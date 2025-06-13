import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import plotly.express as px
from datetime import datetime, timedelta
import time
import json

# --- 常數 ---
SUBJECT_MAP = {
    "醫學一": { (1, 31): "解剖學", (32, 36): "胚胎學", (37, 46): "組織學", (47, 73): "生理學", (74, 100): "生物化學" },
    "醫學二": { (1, 17): "微生物學", (18, 28): "免疫學", (29, 35): "寄生蟲學", (36, 50): "生統與公衛", (51, 75): "藥理學", (76, 100): "病理學" }
}
HISTORY_HEADERS = ['user', 'session_id', 'year', 'paper_type', 'total_questions', 'timeout_questions', 'timeout_ratio']
USER_HEADERS = ['username']

# --- 核心函式 ---
def get_subject(paper_type, question_num):
    if paper_type not in SUBJECT_MAP: return "未知科目"
    for (start, end), subject in SUBJECT_MAP[paper_type].items():
        if start <= question_num <= end: return subject
    return "題號範圍外"

def format_time(seconds):
    seconds = max(0, seconds)
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"

def send_discord_notification(webhook_url, embed):
    if not webhook_url or not webhook_url.startswith("https://discord.com/api/webhooks/"):
        st.toast("💡 未設定有效的 Discord Webhook 網址，無法發送通知。")
        return
    try:
        headers = {"Content-Type": "application/json"}
        payload = json.dumps({"embeds": [embed]})
        requests.post(webhook_url, data=payload, headers=headers)
    except Exception:
        st.toast("🔔 Discord 通知發送失敗。")

# --- Google Sheets 連線 ---
@st.cache_resource(ttl=600)
def connect_to_gsheet():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"]
        )
        return gspread.authorize(creds)
    except Exception:
        return None

def get_worksheet(client, sheet_url, worksheet_name, headers):
    try:
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=worksheet_name, rows="1", cols=len(headers))
        worksheet.append_row(headers)
    return worksheet

# --- 使用者與歷史紀錄管理 ---
@st.cache_data(ttl=300)
def load_users(_client):
    try:
        worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_url"], "users", USER_HEADERS)
        if not worksheet: return ["kudi68"]
        users = worksheet.col_values(1)[1:]
        return users if users else ["kudi68"]
    except Exception:
        return None

def add_user(client, new_user):
    try:
        worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_url"], "users", USER_HEADERS)
        worksheet.append_row([new_user])
        st.cache_data.clear()
        return True
    except Exception:
        return False

@st.cache_data(ttl=300)
def load_history_from_gsheet(_client, username):
    try:
        worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_url"], "history", HISTORY_HEADERS)
        if not worksheet: return pd.DataFrame(columns=HISTORY_HEADERS)
        data = worksheet.get_all_records()
        if not data: return pd.DataFrame(columns=HISTORY_HEADERS)
        df = pd.DataFrame(data)
        if 'user' not in df.columns: return pd.DataFrame(columns=HISTORY_HEADERS)
        user_df = df[df['user'] == username].copy()
        for col in ['total_questions', 'timeout_questions', 'timeout_ratio']:
            if col in user_df.columns:
                user_df[col] = pd.to_numeric(user_df[col], errors='coerce')
        return user_df
    except Exception:
        return pd.DataFrame(columns=HISTORY_HEADERS)

def save_history_to_gsheet(client, new_summary):
    try:
        worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_url"], "history", HISTORY_HEADERS)
        worksheet.append_row(list(new_summary.values()))
        return True
    except Exception:
        return False

# --- 報告渲染函式 (完整版) ---
def render_report_page(user_history_df, is_connected):
    st.header(f"📊 {st.session_state.logged_in_user} 的學習統計報告")
    if 'records' not in st.session_state or not st.session_state.records:
        st.warning("目前尚無本次訂正的紀錄可供分析。")
        return
    df = pd.DataFrame(st.session_state.records)
    total_time_sec = df['耗時(秒)'].sum()
    avg_time_sec = df['耗時(秒)'].mean()
    timeout_count = df['是否超時'].sum()
    total_count = len(df)
    timeout_ratio = (timeout_count / total_count) * 100 if total_count > 0 else 0

    st.success(f"**本次共完成 {total_count} 題，總耗時 {format_time(total_time_sec)}，平均每題 {avg_time_sec:.1f} 秒，超時比例 {timeout_ratio:.1f}%。**")
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 各科平均耗時", "🕒 各科時間佔比", "📉 超時歷史趨勢", "⚠️ 超時清單", "📋 詳細紀錄"])

    with tab1:
        analysis = df.groupby('科目')['耗時(秒)'].agg(['count', 'mean']).reset_index()
        analysis.columns = ['科目', '訂正題數', '平均耗時(秒)']
        analysis['平均耗時(秒)'] = analysis['平均耗時(秒)'].round(1)
        fig_bar = px.bar(analysis, x='科目', y='平均耗時(秒)', text='平均耗時(秒)', color='訂正題數')
        st.plotly_chart(fig_bar, use_container_width=True)
    with tab2:
        time_dist = df.groupby('科目')['耗時(秒)'].sum().reset_index()
        fig_pie = px.pie(time_dist, values='耗時(秒)', names='科目', title='各科目時間分配', hole=.3)
        st.plotly_chart(fig_pie, use_container_width=True)
    with tab3:
        st.subheader("歷次考卷超時比例趨勢")
        if not is_connected:
            st.warning("無法連接至雲端，歷史趨勢圖暫時無法顯示。")
        else:
            history_df = user_history_df.copy()
            if not st.session_state.get('finished', False):
                current_summary = pd.DataFrame([{'user': st.session_state.logged_in_user, 'session_id': '本次', 'year': st.session_state.year, 'paper_type': st.session_state.paper_type, 'total_questions': total_count, 'timeout_questions': timeout_count, 'timeout_ratio': timeout_ratio}])
                history_df = pd.concat([history_df, current_summary], ignore_index=True)
            if not history_df.empty:
                history_df['session_label'] = history_df['year'].astype(str) + '-' + history_df['paper_type']
                fig_line = px.line(history_df, x='session_label', y='timeout_ratio', title='超時比例變化', markers=True)
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.info("尚無歷史紀錄。")
    with tab4:
        st.dataframe(df[df['是否超時'] == True])
    with tab5:
        st.dataframe(df)

# --- 狀態初始化 (完整版) ---
def initialize_app_state():
    keys_to_init = {
        'gsheet_client': None, 'logged_in_user': None, 'studying': False,
        'finished': False, 'confirming_finish': False, 'viewing_report': False,
        'records': [], 'current_question': None, 'is_paused': False,
        'total_paused_duration': timedelta(0), 'paper_type_init': "醫學一",
        'year': "114", 'gsheet_connection_status': "未連接", 'last_question_num': 0,
        'webhook_url': "", 'initial_timeout': 120, 'snooze_interval': 60,
        'paper_type': "醫學一"
    }
    for key, default_value in keys_to_init.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def snooze(minutes: int):
    if st.session_state.current_question:
        st.session_state.current_question['next_notification_time'] = datetime.now() + timedelta(minutes=minutes)
        st.toast(f"👍 已設定在 {minutes} 分鐘後提醒。")

def handle_pause_resume():
    if st.session_state.is_paused:
        pause_duration = datetime.now() - st.session_state.pause_start_time
        st.session_state.total_paused_duration += pause_duration
        if 'next_notification_time' in st.session_state.current_question:
            st.session_state.current_question['next_notification_time'] += pause_duration
        st.session_state.is_paused = False
    else:
        st.session_state.pause_start_time = datetime.now()
        st.session_state.is_paused = True

# --- 主程式 ---
st.set_page_config(page_title="國考訂正追蹤器 v9.0", layout="wide", page_icon="✍️")
initialize_app_state()

if 'gsheet_client' not in st.session_state or st.session_state.gsheet_client is None:
    client = connect_to_gsheet()
    if client:
        st.session_state.gsheet_client = client
        st.session_state.gsheet_connection_status = "✅ 歷史紀錄已同步"
    else:
        st.session_state.gsheet_connection_status = "⚠️ 無法同步歷史紀錄"
gs_client = st.session_state.gsheet_client

if not st.session_state.logged_in_user:
    st.title("歡迎使用國考高效訂正追蹤器")
    st.header("請選擇或建立您的使用者名稱")
    user_list = ["kudi68"]
    if gs_client:
        loaded_users = load_users(gs_client)
        if loaded_users is not None: user_list = loaded_users
    selected_user = st.selectbox("選擇您的使用者名稱：", user_list)
    if st.button("登入", type="primary"):
        st.session_state.logged_in_user = selected_user
        st.rerun()
    with st.expander("或者，建立新使用者"):
        if not gs_client:
            st.warning("無法連接雲端，暫時無法建立新使用者。")
        else:
            new_user = st.text_input("輸入您的新使用者名稱：")
            if st.button("建立並登入"):
                if new_user and new_user not in user_list:
                    if add_user(gs_client, new_user):
                        st.session_state.logged_in_user = new_user; st.success(f"使用者 '{new_user}' 建立成功！"); time.sleep(1); st.rerun()
                elif new_user in user_list: st.warning("此使用者名稱已存在。")
                else: st.warning("請輸入有效的使用者名稱。")
else:
    # --- 主應用程式畫面 (登入後) ---
    with st.sidebar:
        st.header(f"👋 {st.session_state.logged_in_user}")
        st.info(st.session_state.gsheet_connection_status)
        if st.button("登出"):
            client, status = st.session_state.gsheet_client, st.session_state.gsheet_connection_status
            st.session_state.clear(); initialize_app_state()
            st.session_state.gsheet_client, st.session_state.gsheet_connection_status = client, status
            st.rerun()
        st.divider()
        st.header("🔔 Discord 設定")
        st.session_state.webhook_url = st.text_input("您的 Webhook 網址", value=st.session_state.webhook_url, help="此設定僅於本次登入有效。")
        st.divider()
        st.header("⚙️ 初始設定")
        disabled_state = st.session_state.studying or st.session_state.confirming_finish
        st.session_state.year = st.selectbox("考卷年份", [str(y) for y in range(109, 115)], index=5, disabled=disabled_state)
        st.session_state.paper_type_init = st.selectbox("起始試卷別", ["醫學一", "醫學二"], disabled=disabled_state)
        if st.session_state.studying:
            st.divider(); st.header("🕹️ 操作面板")
            if st.button("🧐 預覽當前報告"):
                st.session_state.viewing_report = True; st.rerun()
            if st.button("🏁 完成訂正", type="primary"):
                st.session_state.confirming_finish = True; st.session_state.studying = False; st.rerun()

    # --- 主畫面路由 ---
    if st.session_state.studying and not st.session_state.viewing_report and not st.session_state.confirming_finish:
        main_col, stats_col = st.columns([2, 1.2])
        with main_col:
            st.header("📝 訂正進行中"); st.subheader(f"目前試卷：**{st.session_state.year} 年 - {st.session_state.paper_type}**")
            with st.form(key='question_form'):
                q_num_input = st.number_input("輸入題號 (1-100)", min_value=1, max_value=100, step=1, key="q_num_input")
                submitted = st.form_submit_button("✔️ 確認", use_container_width=True)
            if submitted:
                if st.session_state.current_question:
                    end_time = datetime.now()
                    if st.session_state.is_paused: st.session_state.total_paused_duration += (end_time - st.session_state.pause_start_time)
                    duration_sec = (end_time - st.session_state.current_question['start_time'] - st.session_state.total_paused_duration).total_seconds()
                    st.session_state.records.append({"年份": st.session_state.year, "試卷別": st.session_state.paper_type, "題號": st.session_state.current_question['q_num'], "科目": get_subject(st.session_state.paper_type, st.session_state.current_question['q_num']), "耗時(秒)": int(duration_sec), "是否超時": duration_sec > st.session_state.initial_timeout})
                st.session_state.current_question = {"q_num": q_num_input, "start_time": datetime.now(), "next_notification_time": datetime.now() + timedelta(seconds=st.session_state.initial_timeout)}
                st.session_state.is_paused = False; st.session_state.total_paused_duration = timedelta(0)
                st.rerun()
            pause_button_text = "▶️ 繼續" if st.session_state.is_paused else "⏸️ 暫停"
            st.button(pause_button_text, on_click=handle_pause_resume, use_container_width=True)
        with stats_col:
            st.header("📊 即時狀態")
            if st.session_state.current_question:
                q_info = st.session_state.current_question
                if st.session_state.is_paused:
                    elapsed_duration = st.session_state.pause_start_time - q_info['start_time'] - st.session_state.total_paused_duration
                    st.metric("即時訂正時間 (已暫停)", format_time(elapsed_duration.total_seconds()))
                else:
                    elapsed_duration = datetime.now() - q_info['start_time'] - st.session_state.total_paused_duration
                    st.metric("即時訂正時間", format_time(elapsed_duration.total_seconds()))
                st.metric(f"目前題號：{q_info['q_num']}", f"科目：{get_subject(st.session_state.paper_type, q_info['q_num'])}")
                st.markdown("---"); st.write("**延後提醒**")
                snooze_cols = st.columns(3)
                snooze_cols[0].button("1分鐘", on_click=snooze, args=(1,), use_container_width=True)
                snooze_cols[1].button("2分鐘", on_click=snooze, args=(2,), use_container_width=True)
                snooze_cols[2].button("5分鐘", on_click=snooze, args=(5,), use_container_width=True)
            else:
                st.info("請輸入第一題題號，點擊「✔️ 確認」後開始計時。")

    elif st.session_state.finished or st.session_state.viewing_report or st.session_state.confirming_finish:
        history_df = pd.DataFrame()
        if gs_client: history_df = load_history_from_gsheet(gs_client, st.session_state.logged_in_user)
        render_report_page(history_df, is_connected=(gs_client is not None))
        
        if st.session_state.viewing_report:
            if st.button("⬅️ 返回繼續訂正"):
                st.session_state.viewing_report = False; st.rerun()
        elif st.session_state.confirming_finish:
            st.warning("您即將結束本次訂正，請確認數據是否正確。")
            c1, c2 = st.columns(2)
            if c1.button("💾 確認儲存並結束", type="primary"):
                if st.session_state.records:
                    if gs_client:
                        df = pd.DataFrame(st.session_state.records)
                        timeout_count = df['是否超時'].sum(); total_count = len(df)
                        timeout_ratio = (timeout_count / total_count) * 100 if total_count > 0 else 0
                        new_summary = {'user': st.session_state.logged_in_user, 'session_id': datetime.now().strftime('%Y%m%d%H%M%S'), 'year': st.session_state.year, 'paper_type': st.session_state.paper_type, 'total_questions': total_count, 'timeout_questions': int(timeout_count), 'timeout_ratio': timeout_ratio}
                        if save_history_to_gsheet(gs_client, new_summary): st.toast("紀錄已儲存至雲端！")
                        else: st.toast("⚠️ 無法儲存紀錄至雲端。")
                st.session_state.confirming_finish = False; st.session_state.finished = True; st.rerun()
            if c2.button("❌ 取消"):
                st.session_state.confirming_finish = False; st.session_state.studying = True; st.rerun()
    else:
        st.title(f"歡迎回來, {st.session_state.logged_in_user}!")
        st.header("準備好開始下一次的訂正了嗎？")
        if st.button("🚀 開始新一次訂正", type="primary", use_container_width=True):
            st.session_state.studying = True; st.session_state.finished = False; st.session_state.viewing_report = False; st.session_state.confirming_finish = False
            st.session_state.records = []; st.session_state.current_question = None
            st.session_state.paper_type = st.session_state.paper_type_init
            st.rerun()

    if st.session_state.studying and st.session_state.current_question and not st.session_state.is_paused:
        time.sleep(1); st.rerun()
