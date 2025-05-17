# api_client.py
import os
import time
import requests

# Coba load dari Streamlit secrets dulu
try:
    import streamlit as st
    creds       = st.secrets["deye"]
    EMAIL       = creds["email"]
    PASSWORD    = creds["password"]
    APP_SECRET  = creds["app_secret"]
    APP_ID      = creds["app_id"]
    STATIC_TOKEN = creds.get("token")  # kalau sudah ada token manual
except Exception:
    # fallback ke environment variables
    EMAIL        = os.getenv("DEYE_EMAIL")
    PASSWORD     = os.getenv("DEYE_PASSWORD")
    APP_SECRET   = os.getenv("DEYE_APPSECRET")
    APP_ID       = os.getenv("DEYE_APPID")
    STATIC_TOKEN = os.getenv("DEYE_TOKEN")

# Endpoint untuk dapat token (perubahan appId sebagai query param)
TOKEN_URL  = f"https://eu1-developer.deyecloud.com/v1.0/account/token?appId={APP_ID}"
LATEST_URL = "https://eu1-developer.deyecloud.com/v1.0/device/latest"

# cache sederhana
_token_cache = {"token": None, "expires": 0}

def get_token() -> str:
    """
    Kembalikan STATIC_TOKEN kalau ada, 
    atau gunakan cache, 
    atau login request untuk dapat token baru.
    """
    # 1) pakai token statis dulu
    if STATIC_TOKEN:
        return STATIC_TOKEN

    now = time.time()
    # 2) pakai token cache kalau belum expired
    if _token_cache["token"] and now < _token_cache["expires"] - 60:
        return _token_cache["token"]

    # 3) baru request login
    payload = {
        "email":     EMAIL,
        "password":  PASSWORD,
        "appSecret": APP_SECRET
    }
    resp = requests.post(TOKEN_URL, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    token      = data.get("token")
    expires_in = data.get("expiresIn", 3600)
    _token_cache.update({"token": token, "expires": now + expires_in})
    return token

def fetch_latest(device_list: list) -> dict:
    """
    Fetch latest data untuk daftar serial devices.
    """
    token   = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    body    = {"deviceList": device_list}
    resp    = requests.post(LATEST_URL, json=body, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()
