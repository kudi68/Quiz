import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import plotly.express as px
from datetime import datetime, timedelta
import time
import json

# --- 常數與設定 ---
SUBJECT_MAP = {
    "醫學一": {
        (1, 31): "解剖學", (32, 36): "胚胎學", (37, 46): "組織學",
        (47, 73): "生理學", (74, 100): "生物化學"
    },
    "醫學二": {
        (1, 17): "微生物學", (18, 28): "免疫學", (29, 35): "寄生蟲學",
        (36, 50): "生統與公衛", (51, 75): "藥理學", (76, 100): "病理學"
    }
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

# --- Google Sheets 連線 ---
@st.cache_resource(ttl=600)
def connect_to_gsheet():
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"])
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        # Don't show full error in production
        st.error("無法連接到 Google Sheets，請檢查 Secrets 設定或聯繫管理員。")
        return None

def get_worksheet(client, sheet_name, worksheet_name, headers):
    try:
        sheet = client.open(sheet_name)
        worksheet = sheet.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=worksheet_name, rows="1", cols=len(headers))
        worksheet.append_row(headers)
    except Exception as e:
        st.error(f"無法取得工作表 '{worksheet_name}': {e}")
        return None
    return worksheet

# --- 使用者管理 ---
@st.cache_data(ttl=60)
def load_users(_client):
    if not _client: return ["kudi68"]
    try:
        worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
        if not worksheet: return ["kudi68"]
        users = worksheet.col_values(1)[1:]
        return users if users else ["kudi68"]
    except Exception as e:
        st.warning(f"讀取使用者列表失敗: {e}")
        return ["kudi68"]

def add_user(client, new_user):
    if not client: return False
    try:
        worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
        worksheet.append_row([new_user])
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"新增使用者失敗: {e}")
        return False

# --- 歷史紀錄處理 ---
@st.cache_data(ttl=60)
def load_history_from_gsheet(_client, username):
    if not _client: return pd.DataFrame(columns=HISTORY_HEADERS)
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
    except Exception as e:
        st.error(f"讀取歷史紀錄時發生錯誤: {e}")
        return pd.DataFrame(columns=HISTORY_HEADERS)

def save_history_to_gsheet(client, new_summary):
    if not client: return
    try:
        worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_name"], "history", HISTORY_HEADERS)
        worksheet.append_row(list(new_summary.values()))
    except Exception as e:
        st.error(f"儲存紀錄到 Google Sheet 時發生錯誤: {e}")

# --- 報告渲染函式 ---
def render_report_page(user_history_df):
    st.header(f"📊 {st.session_state.logged_in_user} 的學習統計報告")
    if not st.session_state.records:
        st.warning("目前尚無紀錄可供分析。")
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
        st.subheader("各科目平均訂正時間")
        analysis = df.groupby('科目')['耗時(秒)'].agg(['count', 'mean']).reset_index()
        analysis.columns = ['科目', '訂正題數', '平均耗時(秒)']
        analysis['平均耗時(秒)'] = analysis['平均耗時(秒)'].round(1)
        fig_bar = px.bar(analysis, x='科目', y='平均耗時(秒)', title='各科目平均訂正時間', text='平均耗時(秒)', color='訂正題數', color_continuous_scale=px.colors.sequential.Viridis, hover_data=['訂正題數'])
        st.plotly_chart(fig_bar, use_container_width=True)
    with tab2:
        st.subheader("各科目總耗時佔比")
        time_dist = df.groupby('科目')['耗時(秒)'].sum().reset_index()
        fig_pie = px.pie(time_dist, values='耗時(秒)', names='科目', title='各科目時間分配', hole=.3)
        st.plotly_chart(fig_pie, use_container_width=True)
    with tab3:
        st.subheader("歷次考卷超時比例趨勢")
        history_df = user_history_df.copy()
        current_summary = pd.DataFrame([{'user': st.session_state.logged_in_user, 'session_id': '本次', 'year': st.session_state.year, 'paper_type': st.session_state.paper_type, 'total_questions': total_count, 'timeout_questions': timeout_count, 'timeout_ratio': timeout_ratio}])
        history_df = pd.concat([history_df, current_summary], ignore_index=True)
        if history_df.empty:
            st.info("尚無歷史紀錄，完成一次訂正後即可開始追蹤趨勢。")
        else:
            history_df['session_label'] = history_df['year'].astype(str) + '-' + history_df['paper_type']
            fig_line = px.line(history_df, x='session_label', y='timeout_ratio', title='超時比例變化', markers=True, labels={'session_label': '考卷場次', 'timeout_ratio': '超時比例 (%)'})
            fig_line.update_yaxes(range=[0, 100])
            st.plotly_chart(fig_line, use_container_width=True)
    with tab4:
        timeout_df = df[df['是否超時'] == True]
        if timeout_df.empty: st.success("表現優異！本次沒有超時的題目。")
        else: st.dataframe(timeout_df[['試卷別', '題號', '科目', '耗時(秒)']], use_container_width=True)
    with tab5:
        st.dataframe(df[['試卷別', '題號', '科目', '耗時(秒)']], use_container_width=True)

# --- 狀態初始化 ---
def initialize_app_state():
    if 'gsheet_client' not in st.session_state: st.session_state.gsheet_client = connect_to_gsheet()
    if 'logged_in_user' not in st.session_state: st.session_state.logged_in_user = None
    if 'studying' not in st.session_state: st.session_state.studying = False
    if 'finished' not in st.session_state: st.session_state.finished = False
    if 'confirming_finish' not in st.session_state: st.session_state.confirming_finish = False
    if 'viewing_report' not in st.session_state: st.session_state.viewing_report = False
    if 'records' not in st.session_state: st.session_state.records = []
    if 'current_question' not in st.session_state: st.session_state.current_question = None
    if 'is_paused' not in st.session_state: st.session_state.is_paused = False
    if 'total_paused_duration' not in st.session_state: st.session_state.total_paused_duration = timedelta(0)

# --- 主程式 ---
st.set_page_config(page_title="國考訂正追蹤器 (多人版)", layout="wide", page_icon="✍️")
initialize_app_state()
gs_client = st.session_state.gsheet_client

# --- 登入/使用者選擇畫面 ---
if not st.session_state.logged_in_user:
    st.title("歡迎使用國考高效訂正追蹤器")
    st.header("請選擇或建立您的使用者名稱")
    if gs_client:
        users = load_users(gs_client)
        selected_user = st.selectbox("選擇您的使用者名稱：", users)
        if st.button("登入", type="primary"):
            st.session_state.logged_in_user = selected_user
            st.rerun()
        with st.expander("或者，建立新使用者"):
            new_user = st.text_input("輸入您的新使用者名稱：")
            if st.button("建立並登入"):
                if new_user and new_user not in users:
                    if add_user(gs_client, new_user):
                        st.session_state.logged_in_user = new_user
                        st.success(f"使用者 '{new_user}' 建立成功！")
                        time.sleep(2)
                        st.rerun()
                elif new_user in users: st.warning("此使用者名稱已存在。")
                else: st.warning("請輸入有效的使用者名稱。")

# --- 主應用程式畫面 (登入後) ---
else:
    with st.sidebar:
        st.header(f"👋 {st.session_state.logged_in_user}")
        if st.button("登出"):
            for key in list(st.session_state.keys()):
                if key != 'gsheet_client':
                    del st.session_state[key]
            st.rerun()
        st.divider()
        st.header("⚙️ 初始設定")
        year_options = [str(y) for y in range(109, 115)]
        st.session_state.year = st.selectbox("考卷年份", year_options, index=len(year_options)-1, disabled=st.session_state.studying)
        st.session_state.paper_type_init = st.selectbox("起始試卷別", ["醫學一", "醫學二"], disabled=st.session_state.studying)
        st.session_state.webhook_url = st.text_input("Discord Webhook URL", type="password")

    if st.session_state.get('studying'):
        # 訂正中畫面邏輯...
        pass
    elif st.session_state.get('finished') or st.session_state.get('viewing_report') or st.session_state.get('confirming_finish'):
        user_history_df = load_history_from_gsheet(gs_client, st.session_state.logged_in_user)
        render_report_page(user_history_df)
        # ... 確認儲存與返回邏輯 ...
    else:
        st.title(f"歡迎回來, {st.session_state.logged_in_user}!")
        st.header("準備好開始下一次的訂正了嗎？")
        # --- FIX: 這裡就是之前遺漏的按鈕 ---
        if st.button("🚀 開始新一次訂正", type="primary", use_container_width=True):
            st.session_state.studying = True
            st.session_state.finished = False
            st.session_state.confirming_finish = False
            st.session_state.viewing_report = False
            st.session_state.records = []
            st.session_state.current_question = None
            st.session_state.paper_type = st.session_state.paper_type_init
            st.rerun()
