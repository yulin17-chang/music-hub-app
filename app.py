import streamlit as st
import pandas as pd
from collections import Counter
import re
import json
import os
import time
from ytmusicapi import YTMusic
import datetime
import base64
import uuid
import textwrap
import random
from PIL import Image, ImageOps
import io
import hashlib
import streamlit.components.v1 as components

# --- 1. 全局設定 ---

st.set_page_config(page_title="Music Hub", page_icon="🎵", layout="wide")

@st.cache_resource
def get_ytmusic():
    return YTMusic()

yt = get_ytmusic()
DATA_FILE = 'music_library.json'

# --- 2. 狀態初始化 ---

def get_default_user_data(password_hash=""):
    return {
        "password": password_hash,
        "avatar": None, 
        "playlists": {"已按讚的歌曲": []}, 
        "favorites": {},              
        "chat_history": [],
        "pet_data": {"energy": 0, "last_update": time.time(), "type": "cat", "daily_play_count": 0, "daily_add_count": 0, "claimed_tasks": []}
    }

def init_session_state():
    """強制檢查並初始化所有必要的 Session State 變數"""
    defaults = {
        "current_user": None,
        "user_avatar": None,
        "playlists": {"已按讚的歌曲": []},
        "favorites": {},
        "chat_history": [],
        "pet_data": get_default_user_data()["pet_data"],
        "current_playlist": "已按讚的歌曲",
        "search_results": [],
        "current_playing": None,
        "play_context": "search",
        "new_playlist_name": "",
        "main_nav": "🔍 搜尋歌曲",
        "inited": True
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# 在程式最開頭執行初始化
init_session_state()

# --- 3. 輔助函式 ---

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def crop_image_to_square(image_file):
    try:
        img = Image.open(image_file)
        img = ImageOps.exif_transpose(img)
        width, height = img.size
        new_size = min(width, height)
        left = (width - new_size) / 2
        top = (height - new_size) / 2
        right = (width + new_size) / 2
        bottom = (height + new_size) / 2
        img = img.crop((left, top, right, bottom))
        img.thumbnail((300, 300))
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        return base64.b64encode(img_byte_arr.getvalue()).decode()
    except Exception:
        return None

def detect_language(text):
    if re.search(r'[\u3040-\u30ff]', text): return "JP"
    if re.search(r'[\uac00-\ud7af]', text): return "KR"
    if re.search(r'[\u4e00-\u9fff]', text): return "TW"
    return "EN"

def guess_genre(title):
    t = title.lower()
    if any(x in t for x in ['rock', 'band', 'metal']): return "Rock"
    if any(x in t for x in ['remix', 'edm', 'dj']): return "Electronic"
    if any(x in t for x in ['ballad', 'piano', 'sad']): return "Ballad"
    if any(x in t for x in ['rap', 'hip hop']): return "HipHop"
    return "Pop"

def search_music(query, limit=10):
    try:
        # 修正策略：混合搜尋
        # 1. 先嘗試搜尋「歌曲 (Songs)」
        results = yt.search(query, filter='songs', limit=limit)
        
        # 2. 如果結果太少（少於 5 首），可能是 MV 或翻唱，擴大搜尋「影片 (Videos)」
        if len(results) < 5:
            video_results = yt.search(query, filter='videos', limit=limit)
            results.extend(video_results)
            
        songs = []
        seen_ids = set() # 用來過濾重複的歌曲
        
        for track in results:
            if 'videoId' not in track: continue
            if track['videoId'] in seen_ids: continue # 避免重複
            
            seen_ids.add(track['videoId'])
            
            title = track['title']
            # 處理藝人欄位 (Video 類型的結構可能略有不同)
            artists = ", ".join([a['name'] for a in track.get('artists', [])])
            
            # 處理縮圖
            thumbnails = track.get('thumbnails', [])
            thumbnail = thumbnails[-1]['url'] if thumbnails else ""
            
            # 處理專輯 (Video 通常沒有專輯，給個預設值)
            if 'album' in track and track['album']:
                album_name = track['album'].get('name', 'Single')
            else:
                album_name = 'Video / Single'

            songs.append({
                "id": track['videoId'],
                "title": title,
                "artist": artists,
                "album": album_name,
                "duration": track.get('duration', '--:--'),
                "thumbnail": thumbnail,
                "link": f"https://www.youtube.com/watch?v={track['videoId']}",
                "lang": detect_language(title + " " + artists),
                "genre": guess_genre(title),
                "year": "Unknown"
            })
        
        # 只回傳前 N 筆，避免列表過長
        return songs[:limit]
    except Exception as e:
        print(f"Search Error: {e}")
        return []

def ai_recommend_songs(user_mood):
    mood_keywords = {
        "開心": "Upbeat happy pop songs",
        "難過": "Sad emotional ballad songs",
        "放鬆": "Lofi hip hop chill",
        "專注": "Focus study music piano",
        "運動": "Workout gym motivation music",
        "派對": "Party dance edm hits",
        "失戀": "Heartbreak songs",
        "睡覺": "Sleep music ambient",
    }
    search_term = f"{user_mood} songs playlist"
    for key, value in mood_keywords.items():
        if key in user_mood:
            search_term = value
            break
    return search_music(search_term, limit=10)

# --- 4. 資料管理 ---

def load_all_data():
    default_db = {"users": {}}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "users" not in data: return default_db
                return data
        except Exception:
            return default_db
    return default_db

def save_current_user_data():
    if not st.session_state.current_user: return 
    username = st.session_state.current_user
    all_data = load_all_data()
    
    if username not in all_data["users"]: return 
    
    current_saved_data = all_data["users"][username]
    current_saved_data["playlists"] = st.session_state.playlists
    current_saved_data["favorites"] = st.session_state.favorites
    current_saved_data["chat_history"] = st.session_state.chat_history[-50:]
    current_saved_data["pet_data"] = st.session_state.pet_data
    current_saved_data["avatar"] = st.session_state.user_avatar
    
    all_data["users"][username] = current_saved_data
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=4)
    except Exception: pass

def switch_user(username):
    all_data = load_all_data()
    if username not in all_data["users"]: 
        user_data = get_default_user_data()
    else: 
        user_data = all_data["users"][username]

    st.session_state.current_user = username
    st.session_state.user_avatar = user_data.get("avatar", None)
    st.session_state.playlists = user_data.get("playlists", {"已按讚的歌曲": []})
    st.session_state.favorites = user_data.get("favorites", {})
    st.session_state.chat_history = user_data.get("chat_history", [])
    st.session_state.pet_data = user_data.get("pet_data", get_default_user_data()["pet_data"])
    current_pl = list(st.session_state.playlists.keys())[0] if st.session_state.playlists else "已按讚的歌曲"
    st.session_state.current_playlist = current_pl

# --- 5. Callbacks ---

def check_and_claim_task(task_type):
    if not st.session_state.current_user: return
    
    today_str = datetime.date.today().isoformat()
    pet_data = st.session_state.pet_data
    
    task_play_id = f"task_play_{today_str}"
    task_add_id = f"task_add_{today_str}"
    
    reward = 0
    message = ""
    
    if task_type == 'play':
        pet_data["daily_play_count"] += 1
        if pet_data["daily_play_count"] >= 1 and task_play_id not in pet_data["claimed_tasks"]:
            reward = 10
            pet_data["claimed_tasks"].append(task_play_id)
            message = "🎵 完成播放任務！能量 +10"
            
    elif task_type == 'add':
        pet_data["daily_add_count"] += 1
        if pet_data["daily_add_count"] >= 1 and task_add_id not in pet_data["claimed_tasks"]:
            reward = 20
            pet_data["claimed_tasks"].append(task_add_id)
            message = "➕ 完成新增任務！能量 +20"
            
    if reward > 0:
        pet_data["energy"] = min(100, pet_data["energy"] + reward)
        st.toast(message, icon="⚡")
        
    save_current_user_data()

def add_to_playlist(song, playlist_name=None):
    if not st.session_state.current_user:
        st.toast("請先登入", icon="🔒")
        return
    target = playlist_name if playlist_name else st.session_state.current_playlist
    if target not in st.session_state.playlists:
        st.session_state.playlists[target] = []
        
    current_list = st.session_state.playlists[target]
    if not any(s['id'] == song['id'] for s in current_list):
        st.session_state.playlists[target].append(song)
        st.toast(f"已加入 {target}", icon="💚")
        check_and_claim_task('add') 
    else:
        st.toast("歌曲已存在", icon="⚠️")

def play_song(song_id, context="search"):
    st.session_state.current_playing = song_id
    st.session_state.play_context = context
    if st.session_state.current_user:
        check_and_claim_task('play')

def create_new_playlist():
    if not st.session_state.current_user: return
    new_name = st.session_state.new_playlist_name
    if new_name and new_name not in st.session_state.playlists:
        st.session_state.playlists[new_name] = []
        st.session_state.current_playlist = new_name
        st.session_state.new_playlist_name = ""
        st.session_state.main_nav = "💿 當前歌單"
        save_current_user_data()
        st.toast(f"建立歌單：{new_name}", icon="📁")

def delete_playlist(name):
    if name == "已按讚的歌曲": 
        st.toast("無法刪除預設歌單", icon="🚫")
        return
    if name in st.session_state.playlists:
        del st.session_state.playlists[name]
        st.session_state.current_playlist = "已按讚的歌曲"
        save_current_user_data()
        st.toast(f"已刪除歌單：{name}", icon="🗑️")

def on_avatar_upload():
    uploaded_file = st.session_state.avatar_uploader_key
    if uploaded_file:
        b64_str = crop_image_to_square(uploaded_file)
        if b64_str:
            st.session_state.user_avatar = b64_str
            save_current_user_data()
            st.toast("頭像更新成功", icon="✨")

# --- 6. CSS 設定 ---

def inject_spotify_css():
    css = f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Circular+Std:wght@400;700&family=Noto+Sans+TC:wght@400;700&display=swap');
        
        html, body, [class*="css"] {{
            font-family: 'Circular Std', 'Noto Sans TC', sans-serif;
            background-color: #F8F0FC !important;
            color: #4A4A4A !important;
        }}
        
        [data-testid="stDecoration"] {{
            display: none;
        }}

        footer {{visibility: hidden;}}
        
        .block-container {{
            padding-top: 6rem !important;
            padding-bottom: 50px !important; 
        }}

        @media (max-width: 640px) {{
            .block-container {{
                padding-bottom: 100px;
            }}
        }}

        section[data-testid="stSidebar"] {{
            background-color: #E1BEE7 !important;
            background-image: linear-gradient(180deg, #E1BEE7 0%, #F3E5F5 100%);
            border-right: 1px solid #D1C4E9;
            width: 350px !important;
        }}
        
        section[data-testid="stSidebar"] h1 {{
            color: #4A148C !important;
            font-weight: 900;
        }}

        div[role="radiogroup"] {{
            background: transparent;
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }}
        
        div[role="radiogroup"] label {{
            background-color: #FFFFFF !important;
            border-radius: 50px !important;
            color: #6A1B9A !important;
            border: 1px solid #E1BEE7 !important;
            padding: 5px 15px !important;
            transition: all 0.2s ease;
            box-shadow: 0 2px 4px rgba(0,0,0,0.02);
        }}
        
        div[role="radiogroup"] label:hover {{
            background-color: #F3E5F5 !important;
            transform: scale(1.05);
        }}
        
        div[role="radiogroup"] label:has(input:checked) {{
            background-color: #BA68C8 !important;
            color: #FFFFFF !important;
            border-color: #BA68C8 !important;
            box-shadow: 0 4px 10px rgba(186, 104, 200, 0.4);
        }}
        
        div[role="radiogroup"] label:has(input:checked) p {{
            color: #FFFFFF !important;
        }}
        
        div[role="radiogroup"] label > div:first-child {{
            display: none !important;
        }}

        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background-color: #FFFFFF !important;
            border: 1px solid #F3E5F5 !important;
            border-radius: 16px !important;
            padding: 15px !important;
            margin-bottom: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.02);
        }}

        .stButton button[kind="primary"] {{
            background: linear-gradient(135deg, #BA68C8 0%, #9C27B0 100%) !important;
            color: white !important;
            border-radius: 50px !important;
            border: none !important;
        }}
        
        .stButton button[kind="secondary"] {{
            background-color: transparent !important;
            color: #9C27B0 !important;
            border: 2px solid #E1BEE7 !important;
            border-radius: 50px !important;
        }}

        .stTextInput input {{
            background-color: #FFFFFF !important;
            border: 2px solid #E1BEE7 !important;
            border-radius: 12px !important;
            color: #4A4A4A !important;
        }}
        
        .spotify-avatar {{
            width: 140px;
            height: 140px;
            object-fit: cover;
            border-radius: 50%;
            box-shadow: 0 8px 24px rgba(156, 39, 176, 0.2);
            margin-bottom: 15px;
            border: 4px solid #FFFFFF;
        }}
        
        [data-testid="stFileUploader"] section[tabindex="0"] + section {{
            display: none;
        }}
        
        div[data-testid="column"]:nth-of-type(4) {{
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        
        div[data-testid="column"]:nth-of-type(4) .stButton {{
            margin: 0 2px;
        }}
    </style>
    """
    st.markdown(textwrap.dedent(css), unsafe_allow_html=True)

# --- 7. 介面佈局 (UI) ---

inject_spotify_css()

# === 左側邊欄 ===
with st.sidebar:
    if st.session_state.current_user:
        st.markdown(f"## 🎵 歡迎回來！")
        
        if st.session_state.user_avatar:
            st.markdown(f'<div style="text-align:center"><img src="data:image/png;base64,{st.session_state.user_avatar}" class="spotify-avatar"></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="text-align:center; font-size:100px; margin-bottom:20px;">👤</div>', unsafe_allow_html=True)
        
        st.markdown(f"<div style='text-align:center; font-weight:bold; font-size:1.5rem; margin-bottom:20px; color:#4A148C;'>{st.session_state.current_user}</div>", unsafe_allow_html=True)
        
        with st.expander("⚙️ 帳號設定"):
            st.caption("更換頭像")
            st.file_uploader("選擇圖片", type=['png', 'jpg'], key="avatar_uploader_key", label_visibility="collapsed", on_change=on_avatar_upload)
            
            st.caption("修改密碼")
            new_pw = st.text_input("新密碼", type="password", key="widget_new_pw", label_visibility="collapsed")
            if st.button("更新密碼", key="btn_pw"):
                if new_pw:
                    all_data = load_all_data()
                    if st.session_state.current_user in all_data["users"]:
                        all_data["users"][st.session_state.current_user]["password"] = hash_password(new_pw)
                        with open(DATA_FILE, 'w', encoding='utf-8') as f:
                            json.dump(all_data, f, ensure_ascii=False, indent=4)
                        st.toast("密碼已更新", icon="✅")
                        time.sleep(1)
                        st.rerun()
        
        if st.button("登出", use_container_width=True, type="secondary"):
            st.session_state.clear()
            st.rerun()
            
    else:
        st.markdown("## 🎵 Music Hub")
        st.info("請先登入才能儲存歌單哦！")
        u_name = st.text_input("帳號", key="login_name")
        u_pass = st.text_input("密碼", type="password", key="login_pass")
        
        if st.button("登入 / 註冊", type="primary", use_container_width=True):
            if u_name and u_pass:
                all_data = load_all_data()
                hashed_pw = hash_password(u_pass)
                
                if u_name in all_data["users"]:
                    stored_pw = all_data["users"][u_name].get("password")
                    if stored_pw == hashed_pw or stored_pw == u_pass:
                        if stored_pw == u_pass:
                             all_data["users"][u_name]["password"] = hashed_pw
                             with open(DATA_FILE, 'w', encoding='utf-8') as f:
                                json.dump(all_data, f, ensure_ascii=False, indent=4)
                        switch_user(u_name)
                        st.rerun()
                    else:
                        st.error("密碼錯誤")
                else:
                    new_data = get_default_user_data(hashed_pw)
                    all_data["users"][u_name] = new_data
                    with open(DATA_FILE, 'w', encoding='utf-8') as f:
                        json.dump(all_data, f, ensure_ascii=False, indent=4)
                    switch_user(u_name)
                    st.rerun()
        
        @st.dialog("重設密碼")
        def reset_pw_dialog():
            rn = st.text_input("帳號")
            np = st.text_input("新密碼", type="password")
            if st.button("確認"):
                all_data = load_all_data()
                if rn in all_data["users"]:
                    all_data["users"][rn]["password"] = hash_password(np)
                    with open(DATA_FILE, 'w', encoding='utf-8') as f:
                        json.dump(all_data, f, ensure_ascii=False, indent=4)
                    st.success("重設成功")
                    st.rerun()
                else:
                    st.error("找不到帳號")
        
        if st.button("忘記密碼？", use_container_width=True, type="secondary"):
            reset_pw_dialog()

    st.markdown("---")
    
    st.markdown("### 🎧 您的歌單列表")
    
    with st.popover("➕ 建立歌單", use_container_width=True):
        new_pl_name = st.text_input("歌單名稱")
        if st.button("建立", type="primary"):
            if new_pl_name:
                st.session_state.new_playlist_name = new_pl_name
                create_new_playlist()
                st.rerun()

    if st.session_state.current_user:
        for pl_name in st.session_state.playlists.keys():
            is_active = (st.session_state.current_playlist == pl_name)
            btn_type = "primary" if is_active else "secondary"
            
            if pl_name != "已按讚的歌曲":
                c_pl_1, c_pl_2 = st.columns([4, 1])
                with c_pl_1:
                    if st.button(f"📂 {pl_name}", key=f"nav_{pl_name}", use_container_width=True, type=btn_type):
                        st.session_state.current_playlist = pl_name
                        st.session_state.main_nav = "💿 當前歌單"
                        st.rerun()
                with c_pl_2:
                    if st.button("🗑️", key=f"del_pl_{pl_name}", help="刪除此歌單"):
                        delete_playlist(pl_name)
                        st.rerun()
            else:
                 if st.button(f"❤️ {pl_name}", key=f"nav_{pl_name}", use_container_width=True, type=btn_type):
                        st.session_state.current_playlist = pl_name
                        st.session_state.main_nav = "💿 當前歌單"
                        st.rerun()

# === 主內容區 ===

selected_tab = st.radio(
    "Main Nav",
    ["🔍 搜尋歌曲", "💿 當前歌單", "✨ 音樂助理", "🐱 心情寵物"],
    horizontal=True,
    label_visibility="collapsed",
    key="main_nav"
)

st.markdown("<br>", unsafe_allow_html=True)

# 1. 首頁 (搜尋)
if "首頁" in selected_tab or "搜尋" in selected_tab:
    query = st.text_input("想播放什麼內容？", placeholder="藝人、歌曲或 Podcast", label_visibility="collapsed")
    
    if query:
        with st.spinner("搜尋中..."):
            st.session_state.search_results = search_music(query)
            
    if st.session_state.search_results:
        st.markdown("### 搜尋結果")
        for song in st.session_state.search_results:
            with st.container(border=True): 
                c1, c2, c3, c4 = st.columns([1, 4, 1, 1], vertical_alignment="center")
                with c1:
                    if song['thumbnail']: st.image(song['thumbnail'], width=60)
                with c2:
                    st.markdown(f"**{song['title']}**")
                    st.caption(song['artist'])
                with c3:
                    if st.button("▶", key=f"play_s_{song['id']}"):
                        play_song(song['id'], context="search")
                        st.rerun()
                with c4:
                    if st.button("➕", key=f"add_s_{song['id']}"):
                        add_to_playlist(song)
    # 修正：新增無結果提示
    elif query:
        st.warning(f"找不到關於「{query}」的歌曲，試試看其他關鍵字？", icon="🙈")

# 2. 目前歌單
elif "歌單" in selected_tab:
    pl_name = st.session_state.current_playlist
    if pl_name not in st.session_state.playlists:
        pl_name = "已按讚的歌曲"
        st.session_state.current_playlist = pl_name

    songs = st.session_state.playlists[pl_name]
    
    st.markdown(f"""
    <div style="padding: 20px; border-radius: 8px; background: linear-gradient(to bottom, #E1BEE7 0%, transparent 100%);">
        <h1 style="margin: 0; font-size: 3rem; color: #4A148C;">{pl_name}</h1>
        <p style="opacity: 0.8; color: #6A1B9A;">{st.session_state.current_user} • {len(songs)} 首歌曲</p>
    </div>
    """, unsafe_allow_html=True)
    
    c_p1, c_p2, c_p3 = st.columns([1, 1, 4])
    with c_p1:
        if st.button("▶ 播放", type="primary", use_container_width=True, key="btn_play_all"):
            if songs: 
                play_song(songs[0]['id'], context="playlist")
                st.rerun()
    with c_p2:
        if st.button("🔀 隨機", type="primary", use_container_width=True, key="btn_shuffle"):
            if songs: 
                play_song(random.choice(songs)['id'], context="playlist")
                st.rerun()
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    h1, h2, h3, h4 = st.columns([0.5, 4, 1.5, 1.5]) 
    h1.caption("#")
    h2.caption("曲目")
    h3.caption("專輯")
    h4.caption("操作")
    
    for idx, song in enumerate(songs):
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([0.5, 4, 1.5, 1.5], vertical_alignment="center")
            c1.markdown(f"{idx + 1}")
            with c2:
                sc1, sc2 = st.columns([1, 4])
                with sc1:
                    if song.get('thumbnail'): st.image(song['thumbnail'], width=40)
                with sc2:
                    st.markdown(f"**{song['title']}**")
                    st.caption(song['artist'])
            with c3:
                st.caption(song.get('album', 'Single'))
            with c4:
                b1, b2 = st.columns([1, 1], gap="small")
                with b1:
                    if st.button("▶", key=f"pl_p_{idx}_{pl_name}"):
                        play_song(song['id'], context="playlist")
                        st.rerun()
                with b2:
                    if st.button("🗑️", key=f"pl_d_{idx}_{pl_name}"):
                        st.session_state.playlists[pl_name].pop(idx)
                        save_current_user_data()
                        st.rerun()

# 3. AI 顧問
elif "AI" in selected_tab or "助理" in selected_tab:
    st.markdown("### 🤖 音樂小幫手")
    
    with st.container(border=True):
        with st.form("chat_form", clear_on_submit=True):
            user_input = st.text_input("想聽點什麼？", placeholder="例如：適合深夜的放鬆音樂...", label_visibility="collapsed")
            sent = st.form_submit_button("傳送", use_container_width=True, type="primary")
            
    if sent and user_input:
        current_time = datetime.datetime.now().strftime("%H:%M")
        user_msg = {"role": "user", "content": user_input, "time": current_time, "id": str(uuid.uuid4())}
        st.session_state.chat_history.append(user_msg)
        
        with st.spinner("音樂助理正在挑歌..."):
            recs = ai_recommend_songs(user_input)
            
            ai_msg = {
                "role": "assistant", 
                "content": f"這是為您挑選的歌單：", 
                "songs": recs,
                "id": str(uuid.uuid4()),
                "time": current_time
            }
            st.session_state.chat_history.append(ai_msg)
        
        save_current_user_data()
        st.rerun()

    if not st.session_state.chat_history:
        st.info("快跟音樂助理聊聊吧！")
    
    history = st.session_state.chat_history
    conversations = []
    temp_group = []

    for msg in history:
        temp_group.append(msg)
        if msg['role'] == 'assistant':
            conversations.append(temp_group)
            temp_group = []
    if temp_group:
        conversations.append(temp_group)

    for group in reversed(conversations):
        for msg in group:
            if msg['role'] == 'user':
                with st.container(border=True):
                    st.caption(f"👤 {msg.get('time', '')}")
                    st.write(msg["content"])
            elif msg['role'] == 'assistant':
                with st.container(border=True):
                    st.caption(f"✨ 音樂小幫手")
                    st.write(msg["content"])
                    
                    if "songs" in msg and msg["songs"]:
                        if st.button("加入全部到歌單", key=f"add_all_{msg['id']}"):
                            for s in msg['songs']: add_to_playlist(s)
                        
                        for s in msg['songs']:
                            with st.container(border=True):
                                sc1, sc2, sc3, sc4 = st.columns([1, 4, 1, 1], vertical_alignment="center")
                                sc1.image(s['thumbnail'], width=40)
                                sc2.markdown(f"**{s['title']}** - {s['artist']}")
                                with sc3:
                                    if st.button("▶", key=f"ai_p_{msg['id']}_{s['id']}"):
                                        play_song(s['id'], context="ai")
                                        st.rerun()
                                with sc4:
                                    if st.button("➕", key=f"ai_add_{msg['id']}_{s['id']}"):
                                        add_to_playlist(s)

# 4. 心情寵物
elif "寵物" in selected_tab:
    if not st.session_state.current_user:
        st.warning("請先登入以飼養寵物")
    else:
        pet_data = st.session_state.pet_data
        
        songs = st.session_state.playlists.get(st.session_state.current_playlist, [])
        mood = "平靜"
        if songs:
            genres = [s.get('genre', 'Pop') for s in songs]
            if genres: mood = Counter(genres).most_common(1)[0][0]
        
        energy = pet_data['energy']
        pet_emoji = "🐱" if pet_data['type']=='cat' else "🐶"
        if energy < 30: pet_emoji = "😿" if pet_data['type']=='cat' else "🥺"
        
        st.markdown(f"""
        <div style="text-align:center; padding: 40px; background-color: #FFFFFF; border-radius: 20px; border: 1px solid #E1BEE7; box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-bottom: 20px;">
            <div style="font-size: 10rem; animation: float 3s infinite ease-in-out;">{pet_emoji}</div>
            <div style="margin-top:20px; background:#F3E5F5; padding:15px; border-radius:15px; display:inline-block; font-size: 1.2rem; color: #6A1B9A;">
                {mood} 的氛圍真不錯... 🎵
            </div>
        </div>
        <style>
            @keyframes float {{
                0% {{ transform: translateY(0px); }}
                50% {{ transform: translateY(-15px); }}
                100% {{ transform: translateY(0px); }}
            }}
        </style>
        """, unsafe_allow_html=True)
        
        with st.container(border=True):
            st.markdown("### 您的心情寵物")
            pet_type = st.selectbox("選擇動物", ["貓咪 🐱", "狗狗 🐶"], index=0 if pet_data['type']=='cat' else 1)
            
            new_type_key = "cat" if "貓" in pet_type else "dog"
            if new_type_key != pet_data["type"]:
                st.session_state.pet_data["type"] = new_type_key
                save_current_user_data()
                st.rerun()
            
            st.progress(energy/100, text=f"能量: {energy}%")
            if energy < 30: st.error("我餓了...")
            
            st.markdown("---")
            st.markdown("#### 已解鎖的任務")
            p_done = pet_data['daily_play_count'] >= 1
            a_done = pet_data['daily_add_count'] >= 1
            st.markdown(f"{'✅' if p_done else '⬜'} 播放一首歌（+10）")
            st.markdown(f"{'✅' if a_done else '⬜'} 新增一首歌（+20）")

# === 底部播放器 (V12：修復 AI 推薦來源顯示 + 播放不中斷) ===
if st.session_state.current_playing:
    video_id = st.session_state.current_playing
    context = st.session_state.get('play_context', 'search')
    
    source_name = "未知來源"
    playlist_ids = []
    
    def get_playlist_from_list(target_list, name_prefix):
        for idx, s in enumerate(target_list):
            if s['id'] == video_id:
                remaining = target_list[idx+1:]
                previous = target_list[:idx]
                combined = remaining + previous + [s] 
                p_ids = [u['id'] for u in combined[:50]]
                return name_prefix, p_ids
        return None, None

    # A. 歌單
    if context == 'playlist':
        pl_name = st.session_state.current_playlist
        pl_songs = st.session_state.playlists.get(pl_name, [])
        s_name, p_ids = get_playlist_from_list(pl_songs, pl_name)
        if s_name:
            source_name, playlist_ids = s_name, p_ids
    
    # B. 搜尋
    if not playlist_ids and context == 'search':
        s_name, p_ids = get_playlist_from_list(st.session_state.search_results, "搜尋結果")
        if s_name:
            source_name, playlist_ids = s_name, p_ids
            
    # C. AI (修正重點：掃描歷史對話找出歌曲)
    if not playlist_ids:
        found_in_ai = False
        for msg in st.session_state.chat_history:
            if 'songs' in msg:
                s_name, p_ids = get_playlist_from_list(msg['songs'], "推薦歌曲")
                if s_name:
                    source_name, playlist_ids = s_name, p_ids
                    found_in_ai = True
                    break
        
    # D. Fallback (掃描所有可能)
    if not playlist_ids:
        pl_name = st.session_state.current_playlist
        pl_songs = st.session_state.playlists.get(pl_name, [])
        s_name, p_ids = get_playlist_from_list(pl_songs, pl_name)
        if s_name:
            source_name, playlist_ids = s_name, p_ids
        else:
            s_name, p_ids = get_playlist_from_list(st.session_state.search_results, "搜尋結果")
            if s_name:
                source_name, playlist_ids = s_name, p_ids

    # 參數生成
    if playlist_ids:
        playlist_str = ",".join(playlist_ids)
        playlist_param = f"&playlist={playlist_str}"
    else:
        playlist_param = f"&playlist={video_id}"

    loop_param = "&loop=1"
    safe_source = source_name.replace("'", "\\'")

    js_code = f"""
    <script>
        (function() {{
            var parentDoc = window.parent.document;
            var containerId = 'persistent-player-container';
            var existingContainer = parentDoc.getElementById(containerId);
            
            var videoId = '{video_id}';
            var sourceName = '{safe_source}';
            var currentPlaylistParam = '{playlist_param}';
            
            var embedUrl = "https://www.youtube.com/embed/" + videoId + 
                           "?autoplay=1&controls=1&showinfo=0&modestbranding=1&enablejsapi=1&playsinline=1" + 
                           currentPlaylistParam + "{loop_param}" + 
                           "&origin=" + window.location.origin;
            
            var playerHtml = `
                <div style="
                    position: fixed;
                    bottom: 25px;
                    right: 25px;
                    width: 320px;
                    background-color: #FFFFFF;
                    border-radius: 20px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.15);
                    z-index: 999999;
                    display: flex;
                    flex-direction: column;
                    padding: 15px;
                    border: 1px solid #E1BEE7;
                    transition: all 0.3s ease;
                    font-family: sans-serif;
                " id="inner-player-box">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding: 0 5px;">
                        <div style="font-size: 0.95rem; font-weight: bold; color: #4A148C; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px;">
                            📂 ` + sourceName + `
                        </div>
                        <div style="font-size: 0.8rem; color: #9C27B0; font-weight: bold;">播放中</div>
                    </div>
                    <div style="width: 100%; aspect-ratio: 16/9; border-radius: 12px; overflow: hidden; background: #000;">
                        <iframe 
                            width="100%" 
                            height="100%" 
                            src="` + embedUrl + `" 
                            frameborder="0" 
                            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                            allowfullscreen>
                        </iframe>
                    </div>
                    <button onclick="document.getElementById('` + containerId + `').remove()" style="
                        position: absolute;
                        top: -10px;
                        left: -10px;
                        background: #F3E5F5;
                        border: 1px solid #E1BEE7;
                        border-radius: 50%;
                        width: 28px;
                        height: 28px;
                        cursor: pointer;
                        color: #4A148C;
                        font-weight: bold;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 16px;
                        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    ">×</button>
                </div>
            `;

            if (existingContainer) {{
                var currentVid = existingContainer.getAttribute('data-video-id');
                var oldPlaylist = existingContainer.getAttribute('data-playlist-param');
                
                if (currentVid !== videoId || oldPlaylist !== currentPlaylistParam) {{
                    existingContainer.innerHTML = playerHtml;
                    existingContainer.setAttribute('data-video-id', videoId);
                    existingContainer.setAttribute('data-playlist-param', currentPlaylistParam);
                }}
            }} else {{
                var newDiv = parentDoc.createElement('div');
                newDiv.id = containerId;
                newDiv.setAttribute('data-video-id', videoId);
                newDiv.setAttribute('data-playlist-param', currentPlaylistParam);
                newDiv.innerHTML = playerHtml;
                parentDoc.body.appendChild(newDiv);
            }}
        }})();
    </script>
    """
    components.html(js_code, height=0)

else:
    js_clear = """
    <script>
        var container = window.parent.document.getElementById('persistent-player-container');
        if (container) { container.remove(); }
    </script>
    """
    components.html(js_clear, height=0)