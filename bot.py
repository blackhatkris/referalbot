import os
import sqlite3
import time
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

# Default values (admin can change reward message)
WAIT_HOURS = 12
WAIT_SECONDS = WAIT_HOURS * 3600

# ⚠️ IMPORTANT:
# Public group → https://t.me/your_group_username
# Private group → permanent invite link paste karo
GROUP_LINK = os.getenv("GROUP_LINK")  # REQUIRED

# ================== DATABASE ==================
conn = sqlite3.connect("database.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    group_id INTEGER,
    user_id INTEGER,
    start_time INTEGER,
    completed INTEGER DEFAULT 0,
    PRIMARY KEY (group_id, user_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS groups (
    group_id INTEGER PRIMARY KEY,
    reward_msg TEXT
)
""")

conn.commit()

# ================== HELPERS ==================
def now():
    return int(time.time())

def set_reward_msg(group_id, text):
    cur.execute("""
    INSERT INTO groups (group_id, reward_msg)
    VALUES (?, ?)
    ON CONFLICT(group_id)
    DO UPDATE SET reward_msg=excluded.reward_msg
    """, (group_id, text))
    conn.commit()

def get_reward_msg(group_id):
    cur.execute("SELECT reward_msg FROM groups WHERE group_id=?", (group_id,))
    row = cur.fetchone()
    return row[0] if row else (
        "🎉 Congratulations!\n\n"
        "You’ve completed the requirement.\n"
        "Admin will add you to the private channel soon."
    )

def ensure_started(group_id, user_id):
    cur.execute("""
    SELECT start_time FROM users
    WHERE group_id=? AND user_id=?
    """, (group_id, user_id))
    row = cur.fetchone()

    if not row:
        cur.execute("""
        INSERT INTO users (group_id, user_id, start_time, completed)
        VALUES (?, ?, ?, 0)
        """, (group_id, user_id, now()))
        conn.commit()
        return now()
    return row[0]

# ================== PANEL ==================
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id

    share_url = (
        "https://t.me/share/url?"
        + urllib.parse.urlencode({
            "url": GROUP_LINK,
            "text": "Join this group for free premium content 🔥"
        })
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Referral", url=share_url)],
        [InlineKeyboardButton("📊 My Status", callback_data="status")]
    ])

    await update.message.reply_text(
        "🎁 FREE PREMIUM ACCESS\n\n"
        "Invite 3 friends to this group\n"
        "⏳ Wait 12 hours\n\n"
        "⚠️ Group leave karoge to reward cancel ho jayega",
        reply_markup=keyboard
    )

# ================== STATUS ==================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    group_id = query.message.chat.id

    start_time = ensure_started(group_id, user.id)

    cur.execute("""
    SELECT completed FROM users
    WHERE group_id=? AND user_id=?
    """, (group_id, user.id))
    completed = cur.fetchone()[0]

    elapsed = now() - start_time
    remaining = max(0, WAIT_SECONDS - elapsed)

    if completed:
        await query.answer("🎉 Reward already unlocked", show_alert=True)
        return

    if remaining <= 0:
        # complete reward
        cur.execute("""
        UPDATE users SET completed=1
        WHERE group_id=? AND user_id=?
        """, (group_id, user.id))
        conn.commit()

        reward_msg = get_reward_msg(group_id)
        await context.bot.send_message(chat_id=user.id, text=reward_msg)
        await query.answer("🎉 Completed! Check DM", show_alert=True)
        return

    hrs = remaining // 3600
    mins = (remaining % 3600) // 60

    await query.answer(
        f"{user.first_name} ✅\n"
        f"3/3 Refer (Required)\n"
        f"⏳ Time left: {hrs}h {mins}m",
        show_alert=True
    )

# ================== LEAVE = CANCEL ==================
async def on_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.left_chat_member
    group_id = update.message.chat.id

    cur.execute("""
    DELETE FROM users
    WHERE group_id=? AND user_id=?
    """, (group_id, user.id))
    conn.commit()

# ================== ADMIN COMMAND ==================
async def setreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    group_id = update.effective_chat.id
    text = " ".join(context.args)
    set_reward_msg(group_id, text)
    await update.message.reply_text("✅ Reward message updated")

# ================== MAIN ==================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("panel", panel))
app.add_handler(CommandHandler("setreward", setreward))
app.add_handler(CallbackQueryHandler(status, pattern="status"))
app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_leave))

app.run_polling()
