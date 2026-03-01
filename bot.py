import os
import sqlite3
import urllib.parse
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
REFERRALS_REQUIRED = 3

# ================== DATABASE ==================
conn = sqlite3.connect("database.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS groups (
    group_id INTEGER PRIMARY KEY,
    referral_text TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    group_id INTEGER,
    user_id INTEGER,
    referral_count INTEGER DEFAULT 0,
    reward_unlocked INTEGER DEFAULT 0,
    PRIMARY KEY (group_id, user_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS referrals (
    group_id INTEGER,
    referrer_id INTEGER,
    referred_id INTEGER,
    UNIQUE(group_id, referred_id)
)
""")

conn.commit()

# ================== HELPERS ==================
def get_referral_text(group_id):
    cur.execute("SELECT referral_text FROM groups WHERE group_id=?", (group_id,))
    row = cur.fetchone()
    return row[0] if row else "Join this group for free content 🔥"

def set_referral_text(group_id, text):
    cur.execute("""
    INSERT INTO groups (group_id, referral_text)
    VALUES (?, ?)
    ON CONFLICT(group_id) DO UPDATE SET referral_text=excluded.referral_text
    """, (group_id, text))
    conn.commit()

def ensure_user(group_id, user_id):
    cur.execute("""
    INSERT OR IGNORE INTO users (group_id, user_id)
    VALUES (?, ?)
    """, (group_id, user_id))
    conn.commit()

def get_referral_count(group_id, user_id):
    cur.execute("""
    SELECT referral_count FROM users
    WHERE group_id=? AND user_id=?
    """, (group_id, user_id))
    row = cur.fetchone()
    return row[0] if row else 0

def increment_referral(group_id, user_id):
    cur.execute("""
    UPDATE users
    SET referral_count = referral_count + 1
    WHERE group_id=? AND user_id=?
    """, (group_id, user_id))
    conn.commit()

# ================== START (REF TRACK) ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].startswith("ref_"):
        try:
            _, referrer_id, group_id = context.args[0].split("_")
            context.user_data["referrer_id"] = int(referrer_id)
            context.user_data["group_id"] = int(group_id)
        except:
            pass

# ================== AUTO DELETE JOIN MSG ==================
async def on_user_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    group_id = msg.chat.id

    # delete "user joined" message
    try:
        await context.bot.delete_message(group_id, msg.message_id)
    except:
        pass

    for user in msg.new_chat_members:
        if user.is_bot:
            continue

        ensure_user(group_id, user.id)

        referrer_id = context.user_data.get("referrer_id")
        ref_group_id = context.user_data.get("group_id")

        if referrer_id and ref_group_id == group_id and referrer_id != user.id:
            try:
                cur.execute("""
                INSERT INTO referrals (group_id, referrer_id, referred_id)
                VALUES (?, ?, ?)
                """, (group_id, referrer_id, user.id))
                increment_referral(group_id, referrer_id)
                conn.commit()
            except:
                pass

# ================== PANEL MESSAGE ==================
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    user_id = update.effective_user.id

    ensure_user(group_id, user_id)

    referral_text = get_referral_text(group_id)
    bot_username = context.bot.username

    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}_{group_id}"

    share_url = "https://t.me/share/url?" + urllib.parse.urlencode({
        "url": ref_link,
        "text": referral_text
    })

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Refer 3 People", url=share_url)],
        [InlineKeyboardButton("📊 My Progress", callback_data="progress")]
    ])

    await update.message.reply_text(
        "🔐 Unlock exclusive content\nRefer 3 friends 👇",
        reply_markup=keyboard
    )

# ================== PROGRESS POPUP ==================
async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    group_id = query.message.chat.id

    count = get_referral_count(group_id, user.id)

    text = f"{user.first_name} ✅\n{count}/{REFERRALS_REQUIRED} done"

    if count >= REFERRALS_REQUIRED:
        text += "\n🎉 Completed!"

    await query.answer(text=text, show_alert=True)

# ================== ADMIN COMMAND ==================
async def setrefmsg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return

    group_id = update.effective_chat.id
    text = " ".join(context.args)

    set_referral_text(group_id, text)
    await update.message.reply_text("✅ Referral share message updated")

# ================== MAIN ==================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("panel", panel))
app.add_handler(CommandHandler("setrefmsg", setrefmsg))
app.add_handler(CallbackQueryHandler(progress, pattern="progress"))
app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_user_join))

app.run_polling()
