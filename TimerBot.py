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
# FIX: Added webhook_url to user data structure
USER_HEADERS = ['username', 'webhook_url']

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

def get_worksheet(client, sheet_name, worksheet_name, headers):
    try:
        sheet = client.open(sheet_name)
        worksheet = sheet.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=worksheet_name, rows="1", cols=len(headers))
        worksheet.append_row(headers)
    return worksheet

# --- 使用者與歷史紀錄管理 ---
@st.cache_data(ttl=300)
def load_users(_client):
    try:
        worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
        users = worksheet.col_values(1)[1:]
        return users if users else ["kudi68"]
    except Exception:
        return None

def add_user(client, new_user):
    try:
        worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
        # FIX: Add a blank webhook URL for the new user
        worksheet.append_row([new_user, ""])
        st.cache_data.clear()
        return True
    except Exception:
        return False

# FIX: New function to get user-specific webhook
@st.cache_data(ttl=300)
def get_user_webhook(_client, username):
    try:
        worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
        user_list = worksheet.get_all_records()
        for user in user_list:
            if user['username'] == username:
                return user.get('webhook_url', '')
        return ''
    except Exception:
        return ''

# FIX: New function to update user-specific webhook
def update_user_webhook(client, username, webhook_url):
    try:
        worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
        cell = worksheet.find(username)
        if cell:
            worksheet.update_cell(cell.row, 2, webhook_url)
            st.cache_data.clear() # Clear cache to reflect changes
            return True
        return False
    except Exception:
        return False


@st.cache_data(ttl=300)
def load_history_from_gsheet(_client, username):
    try:
        worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_name"], "history", HISTORY_HEADERS)
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
        worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_name"], "history", HISTORY_HEADERS)
        worksheet.append_row(list(new_summary.values()))
        return True
    except Exception:
        return False

# --- 報告渲染函式 ---
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
        if not is_connected:
            st.warning("無法連接至雲端，歷史趨勢圖暫時無法顯示。")
        else:
            history_df = user_history_df.copy()
            current_summary = pd.DataFrame([{'user': st.session_state.logged_in_user, 'session_id': '本次', 'year': st.session_state.year, 'paper_type': st.session_state.paper_type, 'total_questions': total_count, 'timeout_questions': timeout_count, 'timeout_ratio': timeout_ratio}])
            history_df = pd.concat([history_df, current_summary], ignore_index=True)
            history_df['session_label'] = history_df['year'].astype(str) + '-' + history_df['paper_type']
            fig_line = px.line(history_df, x='session_label', y='timeout_ratio', title='超時比例變化', markers=True)
            st.plotly_chart(fig_line, use_container_width=True)
    with tab4:
        st.dataframe(df[df['是否超時'] == True])
    with tab5:
        st.dataframe(df)

# --- 狀態初始化 ---
def initialize_app_state():
    keys_to_init = {
        'gsheet_client': None, 'logged_in_user': None, 'studying': False,
        'finished': False, 'confirming_finish': False, 'viewing_report': False,
        'records': [], 'current_question': None, 'is_paused': False,
        'total_paused_duration': timedelta(0), 'paper_type_init': "醫學一",
        'year': "114", 'gsheet_connection_status': "未連接", 'last_question_num': 0,
        'webhook_url': "", 'initial_timeout': 120, 'snooze_interval': 60
    }
    for key, default_value in keys_to_init.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def snooze(minutes: int):
    if st.session_state.current_question:
        snooze_until = datetime.now() + timedelta(minutes=minutes)
        st.session_state.current_question['next_notification_time'] = snooze_until
        st.toast(f"👍 已設定在 {minutes} 分鐘後提醒。")

# --- 主程式 ---
st.set_page_config(page_title="國考訂正追蹤器 v5.2", layout="wide", page_icon="✍️")
initialize_app_state()

if 'gsheet_client' not in st.session_state or st.session_state.gsheet_client is None:
    client = connect_to_gsheet()
    if client:
        st.session_state.gsheet_client = client
        st.session_state.gsheet_connection_status = "✅ 已同步雲端"
    else:
        st.session_state.gsheet_connection_status = "⚠️ 無法同步歷史紀錄"
gs_client = st.session_state.gsheet_client

if not st.session_state.logged_in_user:
    st.title("歡迎使用國考高效訂正追蹤器")
    st.header("請選擇或建立您的使用者名稱")
    user_list = ["kudi68"]
    if gs_client:
        loaded_users = load_users(gs_client)
        if loaded_users is not None:
            user_list = loaded_users
    selected_user = st.selectbox("選擇您的使用者名稱：", user_list)
    if st.button("登入", type="primary"):
        st.session_state.logged_in_user = selected_user
        if gs_client:
            st.session_state.webhook_url = get_user_webhook(gs_client, selected_user)
        st.rerun()
    with st.expander("或者，建立新使用者"):
        if not gs_client:
            st.warning("無法連接雲端，暫時無法建立新使用者。")
        else:
            new_user = st.text_input("輸入您的新使用者名稱：")
            if st.button("建立並登入"):
                if new_user and new_user not in user_list:
                    if add_user(gs_client, new_user):
                        st.session_state.logged_in_user = new_user
                        st.session_state.webhook_url = "" # New user has no webhook yet
                        st.success(f"使用者 '{new_user}' 建立成功！")
                        time.sleep(1); st.rerun()
                elif new_user in user_list: st.warning("此使用者名稱已存在。")
                else: st.warning("請輸入有效的使用者名稱。")
else:
    # --- 主應用程式畫面 (登入後) ---
    with st.sidebar:
        st.header(f"👋 {st.session_state.logged_in_user}")
        st.info(st.session_state.gsheet_connection_status)
        if st.button("登出"):
            # ... 登出邏輯 ...
            st.rerun()
        st.divider()

        # FIX: Added per-user webhook settings
        st.header("🔔 Discord 設定")
        new_webhook = st.text_input("您的 Webhook 網址", value=st.session_state.webhook_url)
        if st.button("儲存 Webhook 網址"):
            if gs_client:
                if update_user_webhook(gs_client, st.session_state.logged_in_user, new_webhook):
                    st.session_state.webhook_url = new_webhook
                    st.success("Webhook 網址已更新！")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("儲存失敗，請稍後再試。")
            else:
                st.warning("無法連接雲端，儲存失敗。")

        st.divider()
        st.header("⚙️ 初始設定")
        disabled_state = st.session_state.studying or st.session_state.confirming_finish
        st.session_state.year = st.selectbox("考卷年份", [str(y) for y in range(109, 115)], index=5, disabled=disabled_state)
        st.session_state.paper_type_init = st.selectbox("起始試卷別", ["醫學一", "醫學二"], disabled=disabled_state)
        
        # FIX: Added missing action buttons
        if st.session_state.studying:
            st.divider()
            st.header("🕹️ 操作面板")
            if st.button("🧐 預覽當前報告"):
                st.session_state.viewing_report = True
                st.rerun()
            if st.button("🏁 完成訂正", type="primary"):
                st.session_state.confirming_finish = True
                st.session_state.studying = False
                st.rerun()

    # --- 主畫面路由 ---
    if st.session_state.studying:
        main_col, stats_col = st.columns([2, 1.2])
        with main_col:
            st.header("📝 訂正進行中")
            # ... 訂正中 UI ...
        with stats_col:
            st.header("📊 即時狀態")
            # ... 即時狀態 UI ...

    elif st.session_state.finished or st.session_state.viewing_report or st.session_state.confirming_finish:
        history_df = pd.DataFrame()
        if gs_client:
            history_df = load_history_from_gsheet(gs_client, st.session_state.logged_in_user)
        render_report_page(history_df, is_connected=(gs_client is not None))
        # ... 確認儲存與返回邏輯 ...
    else:
        st.title(f"歡迎回來, {st.session_state.logged_in_user}!")
        st.header("準備好開始下一次的訂正了嗎？")
        if st.button("🚀 開始新一次訂正", type="primary", use_container_width=True):
            st.session_state.studying = True
            st.session_state.records = []
            st.session_state.current_question = None
            st.session_state.paper_type = st.session_state.paper_type_init
            st.rerun()

    if st.session_state.studying and st.session_state.current_question and not st.session_state.is_paused:
        time.sleep(1)
        st.rerun()
