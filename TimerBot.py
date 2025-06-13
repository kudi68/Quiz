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
        # FIX: Using open_by_url for reliability
        sheet = client.open_by_url(sheet_url)
    except Exception as e:
        st.error(f"無法透過 URL 開啟您的 Google Sheet。請確認 URL 是否正確，且服務帳戶已被設為編輯者。錯誤：{e}")
        return None
    try:
        worksheet = sheet.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=worksheet_name, rows="1", cols=len(headers))
        worksheet.append_row(headers)
    return worksheet

# --- 使用者與歷史紀錄管理 ---
@st.cache_data(ttl=300)
def load_users(_client):
    try:
        # FIX: Pass URL from secrets
        worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_url"], "users", USER_HEADERS)
        if not worksheet: return ["kudi68"] # Fallback
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

# --- 報告渲染函式 ---
def render_report_page(user_history_df, is_connected):
    # ... (omitted for brevity, same as v8.0) ...
    pass

# --- 狀態初始化 ---
def initialize_app_state():
    # ... (omitted for brevity, same as v8.0) ...
    pass

def snooze(minutes: int):
    # ... (omitted for brevity, same as v8.0) ...
    pass

def handle_pause_resume():
    # ... (omitted for brevity, same as v8.0) ...
    pass

# --- 主程式 ---
st.set_page_config(page_title="國考訂正追蹤器 v8.1", layout="wide", page_icon="✍️")
initialize_app_state() # Assume this is defined as in v8.0

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
    # --- Main application logic after login ---
    # ... (omitted for brevity, same as v8.0) ...
    pass
