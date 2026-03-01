import os
import sqlite3
import urllib.parse
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
)
from telegram.error import RetryAfter

BOT_TOKEN = os.getenv("BOT_TOKEN")
REQUIRED_JOINS = 3

# ================= DB =================
conn = sqlite3.connect("database.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS referrals (
    group_id INTEGER,
    user_id INTEGER,
    invite_link TEXT,
    join_count INTEGER DEFAULT 0,
    completed INTEGER DEFAULT 0,
    reward_claimed INTEGER DEFAULT 0,
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

# ================= HELPERS =================
def get_user(group_id, user_id):
    cur.execute("""
    SELECT invite_link, join_count, completed, reward_claimed
    FROM referrals WHERE group_id=? AND user_id=?
    """, (group_id, user_id))
    return cur.fetchone()

def save_user(group_id, user_id, invite_link):
    cur.execute("""
    INSERT OR REPLACE INTO referrals
    (group_id, user_id, invite_link, join_count, completed, reward_claimed)
    VALUES (?, ?, ?, 0, 0, 0)
    """, (group_id, user_id, invite_link))
    conn.commit()

def inc_join(group_id, user_id):
    cur.execute("""
    UPDATE referrals SET join_count=join_count+1
    WHERE group_id=? AND user_id=?
    """, (group_id, user_id))
    conn.commit()

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
    return row[0] if row else "🎁 Reward unlocked! Admin will contact you."

# ================= PANEL =================
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Referral", callback_data="start_ref")],
        [InlineKeyboardButton("📊 My Progress", callback_data="progress")]
    ])

    await update.message.reply_text(
        "🔐 UNLOCK EXCLUSIVE ACCESS\n\n"
        "Invite 3 friends using your personal link.\n"
        "👇 Start below 👇",
        reply_markup=keyboard
    )

# ================= START REF =================
async def start_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    group_id = query.message.chat.id

    data = get_user(group_id, user.id)

    if not data or not data[0]:
        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=group_id,
                name=f"ref_{user.id}"
            )
            invite_link = invite.invite_link
            save_user(group_id, user.id, invite_link)
        except RetryAfter:
            await query.answer(
                "⚠️ Server busy hai\n5 minute baad try karo",
                show_alert=True
            )
            return
    else:
        invite_link = data[0]

    share_url = (
        "https://t.me/share/url?"
        + urllib.parse.urlencode({
            "url": invite_link,
            "text": "Join this group for exclusive channel 🔥"
        })
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share Referral Link", url=share_url)],
        [InlineKeyboardButton("📊 My Progress", callback_data="progress")]
    ])

    await query.message.edit_reply_markup(reply_markup=keyboard)
    await query.answer("✅ Share panel open karo", show_alert=False)

# ================= TRACK JOINS =================
async def track_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    invite = update.chat_member.invite_link
    if not invite:
        return

    group_id = update.chat_member.chat.id

    cur.execute("""
    SELECT user_id, join_count, completed
    FROM referrals WHERE group_id=? AND invite_link=?
    """, (group_id, invite.invite_link))
    row = cur.fetchone()
    if not row:
        return

    referrer_id, count, completed = row
    if completed:
        return

    inc_join(group_id, referrer_id)
    if count + 1 >= REQUIRED_JOINS:
        cur.execute("""
        UPDATE referrals SET completed=1
        WHERE group_id=? AND user_id=?
        """, (group_id, referrer_id))
        conn.commit()

# ================= PROGRESS =================
async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    group_id = query.message.chat.id

    data = get_user(group_id, user.id)
    if not data:
        await query.answer("❌ Referral not started", show_alert=True)
        return

    _, count, completed, claimed = data

    if completed and not claimed:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Claim Reward", callback_data="claim")]
        ])
        await query.message.reply_text(
            f"🎉 {user.first_name}, referral complete!",
            reply_markup=keyboard
        )
        await query.answer("🎁 Reward unlocked!", show_alert=True)
        return

    await query.answer(
        f"{user.first_name}\n{count}/{REQUIRED_JOINS} joined",
        show_alert=True
    )

# ================= CLAIM =================
async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    group_id = query.message.chat.id

    data = get_user(group_id, user.id)
    if not data or data[3] == 1 or data[2] == 0:
        await query.answer("❌ Not eligible", show_alert=True)
        return

    cur.execute("""
    UPDATE referrals SET reward_claimed=1
    WHERE group_id=? AND user_id=?
    """, (group_id, user.id))
    conn.commit()

    await query.message.reply_text(get_reward_msg(group_id))
    await query.answer("🎉 Reward claimed!", show_alert=True)

# ================= ADMIN =================
async def setreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    set_reward_msg(update.effective_chat.id, " ".join(context.args))
    await update.message.reply_text("✅ Reward message updated")

# ================= MAIN =================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("panel", panel))
app.add_handler(CommandHandler("setreward", setreward))
app.add_handler(CallbackQueryHandler(start_ref, pattern="start_ref"))
app.add_handler(CallbackQueryHandler(progress, pattern="progress"))
app.add_handler(CallbackQueryHandler(claim, pattern="claim"))
app.add_handler(ChatMemberHandler(track_join, ChatMemberHandler.CHAT_MEMBER))

app.run_polling()
