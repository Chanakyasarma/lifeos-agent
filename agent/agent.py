import os
import json
import asyncio
import re
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# =========================
# ENV CONFIG (FLY.IO SAFE)
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

if not TELEGRAM_TOKEN:
    raise Exception("Missing TELEGRAM_TOKEN")

if not GOOGLE_CREDS_JSON:
    raise Exception("Missing GOOGLE_CREDS_JSON")

# =========================
# GOOGLE SHEETS INIT
# =========================
scope = ["https://www.googleapis.com/auth/spreadsheets"]

creds_dict = json.loads(GOOGLE_CREDS_JSON)
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)

client = gspread.authorize(creds)


def _extract_sheet_id(value: str) -> str:
    """Accept a raw sheet ID or a full Google Sheets URL."""
    value = (value or "").strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
    if match:
        return match.group(1)
    return value


sheet = client.open_by_key(_extract_sheet_id(GOOGLE_SHEET_ID)).sheet1


# =========================
# HELPERS
# =========================
def load_tasks():
    return sheet.get_all_records()


def add_task(row):
    sheet.append_row([
        row["Task"],
        row["Time"],
        row["Status"],
        row["Priority"],
        row["Type"]
    ])


def update_status(row_index, value):
    sheet.update_cell(row_index, 3, value)


# =========================
# SMART TIME PARSER
# =========================
def smart_time(text):
    text = text.lower()

    if "morning" in text:
        return "09:00"
    if "evening" in text:
        return "18:00"
    if "night" in text:
        return "21:00"
    if "later" in text:
        return (datetime.now() + timedelta(hours=1)).strftime("%H:%M")

    match = re.search(r'in (\d+)\s*(min|minutes)', text)
    if match:
        return (datetime.now() + timedelta(minutes=int(match.group(1)))).strftime("%H:%M")

    match = re.search(r'(\d{1,2}):(\d{2})', text)
    if match:
        return match.group(0)

    return "Anytime"


def detect_priority(text):
    if "high" in text:
        return "High"
    if "low" in text:
        return "Low"
    return "Medium"


def detect_type(text):
    if "gym" in text:
        return "Fitness"
    if "study" in text:
        return "Study"
    if "water" in text:
        return "Health"
    return "General"


# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 LifeOS Bot Running!")


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = load_tasks()

    if not tasks:
        await update.message.reply_text("📭 No tasks")
        return

    msg = "📋 Tasks:\n\n"
    for i, t in enumerate(tasks):
        msg += f"{i}. {t['Task']} | {t['Time']} | {t['Status']}\n"

    await update.message.reply_text(msg)


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /done 0")
        return

    idx = int(context.args[0]) + 2
    update_status(idx, "Done")

    await update.message.reply_text("✅ Done")


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delete 0")
        return

    idx = int(context.args[0]) + 2
    sheet.delete_rows(idx)

    await update.message.reply_text("🗑 Deleted")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
🤖 Commands:
/list
/done 0
/delete 0

🧠 Add tasks naturally:
add gym evening
add study dsa morning
add drink water in 10 minutes
""")


# =========================
# SMART ADD (NATURAL INPUT)
# =========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()

    if not text.startswith("add"):
        return

    text = text.replace("add", "").strip()
    parts = re.split(r",| and |\n", text)

    for p in parts:
        if not p.strip():
            continue

        task = p.strip()

        row = {
            "Task": task,
            "Time": smart_time(task),
            "Status": "Pending",
            "Priority": detect_priority(task),
            "Type": detect_type(task)
        }

        add_task(row)

    await update.message.reply_text("✅ Task(s) added")


# =========================
# BACKGROUND CHECKER
# =========================
async def checker(app):
    while True:
        tasks = load_tasks()
        now = datetime.now().strftime("%H:%M")

        for i, t in enumerate(tasks, start=2):
            if t["Status"] == "Pending" and t["Time"] == now:
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🔔 {t['Task']} is due now!"
                )

        await asyncio.sleep(60)


# =========================
# MAIN
# =========================
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    async def post_init(app):
        asyncio.create_task(checker(app))

    app.post_init = post_init

    print("🚀 Bot running on Fly.io...")
    app.run_polling()


if __name__ == "__main__":
    main()