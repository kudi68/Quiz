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

# --- Google Sheets 連線 (錯誤處理強化版) ---
@st.cache_resource(ttl=600)
def connect_to_gsheet():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"]
        )
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"金鑰或權限範圍設定錯誤，請檢查 Secrets: {e}")
        return None

def get_worksheet(client, sheet_name, worksheet_name, headers):
    try:
        sheet = client.open(sheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"錯誤：在您的 Google 雲端硬碟中找不到名為 '{sheet_name}' 的 Google Sheet 檔案。請檢查 Streamlit Secrets 中的 `sheet_name` 是否與您的檔案名稱完全相符。")
        return None
    except Exception as e:
        st.error(f"嘗試開啟 Google Sheet '{sheet_name}' 時發生錯誤：{e}。這通常是權限問題或 Secrets 設定不正確。")
        return None

    try:
        worksheet = sheet.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        try:
            worksheet = sheet.add_worksheet(title=worksheet_name, rows="1", cols=len(headers))
            worksheet.append_row(headers)
            st.info(f"已自動為您建立新的工作表 '{worksheet_name}'。")
        except Exception as e:
            st.error(f"嘗試建立新工作表 '{worksheet_name}' 時發生錯誤：{e}。請檢查服務帳戶是否有此試算表的『編輯者』權限。")
            return None
    except Exception as e:
        st.error(f"嘗試存取工作表 '{worksheet_name}' 時發生錯誤：{e}")
        return None
    return worksheet


# --- 使用者與歷史紀錄管理 (與前版相同) ---
@st.cache_data(ttl=60)
def load_users(_client):
    if not _client: return ["kudi68"]
    worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
    if not worksheet: return ["kudi68"]
    users = worksheet.col_values(1)[1:]
    return users if users else ["kudi68"]

def add_user(client, new_user):
    if not client: return False
    worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
    if not worksheet: return False
    worksheet.append_row([new_user])
    st.cache_data.clear()
    return True

@st.cache_data(ttl=60)
def load_history_from_gsheet(_client, username):
    if not _client: return pd.DataFrame(columns=HISTORY_HEADERS)
    worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_name"], "history", HISTORY_HEADERS)
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

def save_history_to_gsheet(client, new_summary):
    if not client: return
    worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_name"], "history", HISTORY_HEADERS)
    if not worksheet: return
    worksheet.append_row(list(new_summary.values()))


# --- 報告渲染函式 (與前版相同) ---
def render_report_page(user_history_df):
    st.header(f"📊 {st.session_state.logged_in_user} 的學習統計報告")
    if 'records' not in st.session_state or not st.session_state.records:
        st.warning("目前尚無本次訂正的紀錄可供分析。")
        return
    # ... 其餘報告渲染邏輯 ...


# --- 狀態初始化 ---
def initialize_app_state():
    if 'gsheet_client' not in st.session_state: st.session_state.gsheet_client = connect_to_gsheet()
    # ... 其他狀態初始化 ...

# --- 主程式 ---
st.set_page_config(page_title="國考訂正追蹤器 (多人版)", layout="wide", page_icon="✍️")
initialize_app_state()
gs_client = st.session_state.gsheet_client

if not st.session_state.logged_in_user:
    st.title("歡迎使用國考高效訂正追蹤器")
    st.header("請選擇或建立您的使用者名稱")
    if gs_client:
        # ... 登入邏輯 ...
        pass
    else:
        st.warning("正在等待與 Google Sheets 建立連線... 如果持續顯示此訊息，請依照除錯清單檢查您的設定。")
else:
    # --- 主應用程式畫面 (登入後) ---
    # ... 側邊欄與主畫面邏輯 ...
    pass

