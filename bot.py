import os
import sqlite3
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
)
from telegram.error import RetryAfter

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ================= DATABASE =================
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
    reward_msg TEXT,
    required_joins INTEGER DEFAULT 3
)
""")
conn.commit()

# ================= HELPERS =================
def get_group(group_id):
    cur.execute("SELECT reward_msg, required_joins FROM groups WHERE group_id=?", (group_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO groups (group_id) VALUES (?)", (group_id,))
        conn.commit()
        return None, 3
    return row[0], row[1]

def set_required_joins(group_id, n):
    cur.execute("""
    INSERT INTO groups (group_id, required_joins)
    VALUES (?, ?)
    ON CONFLICT(group_id)
    DO UPDATE SET required_joins=excluded.required_joins
    """, (group_id, n))
    conn.commit()

def set_reward(group_id, text):
    cur.execute("""
    INSERT INTO groups (group_id, reward_msg)
    VALUES (?, ?)
    ON CONFLICT(group_id)
    DO UPDATE SET reward_msg=excluded.reward_msg
    """, (group_id, text))
    conn.commit()

def get_user(group_id, user_id):
    cur.execute("""
    SELECT invite_link, join_count, completed, reward_claimed
    FROM referrals WHERE group_id=? AND user_id=?
    """, (group_id, user_id))
    return cur.fetchone()

def save_user(group_id, user_id, link):
    cur.execute("""
    INSERT OR REPLACE INTO referrals
    (group_id, user_id, invite_link, join_count, completed, reward_claimed)
    VALUES (?, ?, ?, 0, 0, 0)
    """, (group_id, user_id, link))
    conn.commit()

def inc_join(group_id, user_id):
    cur.execute("""
    UPDATE referrals SET join_count = join_count + 1
    WHERE group_id=? AND user_id=?
    """, (group_id, user_id))
    conn.commit()

def mark_completed(group_id, user_id):
    cur.execute("""
    UPDATE referrals SET completed=1
    WHERE group_id=? AND user_id=?
    """, (group_id, user_id))
    conn.commit()

def mark_claimed(group_id, user_id):
    cur.execute("""
    UPDATE referrals SET reward_claimed=1
    WHERE group_id=? AND user_id=?
    """, (group_id, user_id))
    conn.commit()

# ================= PANEL =================
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Referral", callback_data="start_ref")],
        [InlineKeyboardButton("📊 My Progress", callback_data="progress")]
    ])
    await update.message.reply_text(
        "🔐 UNLOCK EXCLUSIVE ACCESS\n\nInvite friends using your personal link 👇",
        reply_markup=kb
    )

# ================= START REF =================
async def start_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    group_id = q.message.chat.id

    data = get_user(group_id, user.id)
    if not data or not data[0]:
        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=group_id,
                name=f"ref_{user.id}"
            )
            save_user(group_id, user.id, invite.invite_link)
            link = invite.invite_link
            print("INVITE CREATED:", link)
        except RetryAfter:
            await q.answer("⚠️ Server busy, 5 min baad try karo", show_alert=True)
            return
    else:
        link = data[0]

    share = "https://t.me/share/url?" + urllib.parse.urlencode({
        "url": link,
        "text": "Join this group for exclusive channel 🔥"
    })

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share Referral Link", url=share)],
        [InlineKeyboardButton("📊 My Progress", callback_data="progress")]
    ])

    await q.message.edit_reply_markup(reply_markup=kb)
    await q.answer()

# ================= TRACK JOIN (FIXED) =================
async def track_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member

    # ONLY count when user becomes member
    if cm.new_chat_member.status != "member":
        return

    invite = cm.invite_link
    if not invite:
        print("JOIN WITHOUT INVITE LINK")
        return

    group_id = cm.chat.id

    cur.execute("""
    SELECT user_id, join_count, completed
    FROM referrals
    WHERE group_id=? AND invite_link=?
    """, (group_id, invite.invite_link))
    row = cur.fetchone()

    if not row:
        print("INVITE LINK NOT FOUND IN DB")
        return

    referrer_id, count, completed = row
    if completed:
        return

    inc_join(group_id, referrer_id)
    print(f"JOIN COUNT UPDATED -> {referrer_id}: {count+1}")

    _, required = get_group(group_id)
    if count + 1 >= required:
        mark_completed(group_id, referrer_id)
        print("REFERRAL COMPLETED:", referrer_id)

# ================= PROGRESS =================
async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    group_id = q.message.chat.id

    data = get_user(group_id, user.id)
    if not data:
        await q.answer("❌ Referral start nahi hua", show_alert=True)
        return

    _, count, completed, claimed = data
    _, required = get_group(group_id)

    if completed and not claimed:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Claim Reward", callback_data="claim")]
        ])
        await q.message.reply_text("🎉 Referral complete!", reply_markup=kb)
        await q.answer("🎁 Reward unlocked", show_alert=True)
        return

    await q.answer(f"{count}/{required} joined", show_alert=True)

# ================= CLAIM =================
async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    group_id = q.message.chat.id

    data = get_user(group_id, user.id)
    if not data or data[3] or not data[2]:
        await q.answer("❌ Not eligible", show_alert=True)
        return

    mark_claimed(group_id, user.id)
    reward, _ = get_group(group_id)
    await q.message.reply_text(reward or "🎁 Reward unlocked! Admin will contact you.")
    await q.answer("🎉 Claimed", show_alert=True)

# ================= ADMIN =================
async def setreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    set_reward(update.effective_chat.id, " ".join(context.args))
    await update.message.reply_text("✅ Reward updated")

async def setjoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Usage: /setjoin 3")
        return
    set_required_joins(update.effective_chat.id, int(context.args[0]))
    await update.message.reply_text("✅ Join count updated")

# ================= MAIN =================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("panel", panel))
app.add_handler(CommandHandler("setreward", setreward))
app.add_handler(CommandHandler("setjoin", setjoin))
app.add_handler(CallbackQueryHandler(start_ref, pattern="start_ref"))
app.add_handler(CallbackQueryHandler(progress, pattern="progress"))
app.add_handler(CallbackQueryHandler(claim, pattern="claim"))
app.add_handler(ChatMemberHandler(track_join, ChatMemberHandler.CHAT_MEMBER))

app.run_polling(allowed_updates=["message", "callback_query", "chat_member"])
