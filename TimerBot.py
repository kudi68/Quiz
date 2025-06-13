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
TOTAL_QUESTIONS_PER_PAPER = 100
HISTORY_HEADERS = ['user', 'session_id', 'year', 'paper_type', 'total_questions', 'timeout_questions', 'timeout_ratio']
USER_HEADERS = ['username']

# --- Google Sheets 連線 ---
@st.cache_resource(ttl=600)
def connect_to_gsheet():
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"])
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"無法連接到 Google Sheets，請檢查 Secrets 設定: {e}")
        return None

# --- 使用者管理 (新) ---
def get_worksheet(client, sheet_name, worksheet_name, headers):
    """取得工作表，若不存在則建立"""
    try:
        sheet = client.open(sheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"找不到名為 '{sheet_name}' 的 Google Sheet。請先建立它。")
        return None
    try:
        worksheet = sheet.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=worksheet_name, rows="1", cols=len(headers))
        worksheet.append_row(headers)
    return worksheet

@st.cache_data(ttl=60)
def load_users(_client):
    """從 Google Sheet 載入使用者列表"""
    if not _client: return ["kudi68"] # Fallback
    try:
        worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
        users = worksheet.col_values(1)[1:] # 跳過標頭
        return users if users else ["kudi68"]
    except Exception as e:
        st.warning(f"讀取使用者列表失敗: {e}")
        return ["kudi68"]

def add_user(client, new_user):
    """新增使用者到 Google Sheet"""
    if not client: return False
    try:
        worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_name"], "users", USER_HEADERS)
        worksheet.append_row([new_user])
        st.cache_data.clear() # 清除快取以重新載入使用者列表
        return True
    except Exception as e:
        st.error(f"新增使用者失敗: {e}")
        return False

# --- 歷史紀錄處理 (已更新為支援多使用者) ---
@st.cache_data(ttl=60)
def load_history_from_gsheet(_client, username):
    if not _client: return pd.DataFrame()
    try:
        worksheet = get_worksheet(_client, st.secrets["gsheet"]["sheet_name"], "history", HISTORY_HEADERS)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if df.empty: return pd.DataFrame(columns=HISTORY_HEADERS)
        
        # 過濾出當前使用者的紀錄
        user_df = df[df['user'] == username].copy()

        numeric_cols = ['total_questions', 'timeout_questions', 'timeout_ratio']
        for col in numeric_cols:
            if col in user_df.columns:
                user_df[col] = pd.to_numeric(user_df[col], errors='coerce')
        return user_df
    except Exception as e:
        st.error(f"讀取歷史紀錄時發生錯誤: {e}")
        return pd.DataFrame()

def save_history_to_gsheet(client, new_summary):
    if not client: return
    try:
        worksheet = get_worksheet(client, st.secrets["gsheet"]["sheet_name"], "history", HISTORY_HEADERS)
        worksheet.append_row(list(new_summary.values()))
    except Exception as e:
        st.error(f"儲存紀錄到 Google Sheet 時發生錯誤: {e}")


# --- 報告渲染函式 (已更新為支援多使用者) ---
def render_report_page(user_history_df):
    st.header(f"📊 {st.session_state.logged_in_user} 的學習統計報告")
    # ... 其餘報告渲染邏輯與 v3.0 相同，但現在接收的是過濾後的 user_history_df
    if not st.session_state.records:
        st.warning("目前尚無紀錄可供分析。")
        return

    df = pd.DataFrame(st.session_state.records)
    # ... (此處貼上原本的報告產生程式碼, 使用 df 和 user_history_df) ...
    total_time_sec = df['耗時(秒)'].sum()
    avg_time_sec = df['耗時(秒)'].mean()
    timeout_count = df['是否超時'].sum()
    total_count = len(df)
    timeout_ratio = (timeout_count / total_count) * 100 if total_count > 0 else 0

    st.success(f"**本次共完成 {total_count} 題，總耗時 {format_time(total_time_sec)}，平均每題 {avg_time_sec:.1f} 秒，超時比例 {timeout_ratio:.1f}%。**")
    
    # ... 接下來的 Tabs 邏輯 ...
    # 折線圖部分需要使用 user_history_df
    with st.tabs(["📈 各科平均耗時", "🕒 各科時間佔比", "📉 超時歷史趨勢", "⚠️ 超時清單", "📋 詳細紀錄"])[2]:
        st.subheader("歷次考卷超時比例趨勢")
        history_df = user_history_df.copy()
        current_summary = pd.DataFrame([{'user': st.session_state.logged_in_user, 'session_id': '本次', 'year': st.session_state.year, 'paper_type': st.session_state.paper_type, 'total_questions': total_count, 'timeout_questions': timeout_count, 'timeout_ratio': timeout_ratio}])
        history_df = pd.concat([history_df, current_summary], ignore_index=True)
        # ... 剩餘的圖表邏輯 ...


# --- 狀態初始化 ---
def initialize_app_state():
    if 'gsheet_client' not in st.session_state:
        st.session_state.gsheet_client = connect_to_gsheet()
    if 'logged_in_user' not in st.session_state:
        st.session_state.logged_in_user = None
    if 'studying' not in st.session_state: st.session_state.studying = False
    # ... 其他狀態 ...


# --- 主程式 ---
st.set_page_config(page_title="國考訂正追蹤器 (多人版)", layout="wide", page_icon="✍️")
initialize_app_state()
gs_client = st.session_state.gsheet_client

# --- 登入/使用者選擇畫面 ---
if not st.session_state.logged_in_user:
    st.title("歡迎使用國考高效訂正追蹤器")
    st.header("請選擇或建立您的使用者名稱")

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
            elif new_user in users:
                st.warning("此使用者名稱已存在。")
            else:
                st.warning("請輸入有效的使用者名稱。")

# --- 主應用程式畫面 (登入後) ---
else:
    # --- 側邊欄 ---
    with st.sidebar:
        st.header(f"👋 {st.session_state.logged_in_user}")
        # ... (貼上 v3.0 的完整側邊欄程式碼) ...
        if st.button("登出"):
            for key in st.session_state.keys():
                if key != 'gsheet_client': # 保留連線物件
                    del st.session_state[key]
            st.rerun()

    # --- 主畫面 ---
    if st.session_state.get('viewing_report') or st.session_state.get('confirming_finish') or st.session_state.get('finished'):
        user_history_df = load_history_from_gsheet(gs_client, st.session_state.logged_in_user)
        render_report_page(user_history_df)
        
        # 確認儲存邏輯
        if st.session_state.get('confirming_finish'):
            # ...
            if st.button("💾 確認儲存並結束", type="primary"):
                # 建立包含使用者名稱的 new_summary
                new_summary = {
                    'user': st.session_state.logged_in_user,
                    'session_id': datetime.now().strftime('%Y%m%d%H%M%S'),
                    # ... 其他欄位 ...
                }
                save_history_to_gsheet(gs_client, new_summary)
                # ...
                st.rerun()

    elif st.session_state.get('studying'):
        # ... (貼上 v3.0 的訂正中主畫面邏輯) ...
        pass
    
    else: # 初始歡迎畫面
        st.title(f"歡迎回來, {st.session_state.logged_in_user}!")
        st.header("準備好開始下一次的訂正了嗎？")
        # ... (貼上 v3.0 的開始訂正按鈕與相關邏輯) ...

# 由於程式碼結構變動較大，請務必將上述片段整合進您現有的 v3.0 程式碼中，
# 特別注意 `render_report_page` 的呼叫、儲存邏輯、以及將主應用程式包裹在 `else` 區塊中。
# 為了方便您，建議直接使用一個新的檔案來貼上此完整結構。

