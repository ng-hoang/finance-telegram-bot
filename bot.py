from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import sqlite3
import re
from datetime import datetime

# ================== TOKEN ==================
import os
TOKEN = os.getenv("BOT_TOKEN")
# ===========================================


# ================== DATABASE ==================
conn = sqlite3.connect("finance.db", check_same_thread=False)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount INTEGER,
    type TEXT,
    category TEXT,
    note TEXT,
    created_at TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS balance (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    amount INTEGER
)
""")

c.execute("INSERT OR IGNORE INTO balance (id, amount) VALUES (1, 0)")
conn.commit()
# ============================================


# ================== CATEGORY RULE ==================
CATEGORY_RULES = {
    "Đồ ăn": ["ăn", "cf", "cafe", "trà sữa", "bún", "phở"],
    "Giải trí": ["phim", "game", "netflix", "spotify"],
    "Đi lại": ["grab", "xăng", "xe", "bus"],
    "Mua sắm": ["shopee", "áo", "giày", "lazada"],
    "Thu nhập": ["lương", "thưởng", "freelance", "job"]
}

def detect_category(text: str) -> str:
    text = text.lower()
    for cat, keywords in CATEGORY_RULES.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "Khác"


def parse_amount(text: str):
    match = re.search(r"([\d\.]+)\s*(k|tr)?", text.lower())
    if not match:
        return None

    num = float(match.group(1))
    unit = match.group(2)

    if unit == "k":
        return int(num * 1_000)
    if unit == "tr":
        return int(num * 1_000_000)
    return int(num)
# ================================================


# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot ghi thu chi đã sẵn sàng.\n\n"
        "Ví dụ:\n"
        "- ăn sáng 30k\n"
        "- cf 45k\n"
        "- lương 8tr\n\n"
        "Lệnh:\n"
        "/setbalance – set số dư ban đầu\n"
        "/balance – xem số dư\n"
        "/thang – tổng kết tháng\n"
        "/undo – hoàn tác giao dịch"
    )


async def setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Dùng: /setbalance 5tr")
        return

    amount = parse_amount(context.args[0])
    if not amount:
        await update.message.reply_text("Không đọc được số tiền.")
        return

    c.execute("UPDATE balance SET amount = ? WHERE id = 1", (amount,))
    conn.commit()

    await update.message.reply_text(f"✅ Đã set số dư: {amount:,}đ")


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT amount FROM balance WHERE id = 1")
    bal = c.fetchone()[0]
    await update.message.reply_text(f"💰 Số dư hiện tại: {bal:,}đ")


async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT id, amount, type FROM transactions ORDER BY id DESC LIMIT 1")
    row = c.fetchone()

    if not row:
        await update.message.reply_text("❌ Không có giao dịch để hoàn tác.")
        return

    tx_id, amount, ttype = row

    if ttype == "chi":
        c.execute("UPDATE balance SET amount = amount + ?", (amount,))
    else:
        c.execute("UPDATE balance SET amount = amount - ?", (amount,))

    c.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    conn.commit()

    await update.message.reply_text("✅ Đã hoàn tác giao dịch gần nhất.")


async def thang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    year, month = now.year, now.month

    start = f"{year}-{month:02d}-01"
    end = f"{year + (month == 12)}-{1 if month == 12 else month + 1:02d}-01"

    c.execute("""
        SELECT IFNULL(SUM(amount), 0)
        FROM transactions
        WHERE type = 'thu' AND created_at >= ? AND created_at < ?
    """, (start, end))
    total_income = c.fetchone()[0]

    c.execute("""
        SELECT IFNULL(SUM(amount), 0)
        FROM transactions
        WHERE type = 'chi' AND created_at >= ? AND created_at < ?
    """, (start, end))
    total_expense = c.fetchone()[0]

    net = total_income - total_expense

    c.execute("""
        SELECT note, amount
        FROM transactions
        WHERE type = 'chi' AND created_at >= ? AND created_at < ?
        ORDER BY amount DESC
        LIMIT 5
    """, (start, end))
    top_expenses = c.fetchall()

    msg = (
        f"📊 TỔNG KẾT THÁNG {month}/{year}\n\n"
        f"💰 Thu: {total_income:,}đ\n"
        f"💸 Chi: {total_expense:,}đ\n"
        f"📉 Net: {net:,}đ\n"
    )

    if top_expenses:
        msg += "\n🔥 Chi nhiều nhất:\n"
        for note, amount in top_expenses:
            msg += f"- {note}: {amount:,}đ\n"

    await update.message.reply_text(msg)

async def ls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c.execute("""
        SELECT id, type, amount, category, note, created_at
        FROM transactions
        ORDER BY id DESC
        LIMIT 10
    """)
    rows = c.fetchall()

    if not rows:
        await update.message.reply_text("📭 Chưa có giao dịch nào.")
        return

    msg = "📜 10 giao dịch gần nhất:\n\n"

    for tx_id, ttype, amount, category, note, created_at in rows:
        sign = "+" if ttype == "thu" else "-"
        time = created_at.split("T")[0]
        msg += (
            f"#{tx_id} | {time}\n"
            f"{sign}{amount:,}đ | {category}\n"
            f"{note}\n\n"
        )

    await update.message.reply_text(msg)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    amount = parse_amount(text)
    if not amount:
        return

    category = detect_category(text)
    is_income = category == "Thu nhập"
    ttype = "thu" if is_income else "chi"

    if is_income:
        c.execute("UPDATE balance SET amount = amount + ?", (amount,))
    else:
        c.execute("UPDATE balance SET amount = amount - ?", (amount,))

    c.execute("""
        INSERT INTO transactions (amount, type, category, note, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (amount, ttype, category, text, datetime.now().isoformat()))

    conn.commit()

    c.execute("SELECT amount FROM balance WHERE id = 1")
    bal = c.fetchone()[0]

    await update.message.reply_text(
        f"📌 Đã ghi {ttype} {amount:,}đ ({category})\n"
        f"💰 Số dư còn: {bal:,}đ"
    )
# =============================================


# ================== RUN BOT ==================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("setbalance", setbalance))
app.add_handler(CommandHandler("balance", balance))
app.add_handler(CommandHandler("thang", thang))
app.add_handler(CommandHandler("undo", undo))
app.add_handler(CommandHandler("ls", ls))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot is running...")
app.run_polling()
# =============================================
