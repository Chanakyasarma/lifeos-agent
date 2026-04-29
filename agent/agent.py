import pandas as pd
from datetime import datetime, timedelta
import asyncio
import re
import config

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================================
# 📊 CONFIG
# ================================
COLUMNS = ["Task", "Time", "Status", "Priority", "Type", "Repeat", "Goal", "Progress", "Last Reset"]

# ================================
# 📊 EXCEL
# ================================
def load_df():
    try:
        df = pd.read_excel(config.FILE_PATH, engine="openpyxl")

        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""

        return df.astype(str)  # fix dtype issues

    except:
        return pd.DataFrame(columns=COLUMNS)


def save_df(df):
    try:
        df.to_excel(config.FILE_PATH, index=False)
    except:
        print("⚠️ Close Excel file!")

# ================================
# 🧠 SMART PARSERS
# ================================
def smart_time(text):
    text = text.lower()

    if "morning" in text:
        return "09:00"
    if "afternoon" in text:
        return "14:00"
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

    match = re.search(r'(\d{1,2})\s*(am|pm)', text)
    if match:
        hour = int(match.group(1))
        if match.group(2) == "pm" and hour != 12:
            hour += 12
        if match.group(2) == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:00"

    return "Anytime"


def parse_priority(text):
    if "high" in text:
        return "High"
    if "low" in text:
        return "Low"
    return "Medium"


def detect_repeat(text):
    return "Daily" if "daily" in text or "everyday" in text else "None"


def detect_type(text):
    if "study" in text or "dsa" in text:
        return "Study"
    if "gym" in text or "workout" in text:
        return "Fitness"
    if "read" in text:
        return "Reading"
    if "work" in text:
        return "Work"
    if "water" in text:
        return "Health"
    return "General"


def detect_goal(text):
    match = re.search(r'(\d+)\s*l', text)
    return f"{match.group(1)}L" if match else ""

# ================================
# 🔔 BUTTONS
# ================================
async def send_buttons(app, task, index):
    keyboard = [[
        InlineKeyboardButton("✅ Done", callback_data=f"done|{index}"),
        InlineKeyboardButton("🗑 Delete", callback_data=f"delete|{index}")
    ]]

    await app.bot.send_message(
        chat_id=config.CHAT_ID,
        text=f"🔔 {task}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    action, i = q.data.split("|")
    i = int(i)

    df = load_df()

    if action == "done":
        df.loc[i, "Status"] = "Done"
        await q.edit_message_text("✅ Done")

    elif action == "delete":
        df = df.drop(i).reset_index(drop=True)
        await q.edit_message_text("🗑 Deleted")

    save_df(df)

# ================================
# 📋 COMMANDS
# ================================
async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = load_df()

    if df.empty:
        await update.message.reply_text("📭 No tasks")
        return

    msg = "📋 Tasks:\n\n"
    for i, row in df.iterrows():
        msg += f"{i}. {row['Task']} | {row['Time']} | {row['Status']} | {row['Type']}\n"

    await update.message.reply_text(msg)


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = load_df()

    if not context.args:
        await update.message.reply_text("❌ Usage: /delete 1")
        return

    i = int(context.args[0])

    if i >= len(df):
        await update.message.reply_text("❌ Invalid index")
        return

    df = df.drop(i).reset_index(drop=True)
    save_df(df)

    await update.message.reply_text("🗑 Deleted")


async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = load_df()

    if not context.args:
        await update.message.reply_text("❌ Usage: /done 1")
        return

    i = int(context.args[0])

    if i >= len(df):
        await update.message.reply_text("❌ Invalid index")
        return

    df.loc[i, "Status"] = "Done"
    save_df(df)

    await update.message.reply_text("✅ Done")


async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = load_df()
    df = df.iloc[0:0]
    save_df(df)

    await update.message.reply_text("🗑 All tasks cleared")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
🤖 Commands:
/list
/delete 1
/done 1
/clear

🧠 Smart:
add study dsa morning daily
add gym evening daily high
add drink water 3L daily
drank 1L

🧠 Multi-task:
add study dsa morning, gym evening
add study dsa morning and gym evening
(add multiline supported)
""")

# ================================
# 🧠 TEXT HANDLER (SMART + MULTI)
# ================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    df = load_df()

    # 💧 WATER TRACK
    match = re.search(r'(\d+(\.\d+)?)\s*l', text)
    if "drink" in text or "drank" in text:
        if match:
            amount = float(match.group(1))

            for i, row in df.iterrows():
                if "water" in row["Task"].lower():
                    current = float(row["Progress"]) if row["Progress"] not in ["", "nan"] else 0
                    df.loc[i, "Progress"] = current + amount
                    save_df(df)
                    await update.message.reply_text(f"💧 Total: {current + amount}L")
                    return

    # =========================
    # MULTI TASK PARSER
    # =========================
    text = re.sub(r'^add', '', text).strip()

    lines = text.split("\n")

    tasks = []
    for line in lines:
        parts = re.split(r',| and ', line)
        for part in parts:
            part = part.strip()
            if part:
                tasks.append(part)

    if tasks:
        added_tasks = []

        for part in tasks:
            time_str = smart_time(part)
            priority = parse_priority(part)
            repeat = detect_repeat(part)
            task_type = detect_type(part)
            goal = detect_goal(part)

            task = re.sub(r'at .*|in .*|daily|everyday', '', part).strip()

            df = pd.concat([df, pd.DataFrame([{
                "Task": task,
                "Time": time_str,
                "Status": "Pending",
                "Priority": priority,
                "Type": task_type,
                "Repeat": repeat,
                "Goal": goal,
                "Progress": "",
                "Last Reset": ""
            }])], ignore_index=True)

            added_tasks.append(f"{task} ({time_str})")

        save_df(df)

        await update.message.reply_text("✅ Added:\n" + "\n".join(added_tasks))
        return

    await update.message.reply_text("❌ Couldn't understand. Try /help")

# ================================
# ⏱ CHECK LOOP
# ================================
async def checker(app):
    while True:
        df = load_df()
        now = datetime.now().strftime("%H:%M")
        today = datetime.now().strftime("%Y-%m-%d")

        for i, row in df.iterrows():

            if row["Repeat"] == "Daily" and row["Last Reset"] != today:
                df.loc[i, "Status"] = "Pending"
                df.loc[i, "Last Reset"] = today

            if row["Status"] == "Pending" and row["Time"] == now:
                await send_buttons(app, row["Task"], i)

        save_df(df)
        await asyncio.sleep(60)

# ================================
# 🚀 MAIN
# ================================
def main():
    print("🚀 LifeOS Smart Agent Running...")

    app = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    # Buttons
    app.add_handler(CallbackQueryHandler(button_handler))

    # Text LAST
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    async def start(app):
        asyncio.create_task(checker(app))

    app.post_init = start

    app.run_polling()


if __name__ == "__main__":
    main()