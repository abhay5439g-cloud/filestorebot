import telebot
import sqlite3
import time
import threading
import os
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- CONFIGURATION ---
TOKEN = "8519363781:AAG5xc-xh6FS-KWn4-iJ3t_hIErBdibjcRA"
ADMIN_ID = 1908749624

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        is_banned INTEGER DEFAULT 0,
        upload_count INTEGER DEFAULT 0
    )''')
    # Files table
    c.execute('''CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT,
        file_name TEXT,
        file_type TEXT,
        uploader_id INTEGER
    )''')
    conn.commit()
    conn.close()

init_db()

# --- KEEP ALIVE SERVER FOR RENDER ---
@app.route('/')
def home():
    return "Bot is Running!"

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- HELPERS ---
def get_db_connection():
    return sqlite3.connect('bot_data.db', check_same_thread=False)

def add_user(user_id, first_name, username):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, first_name, username) VALUES (?, ?, ?)", 
              (user_id, first_name, username))
    conn.commit()
    conn.close()

def is_banned(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    if result and result[0] == 1:
        return True
    return False

# --- MENUS ---
def main_menu(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    markup.row("🔍 Search File", "UL Upload File")
    if user_id == ADMIN_ID:
        markup.row("👑 Admin Panel")
    return markup

def back_btn():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 Back")
    return markup

# --- HANDLERS ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    uname = message.from_user.username if message.from_user.username else "None"
    add_user(message.from_user.id, message.from_user.first_name, uname)
    bot.reply_to(message, f"Welcome {message.from_user.first_name}!\nType any file name to search or use the menu.", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda message: message.text == "🔙 Back")
def go_back(message):
    bot.send_message(message.chat.id, "Main Menu:", reply_markup=main_menu(message.from_user.id))

# --- UPLOAD LOGIC ---
@bot.message_handler(func=lambda message: message.text == "UL Upload File")
def upload_prompt(message):
    if is_banned(message.from_user.id):
        bot.reply_to(message, "🚫 You are banned.")
        return
    bot.send_message(message.chat.id, "Send me any file (Video, Document, Audio) to upload.", reply_markup=back_btn())

@bot.message_handler(content_types=['document', 'video', 'audio'])
def handle_docs(message):
    if is_banned(message.from_user.id):
        bot.reply_to(message, "🚫 You are banned.")
        return
    
    if message.document:
        fid = message.document.file_id
        fname = message.document.file_name
        ftype = 'doc'
    elif message.video:
        fid = message.video.file_id
        fname = message.caption if message.caption else f"Video_{message.message_id}.mp4"
        ftype = 'video'
    elif message.audio:
        fid = message.audio.file_id
        fname = message.audio.file_name if message.audio.file_name else f"Audio_{message.message_id}.mp3"
        ftype = 'audio'
    else:
        return

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO files (file_id, file_name, file_type, uploader_id) VALUES (?, ?, ?, ?)", 
              (fid, fname, ftype, message.from_user.id))
    c.execute("UPDATE users SET upload_count = upload_count + 1 WHERE user_id=?", (message.from_user.id,))
    conn.commit()
    conn.close()
    
    bot.reply_to(message, f"✅ File '{fname}' Saved! Only Admin can delete it.", reply_markup=main_menu(message.from_user.id))

# --- SEARCH LOGIC ---
user_searches = {}

@bot.message_handler(func=lambda message: message.text == "🔍 Search File")
def search_prompt(message):
    bot.send_message(message.chat.id, "Type the file name you want to search:", reply_markup=back_btn())

def get_search_results(query, page=0):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Split query for exact partial matching
    words = query.split()
    sql = "SELECT id, file_name, file_id, file_type FROM files WHERE 1=1"
    params = []
    for w in words:
        sql += " AND file_name LIKE ?"
        params.append(f'%{w}%')
        
    c.execute(sql, params)
    all_results = c.fetchall()
    conn.close()
    
    items_per_page = 10
    start = page * items_per_page
    end = start + items_per_page
    page_items = all_results[start:end]
    has_next = len(all_results) > end
    
    return page_items, has_next, len(all_results)

def send_search_page(chat_id, query, page):
    results, has_next, total = get_search_results(query, page)
    
    if not results and page == 0:
        bot.send_message(chat_id, "❌ No files found.", reply_markup=main_menu(chat_id))
        return

    markup = InlineKeyboardMarkup()
    for res in results:
        btn_text = f"📂 {res[1]}"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"snd|{res[0]}"))
        
        # Admin Delete Option
        if chat_id == ADMIN_ID:
            markup.add(InlineKeyboardButton(f"❌ Delete {res[1][:10]}...", callback_data=f"del_file|{res[0]}"))
    
    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"pg|{page-1}"))
    if has_next:
        nav_btns.append(InlineKeyboardButton("Next ➡️", callback_data=f"pg|{page+1}"))
    
    if nav_btns:
        markup.row(*nav_btns)
        
    bot.send_message(chat_id, f"🔎 Results for '{query}' (Page {page+1}):", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text and not message.text.startswith('/') and message.text not in ["👑 Admin Panel", "🔙 Back", "UL Upload File", "🔍 Search File"])
def handle_search_text(message):
    if is_banned(message.from_user.id): return
    query = message.text
    user_searches[message.chat.id] = query
    send_search_page(message.chat.id, query, 0)

# --- CALLBACKS ---
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    data = call.data.split('|')
    action = data[0]
    
    if action == "snd":
        file_db_id = data[1]
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT file_id, file_type, file_name FROM files WHERE id=?", (file_db_id,))
        res = c.fetchone()
        conn.close()
        
        if res:
            fid, ftype, fname = res
            try:
                if ftype == 'doc': bot.send_document(call.message.chat.id, fid, caption=fname)
                elif ftype == 'video': bot.send_video(call.message.chat.id, fid, caption=fname)
                elif ftype == 'audio': bot.send_audio(call.message.chat.id, fid, caption=fname)
            except Exception:
                bot.answer_callback_query(call.id, "Error sending file.")
        else:
            bot.answer_callback_query(call.id, "File removed.")
            
    elif action == "pg":
        page = int(data[1])
        query = user_searches.get(call.message.chat.id, "")
        if query:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            send_search_page(call.message.chat.id, query, page)

    elif action == "ban":
        uid = int(data[1])
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "User Banned.")
        
    elif action == "unban":
        uid = int(data[1])
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "User Unbanned.")
        
    elif action == "del_file":
        fid_db = int(data[1])
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM files WHERE id=?", (fid_db,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "File Deleted.")
        bot.delete_message(call.message.chat.id, call.message.message_id)

# --- ADMIN PANEL ---
@bot.message_handler(func=lambda message: message.text == "👑 Admin Panel")
def admin_panel(message):
    if message.from_user.id != ADMIN_ID: return
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("👥 Users List")
    markup.row("🔙 Back")
    bot.send_message(message.chat.id, "Admin Panel:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "👥 Users List" and message.from_user.id == ADMIN_ID)
def admin_users(message):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT user_id, first_name, upload_count, is_banned, username FROM users")
    users = c.fetchall()
    conn.close()
    
    if not users:
        bot.send_message(message.chat.id, "No users found in database.")
        return
        
    bot.send_message(message.chat.id, f"Total Users: {len(users)}\nGenerating list...")
    
    for u in users:
        status = "🚫 BANNED" if u[3] else "✅ Active"
        username_txt = f"@{u[4]}" if u[4] else "No Username"
        txt = f"🆔 `{u[0]}`\n👤 {u[1]} ({username_txt})\n📂 Uploads: {u[2]}\nStatus: {status}"
        
        markup = InlineKeyboardMarkup()
        if u[3]:
            markup.add(InlineKeyboardButton("✅ Unban User", callback_data=f"unban|{u[0]}"))
        else:
            markup.add(InlineKeyboardButton("🚫 Ban User", callback_data=f"ban|{u[0]}"))
            
        bot.send_message(message.chat.id, txt, parse_mode="Markdown", reply_markup=markup)

# --- RUN BOT ---
if __name__ == "__main__":
    # Start Keep-Alive Server in separate thread
    t = threading.Thread(target=run_web_server)
    t.start()
    
    print("Bot Started...")
    bot.infinity_polling()