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

# --- Google Sheets 連線 (更穩定的錯誤處理) ---
@st.cache_resource(ttl=600)
def connect_to_gsheet():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"]
        )
        return gspread.authorize(creds)
    except Exception:
        # 在這裡不顯示錯誤，讓主程式來處理
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
        return None # 連線失敗時返回 None

def add_user(client, new_user):
    try:
        worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
        worksheet.append_row([new_user])
        st.cache_data.clear()
        return True
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
    # ... 其餘報告渲染邏輯 ...
    with st.tabs(["..."])[2]: # 歷史趨勢圖
        if not is_connected:
            st.warning("無法連接至雲端，歷史趨勢圖暫時無法顯示。")
        else:
            # 繪製圖表邏輯
            pass

# --- 狀態初始化 ---
def initialize_app_state():
    keys_to_init = {
        'gsheet_client': None, 'logged_in_user': None, 'studying': False,
        'finished': False, 'confirming_finish': False, 'viewing_report': False,
        'records': [], 'current_question': None, 'is_paused': False,
        'total_paused_duration': timedelta(0), 'paper_type_init': "醫學一",
        'year': "114", 'gsheet_connection_status': "未連接"
    }
    for key, default_value in keys_to_init.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# --- 主程式 ---
st.set_page_config(page_title="國考訂正追蹤器 v5.0", layout="wide", page_icon="✍️")
initialize_app_state()

# 在程式開始時只嘗試連線一次
if st.session_state.gsheet_client is None:
    client = connect_to_gsheet()
    if client:
        st.session_state.gsheet_client = client
        st.session_state.gsheet_connection_status = "✅ 已同步雲端"
    else:
        st.session_state.gsheet_connection_status = "⚠️ 無法同步歷史紀錄"

gs_client = st.session_state.gsheet_client

# 登入畫面邏輯
if not st.session_state.logged_in_user:
    st.title("歡迎使用國考高效訂正追蹤器")
    st.header("請選擇或建立您的使用者名稱")
    
    user_list = ["kudi68"] # 預設值
    if gs_client:
        loaded = load_users(gs_client)
        if loaded is not None:
            user_list = loaded

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
                        st.session_state.logged_in_user = new_user
                        st.success(f"使用者 '{new_user}' 建立成功！")
                        time.sleep(1)
                        st.rerun()
                # ... 其他使用者檢查 ...

# 主應用程式畫面 (登入後)
else:
    with st.sidebar:
        st.header(f"👋 {st.session_state.logged_in_user}")
        st.info(st.session_state.gsheet_connection_status) # 顯示連線狀態
        if st.button("登出"):
            st.session_state.clear()
            st.rerun()
        st.divider()
        # ... 其他側邊欄設定 ...

    # 主畫面路由
    if st.session_state.studying:
        # 訂正中的 UI
        pass
    elif st.session_state.finished or st.session_state.viewing_report or st.session_state.confirming_finish:
        # 報告頁面的 UI
        history_df = pd.DataFrame()
        if gs_client:
            history_df = load_history_from_gsheet(gs_client, st.session_state.logged_in_user)
        render_report_page(history_df, is_connected=(gs_client is not None))
    else:
        # 歡迎畫面的 UI
        st.title(f"歡迎回來, {st.session_state.logged_in_user}!")
        if st.button("🚀 開始新一次訂正", type="primary", use_container_width=True):
            # ... 開始訂正的狀態重設 ...
            st.rerun()

