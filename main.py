import telebot
import sqlite3
import time
import threading
import os
import asyncio
import json
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- CONFIGURATION ---
TOKEN = "8519363781:AAG5xc-xh6FS-KWn4-iJ3t_hIErBdibjcRA"
ADMIN_ID = 1908749624

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Global settings
settings = {
    'custom_footer_enabled': False,
    'custom_footer_text': '',
    'forced_join_enabled': False,
    'forced_channels': []
}

# Store message IDs for auto-deletion
user_messages = {}
upload_messages = {}

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
        uploader_id INTEGER,
        source_chat_id INTEGER DEFAULT NULL
    )''')
    # Settings table
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    # User messages for auto-delete
    c.execute('''CREATE TABLE IF NOT EXISTS user_messages (
        user_id INTEGER,
        message_id INTEGER,
        chat_id INTEGER,
        timestamp INTEGER
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
    markup.row("🔍 Search Files", "🏠 Start")
    if user_id == ADMIN_ID:
        markup.row("👑 Admin Panel")
    return markup

def admin_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("👥 Users List", "⚙️ Settings")
    markup.row("📝 Custom Footer", "🔒 Forced Join")
    markup.row("💾 Backup", "📥 Restore")
    markup.row("🔙 Back")
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
    
    # Check forced join
    if not check_forced_join(message.from_user.id):
        return
    
    welcome_text = f"🎉 **Welcome {message.from_user.first_name}!**\n\n" \
                  f"🤖 **File Store Search Bot**\n" \
                  f"━━━━━━━━━━━━━━━━━━━━━\n" \
                  f"📁 Search thousands of files instantly\n" \
                  f"📤 Upload files easily\n" \
                  f"⚡ Lightning fast results\n" \
                  f"🔒 Secure & reliable\n\n" \
                  f"💡 **How to use:**\n" \
                  f"• Type any filename to search\n" \
                  f"• Send files to upload automatically\n" \
                  f"• Use menu buttons for quick access\n\n" \
                  f"🚀 **Ready to explore?**"
    
    msg = bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=main_menu(message.from_user.id))
    track_user_message(message.from_user.id, msg.message_id, message.chat.id)

@bot.message_handler(func=lambda message: message.text == "🏠 Start")
def start_command(message):
    send_welcome(message)

@bot.message_handler(func=lambda message: message.text == "🔙 Back")
def go_back(message):
    msg = bot.send_message(message.chat.id, "Main Menu:", reply_markup=main_menu(message.from_user.id))
    track_user_message(message.from_user.id, msg.message_id, message.chat.id)

# Remove upload prompt - files auto-upload now
@bot.message_handler(func=lambda message: message.text == "🔍 Search Files")
def search_prompt(message):
    if not check_forced_join(message.from_user.id):
        return
    msg = bot.send_message(message.chat.id, "🔍 **Search Files**\n\nType the filename you want to search:", parse_mode="Markdown", reply_markup=back_btn())
    track_user_message(message.from_user.id, msg.message_id, message.chat.id)

@bot.message_handler(content_types=['document', 'video', 'audio'])
def handle_docs(message):
    if is_banned(message.from_user.id):
        bot.reply_to(message, "🚫 You are banned.")
        return
    if not check_forced_join(message.from_user.id):
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
    c.execute("INSERT INTO files (file_id, file_name, file_type, uploader_id, source_chat_id) VALUES (?, ?, ?, ?, ?)", 
              (fid, fname, ftype, message.from_user.id, message.chat.id))
    c.execute("UPDATE users SET upload_count = upload_count + 1 WHERE user_id=?", (message.from_user.id,))
    conn.commit()
    conn.close()
    
    success_msg = bot.reply_to(message, f"✅ File '{fname}' Saved! Only Admin can delete it.", reply_markup=main_menu(message.from_user.id))
    
    # Auto-delete success message after 30 seconds
    threading.Timer(30.0, lambda: delete_message_safe(message.chat.id, success_msg.message_id)).start()

# --- SEARCH LOGIC ---
user_searches = {}

# --- AUTO UPLOAD LOGIC ---

@bot.message_handler(func=lambda message: message.text and not message.text.startswith('/') and message.text not in ["👑 Admin Panel", "🔙 Back", "🔍 Search Files", "🏠 Start", "👥 Users List", "⚙️ Settings", "📝 Custom Footer", "🔒 Forced Join", "💾 Backup", "📥 Restore"])
def handle_search_text(message):
    if is_banned(message.from_user.id): return
    if not check_forced_join(message.from_user.id): return
    
    query = message.text
    user_searches[message.chat.id] = query
    
    # Search in database and cross-groups
    results = search_files_cross_platform(query)
    send_search_results(message.chat.id, query, results, 0)
    
    track_user_message(message.from_user.id, message.message_id, message.chat.id)

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
                caption = get_file_caption(fname)
                if ftype == 'doc': 
                    sent_msg = bot.send_document(call.message.chat.id, fid, caption=caption)
                elif ftype == 'video': 
                    sent_msg = bot.send_video(call.message.chat.id, fid, caption=caption)
                elif ftype == 'audio': 
                    sent_msg = bot.send_audio(call.message.chat.id, fid, caption=caption)
                
                # Show delete button only to admin after file is sent
                if call.from_user.id == ADMIN_ID:
                    del_markup = InlineKeyboardMarkup()
                    del_markup.add(InlineKeyboardButton(f"🗑️ Delete {fname[:15]}...", callback_data=f"del_sent|{file_db_id}"))
                    bot.send_message(call.message.chat.id, "Admin Options:", reply_markup=del_markup)
                
                # Auto-delete file after 5 minutes
                threading.Timer(300.0, lambda: delete_message_safe(call.message.chat.id, sent_msg.message_id)).start()
            except Exception:
                bot.answer_callback_query(call.id, "Error sending file.")
        else:
            bot.answer_callback_query(call.id, "File removed.")
            
    elif action == "pg":
        page = int(data[1])
        query = user_searches.get(call.message.chat.id, "")
        if query:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            results = search_files_cross_platform(query)
            send_search_results(call.message.chat.id, query, results, page)

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
        
    elif action == "del_sent":
        fid_db = int(data[1])
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM files WHERE id=?", (fid_db,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "File Deleted from Database.")
        bot.delete_message(call.message.chat.id, call.message.message_id)

# --- ADMIN PANEL ---
@bot.message_handler(func=lambda message: message.text == "👑 Admin Panel")
def admin_panel(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "Admin Panel:", reply_markup=admin_menu())

@bot.message_handler(func=lambda message: message.text == "👥 Users List" and message.from_user.id == ADMIN_ID)
def admin_users(message):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1")
    banned_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM files")
    total_files = c.fetchone()[0]
    
    stats_text = f"📊 **Bot Statistics**\n\n" \
                f"👥 Total Users: **{total_users}**\n" \
                f"🚫 Banned Users: **{banned_users}**\n" \
                f"✅ Active Users: **{total_users - banned_users}**\n" \
                f"📁 Total Files: **{total_files}**\n\n" \
                f"📋 **Recent Users:**"
    
    bot.send_message(message.chat.id, stats_text, parse_mode="Markdown")
    
    c.execute("SELECT user_id, first_name, upload_count, is_banned, username FROM users ORDER BY user_id DESC LIMIT 10")
    users = c.fetchall()
    conn.close()
    
    if not users:
        bot.send_message(message.chat.id, "No users found in database.")
        return
    
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

# --- ADVANCED FEATURES ---

# Group/Channel message handler for cross-platform file collection
@bot.message_handler(content_types=['document', 'video', 'audio'], func=lambda message: message.chat.type in ['group', 'supergroup', 'channel'])
def handle_group_files(message):
    try:
        # Check if bot is admin in the group/channel
        bot_member = bot.get_chat_member(message.chat.id, bot.get_me().id)
        if bot_member.status not in ['administrator', 'creator']:
            return
        
        # Extract file info
        if message.document:
            fid = message.document.file_id
            fname = message.document.file_name or f"Document_{message.message_id}"
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
        
        # Store file in database
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO files (file_id, file_name, file_type, uploader_id, source_chat_id) VALUES (?, ?, ?, ?, ?)", 
                  (fid, fname, ftype, message.from_user.id if message.from_user else 0, message.chat.id))
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"Error handling group file: {e}")

def check_forced_join(user_id):
    if not settings['forced_join_enabled'] or not settings['forced_channels']:
        return True
    
    for channel in settings['forced_channels']:
        try:
            member = bot.get_chat_member(channel, user_id)
            if member.status in ['left', 'kicked']:
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("Join Channel", url=f"https://t.me/{channel.replace('@', '')}"))
                bot.send_message(user_id, f"❌ You must join {channel} to use this bot!", reply_markup=markup)
                return False
        except:
            continue
    return True

def get_file_caption(filename):
    if settings['custom_footer_enabled'] and settings['custom_footer_text']:
        return f"{filename}\n\n{settings['custom_footer_text']}"
    return filename

def search_files_cross_platform(query):
    # Search in database
    conn = get_db_connection()
    c = conn.cursor()
    words = query.split()
    sql = "SELECT id, file_name, file_id, file_type, source_chat_id FROM files WHERE 1=1"
    params = []
    for w in words:
        sql += " AND file_name LIKE ?"
        params.append(f'%{w}%')
    c.execute(sql, params)
    results = c.fetchall()
    conn.close()
    return results

def send_search_results(chat_id, query, results, page):
    if not results and page == 0:
        msg = bot.send_message(chat_id, "❌ No files found.", reply_markup=main_menu(chat_id))
        track_user_message(chat_id, msg.message_id, chat_id)
        return
    
    items_per_page = 10
    start = page * items_per_page
    end = start + items_per_page
    page_items = results[start:end]
    has_next = len(results) > end
    has_prev = page > 0
    
    markup = InlineKeyboardMarkup()
    for res in page_items:
        btn_text = f"📂 {res[1]}"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"snd|{res[0]}"))
    
    # Always show navigation if there are multiple pages
    if has_prev or has_next:
        nav_btns = []
        if has_prev:
            nav_btns.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"pg|{page-1}"))
        if has_next:
            nav_btns.append(InlineKeyboardButton("Next ➡️", callback_data=f"pg|{page+1}"))
        markup.row(*nav_btns)
    
    msg = bot.send_message(chat_id, f"🔎 Results for '{query}' (Page {page+1} of {(len(results)-1)//10 + 1}):", reply_markup=markup)
    track_user_message(chat_id, msg.message_id, chat_id)

def track_user_message(user_id, message_id, chat_id):
    if user_id == ADMIN_ID:
        return
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO user_messages (user_id, message_id, chat_id, timestamp) VALUES (?, ?, ?, ?)",
              (user_id, message_id, chat_id, int(time.time())))
    conn.commit()
    conn.close()

def delete_message_safe(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

def cleanup_old_messages():
    while True:
        try:
            conn = get_db_connection()
            c = conn.cursor()
            # Delete messages older than 24 hours
            cutoff = int(time.time()) - 86400
            c.execute("SELECT user_id, message_id, chat_id FROM user_messages WHERE timestamp < ?", (cutoff,))
            old_messages = c.fetchall()
            
            for user_id, msg_id, chat_id in old_messages:
                delete_message_safe(chat_id, msg_id)
            
            c.execute("DELETE FROM user_messages WHERE timestamp < ?", (cutoff,))
            conn.commit()
            conn.close()
        except:
            pass
        time.sleep(3600)  # Check every hour

# --- BACKUP & RESTORE ---
def export_data():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Export all tables
    data = {
        'users': [],
        'files': [],
        'settings': settings,
        'timestamp': int(time.time())
    }
    
    # Export users
    c.execute("SELECT * FROM users")
    for row in c.fetchall():
        data['users'].append({
            'user_id': row[0],
            'first_name': row[1],
            'username': row[2],
            'is_banned': row[3],
            'upload_count': row[4]
        })
    
    # Export files
    c.execute("SELECT * FROM files")
    for row in c.fetchall():
        data['files'].append({
            'id': row[0],
            'file_id': row[1],
            'file_name': row[2],
            'file_type': row[3],
            'uploader_id': row[4],
            'source_chat_id': row[5] if len(row) > 5 else None
        })
    
    conn.close()
    return json.dumps(data, indent=2)

def import_data(json_data):
    try:
        data = json.loads(json_data)
        conn = get_db_connection()
        c = conn.cursor()
        
        # Clear existing data
        c.execute("DELETE FROM users")
        c.execute("DELETE FROM files")
        c.execute("DELETE FROM user_messages")
        
        # Import users
        for user in data.get('users', []):
            c.execute("INSERT INTO users (user_id, first_name, username, is_banned, upload_count) VALUES (?, ?, ?, ?, ?)",
                     (user['user_id'], user['first_name'], user['username'], user['is_banned'], user['upload_count']))
        
        # Import files
        for file in data.get('files', []):
            c.execute("INSERT INTO files (file_id, file_name, file_type, uploader_id, source_chat_id) VALUES (?, ?, ?, ?, ?)",
                     (file['file_id'], file['file_name'], file['file_type'], file['uploader_id'], file.get('source_chat_id')))
        
        # Import settings
        global settings
        settings.update(data.get('settings', {}))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Import error: {e}")
        return False

@bot.message_handler(func=lambda message: message.text == "💾 Backup" and message.from_user.id == ADMIN_ID)
def backup_data(message):
    try:
        backup_json = export_data()
        
        # Save to file
        filename = f"bot_backup_{int(time.time())}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(backup_json)
        
        # Send file to admin
        with open(filename, 'rb') as f:
            bot.send_document(message.chat.id, f, caption="🗄️ Bot Data Backup\n\nSave this file safely!")
        
        # Delete local file
        os.remove(filename)
        
        bot.send_message(message.chat.id, "✅ Backup created successfully!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Backup failed: {str(e)}")

@bot.message_handler(func=lambda message: message.text == "📥 Restore" and message.from_user.id == ADMIN_ID)
def restore_prompt(message):
    bot.send_message(message.chat.id, "📤 Send me the backup JSON file to restore data.\n\n⚠️ Warning: This will replace all current data!")
    bot.register_next_step_handler(message, process_restore)

def process_restore(message):
    if not message.document or not message.document.file_name.endswith('.json'):
        bot.send_message(message.chat.id, "❌ Please send a valid JSON backup file.")
        return
    
    try:
        # Download file
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Process restore
        json_data = downloaded_file.decode('utf-8')
        if import_data(json_data):
            bot.send_message(message.chat.id, "✅ Data restored successfully!\n\nBot restarting...")
            # Restart bot (optional)
            os._exit(0)
        else:
            bot.send_message(message.chat.id, "❌ Restore failed. Check file format.")
    
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Restore error: {str(e)}")
@bot.message_handler(func=lambda message: message.text == "📝 Custom Footer" and message.from_user.id == ADMIN_ID)
def custom_footer_menu(message):
    markup = InlineKeyboardMarkup()
    status = "✅ Enabled" if settings['custom_footer_enabled'] else "❌ Disabled"
    markup.add(InlineKeyboardButton(f"Toggle Footer {status}", callback_data="toggle_footer"))
    if settings['custom_footer_enabled']:
        markup.add(InlineKeyboardButton("📝 Edit Footer Text", callback_data="edit_footer"))
    
    current_text = settings['custom_footer_text'] if settings['custom_footer_text'] else "No footer set"
    bot.send_message(message.chat.id, f"Custom Footer Settings:\n\nStatus: {status}\nCurrent Footer: {current_text}", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔒 Forced Join" and message.from_user.id == ADMIN_ID)
def forced_join_menu(message):
    markup = InlineKeyboardMarkup()
    status = "✅ Enabled" if settings['forced_join_enabled'] else "❌ Disabled"
    markup.add(InlineKeyboardButton(f"Toggle Forced Join {status}", callback_data="toggle_forced"))
    if settings['forced_join_enabled']:
        markup.add(InlineKeyboardButton("➕ Add Channel", callback_data="add_channel"))
        markup.add(InlineKeyboardButton("➖ Remove Channel", callback_data="remove_channel"))
    
    channels_text = "\n".join(settings['forced_channels']) if settings['forced_channels'] else "No channels set"
    bot.send_message(message.chat.id, f"Forced Join Settings:\n\nStatus: {status}\nChannels: {channels_text}", reply_markup=markup)

# --- CALLBACK UPDATES ---
@bot.callback_query_handler(func=lambda call: call.data in ["toggle_footer", "edit_footer", "toggle_forced", "add_channel", "remove_channel"])
def settings_callback(call):
    if call.from_user.id != ADMIN_ID:
        return
    
    if call.data == "toggle_footer":
        settings['custom_footer_enabled'] = not settings['custom_footer_enabled']
        bot.answer_callback_query(call.id, f"Footer {'Enabled' if settings['custom_footer_enabled'] else 'Disabled'}")
        custom_footer_menu(call.message)
    
    elif call.data == "edit_footer":
        bot.answer_callback_query(call.id, "Send the footer text:")
        bot.send_message(call.message.chat.id, "Send me the custom footer text:")
        bot.register_next_step_handler(call.message, process_footer_text)
    
    elif call.data == "toggle_forced":
        settings['forced_join_enabled'] = not settings['forced_join_enabled']
        bot.answer_callback_query(call.id, f"Forced Join {'Enabled' if settings['forced_join_enabled'] else 'Disabled'}")
        forced_join_menu(call.message)
    
    elif call.data == "add_channel":
        bot.answer_callback_query(call.id, "Send channel username:")
        bot.send_message(call.message.chat.id, "Send channel username (e.g., @channelname):")
        bot.register_next_step_handler(call.message, process_add_channel)
    
    elif call.data == "remove_channel":
        if settings['forced_channels']:
            markup = InlineKeyboardMarkup()
            for ch in settings['forced_channels']:
                markup.add(InlineKeyboardButton(f"Remove {ch}", callback_data=f"rm_ch|{ch}"))
            bot.send_message(call.message.chat.id, "Select channel to remove:", reply_markup=markup)
        else:
            bot.answer_callback_query(call.id, "No channels to remove")

def process_footer_text(message):
    settings['custom_footer_text'] = message.text
    bot.send_message(message.chat.id, "✅ Footer text updated!")

def process_add_channel(message):
    channel = message.text.strip()
    if not channel.startswith('@'):
        channel = '@' + channel
    
    if channel not in settings['forced_channels']:
        settings['forced_channels'].append(channel)
        bot.send_message(message.chat.id, f"✅ Channel {channel} added!")
    else:
        bot.send_message(message.chat.id, "Channel already exists!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("rm_ch|"))
def remove_channel_callback(call):
    if call.from_user.id != ADMIN_ID:
        return
    
    channel = call.data.split('|')[1]
    if channel in settings['forced_channels']:
        settings['forced_channels'].remove(channel)
        bot.answer_callback_query(call.id, f"Channel {channel} removed!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "Channel not found!")

# --- RUN BOT ---
if __name__ == "__main__":
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_old_messages, daemon=True)
    cleanup_thread.start()
    
    # Start Keep-Alive Server in separate thread
    t = threading.Thread(target=run_web_server)
    t.start()
    
    print("Bot Started...")
    bot.infinity_polling()
