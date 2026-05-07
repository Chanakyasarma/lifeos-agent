import os
import json
import asyncio
import re
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")

def now_ist() -> datetime:
    return datetime.now(IST)

import gspread
from google.oauth2.service_account import Credentials

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================
# ENV CONFIG
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
# Columns: Task | Time | Status | Priority | Type | Repeat | Goal | Progress | Last Reset
COL_TASK      = 1
COL_TIME      = 2
COL_STATUS    = 3
COL_PRIORITY  = 4
COL_TYPE      = 5
COL_REPEAT    = 6
COL_GOAL      = 7
COL_PROGRESS  = 8
COL_LASTRESET = 9

scope = ["https://www.googleapis.com/auth/spreadsheets"]
creds_dict = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
client = gspread.authorize(creds)


def _extract_sheet_id(value: str) -> str:
    value = (value or "").strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
    return match.group(1) if match else value


sheet = client.open_by_key(_extract_sheet_id(GOOGLE_SHEET_ID)).sheet1


# =========================
# SHEET HELPERS
# =========================
def load_tasks():
    return sheet.get_all_records()


def add_task(row: dict):
    sheet.append_row([
        row.get("Task", ""),
        row.get("Time", "Anytime"),
        row.get("Status", "Pending"),
        row.get("Priority", "Medium"),
        row.get("Type", "General"),
        row.get("Repeat", "No"),
        row.get("Goal", ""),
        row.get("Progress", 0),
        row.get("Last Reset", ""),
    ])


def update_cell(row_index: int, col: int, value):
    """row_index is 1-based sheet row (data starts at row 2)."""
    sheet.update_cell(row_index, col, value)


def data_row(idx: int) -> int:
    """Convert 0-based task index to 1-based sheet row (header is row 1)."""
    return idx + 2


# =========================
# PARSERS
# =========================
def smart_time(text: str) -> str:
    t = text.lower()
    if "morning" in t:   return "09:00"
    if "afternoon" in t: return "14:00"
    if "evening" in t:   return "18:00"
    if "night" in t:     return "21:00"
    if "later" in t:
        return (now_ist() + timedelta(hours=1)).strftime("%H:%M")
    m = re.search(r'in (\d+)\s*(min|minutes)', t)
    if m:
        return (now_ist() + timedelta(minutes=int(m.group(1)))).strftime("%H:%M")
    m = re.search(r'(\d{1,2}):(\d{2})', t)
    if m:
        return m.group(0)
    return "Anytime"


def detect_priority(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["urgent", "high", "important", "critical", "must"]):
        return "High"
    if any(w in t for w in ["low", "whenever", "optional"]):
        return "Low"
    return "Medium"


def detect_type(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["gym", "workout", "run", "exercise", "lift"]):
        return "Fitness"
    if any(w in t for w in ["study", "read", "learn", "course", "book"]):
        return "Study"
    if any(w in t for w in ["water", "sleep", "meditate", "eat", "meal"]):
        return "Health"
    if any(w in t for w in ["work", "meeting", "task", "project", "email"]):
        return "Work"
    return "General"


def detect_repeat(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["daily", "every day", "everyday", "each day"]):
        return "Daily"
    if any(w in t for w in ["weekly", "every week"]):
        return "Weekly"
    return "No"


def detect_goal(text: str) -> str:
    """Extract a goal label like 'lose weight', 'learn python' from text."""
    m = re.search(r'(?:for|goal[:\s]+|towards)\s+(.+)', text, re.IGNORECASE)
    if m:
        return m.group(1).strip().title()
    return ""


# =========================
# FORMATTERS
# =========================
PRIORITY_EMOJI = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}
REPEAT_EMOJI   = {"Daily": "🔁", "Weekly": "📅", "No": ""}
STATUS_EMOJI   = {"Done": "✅", "Pending": "⏳", "Skipped": "⏭"}


def progress_bar(pct: int, width: int = 8) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled) + f" {pct}%"


def format_task_line(i: int, t: dict, show_buttons: bool = False) -> str:
    p_emoji  = PRIORITY_EMOJI.get(t.get("Priority", "Medium"), "🟡")
    r_emoji  = REPEAT_EMOJI.get(t.get("Repeat", "No"), "")
    s_emoji  = STATUS_EMOJI.get(t.get("Status", "Pending"), "⏳")
    goal     = t.get("Goal", "")
    progress = int(t.get("Progress", 0) or 0)
    line = f"{i}. {p_emoji} {t['Task']} | {t['Time']} {r_emoji} {s_emoji}"
    if goal:
        line += f"\n   🎯 {goal} {progress_bar(progress)}"
    return line


# =========================
# INLINE KEYBOARD BUILDER
# =========================
def task_keyboard(idx: int) -> InlineKeyboardMarkup:
    """Returns Done / Skip / Delete buttons for a specific task index."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Done",   callback_data=f"done:{idx}"),
        InlineKeyboardButton("⏭ Skip",   callback_data=f"skip:{idx}"),
        InlineKeyboardButton("🗑 Delete", callback_data=f"delete:{idx}"),
    ]])


# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 *LifeOS Agent Ready!*\n\nType /help to see all commands.",
        parse_mode="Markdown"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
🤖 *LifeOS Commands*

`/list`  — Show all tasks with priority & goal progress
`/done 0`  — Mark task #0 as Done
`/skip 0`  — Mark task #0 as Skipped
`/delete 0`  — Delete task #0
`/clear`  — Delete ALL completed tasks
`/daily`  — Reset all Daily tasks to Pending (one-button daily plan!)
`/progress 0 80`  — Set goal progress for task #0 to 80%
`/help`  — Show this message

🧠 *Natural add (just type):*
`add gym morning daily high`
`add study dsa evening for Learn Python`
`add drink water in 10 minutes`
`add work on project urgent`

🎯 *Priority:* high / medium / low (or urgent, optional)
🔁 *Repeat:* daily / weekly
🎯 *Goal:* add "for [goal name]" to link a task to a goal
""", parse_mode="Markdown")


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = load_tasks()
    if not tasks:
        await update.message.reply_text("📭 No tasks yet. Type `add gym morning` to start.", parse_mode="Markdown")
        return

    # Group by priority
    high   = [t for t in tasks if t.get("Priority") == "High"]
    medium = [t for t in tasks if t.get("Priority") == "Medium"]
    low    = [t for t in tasks if t.get("Priority") == "Low"]

    msg = "📋 *Your Tasks*\n\n"

    all_tasks = tasks  # preserve original index
    for section, label in [(high, "🔴 High"), (medium, "🟡 Medium"), (low, "🟢 Low")]:
        if not section:
            continue
        msg += f"*{label}*\n"
        for t in section:
            i = all_tasks.index(t)
            msg += format_task_line(i, t) + "\n"
        msg += "\n"

    # Goal summary
    goals = {}
    for t in tasks:
        g = t.get("Goal", "")
        p = int(t.get("Progress", 0) or 0)
        if g:
            if g not in goals:
                goals[g] = []
            goals[g].append(p)

    if goals:
        msg += "🎯 *Goal Progress*\n"
        for g, progresses in goals.items():
            avg = round(sum(progresses) / len(progresses))
            msg += f"  {g}: {progress_bar(avg)}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/done 0`", parse_mode="Markdown")
        return
    try:
        idx = int(context.args[0])
        tasks = load_tasks()
        task_name = tasks[idx].get("Task", f"Task {idx}")
        update_cell(data_row(idx), COL_STATUS, "Done")
        await update.message.reply_text(f"✅ *{task_name}* marked Done!", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Invalid task number.")


async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/skip 0`", parse_mode="Markdown")
        return
    try:
        idx = int(context.args[0])
        tasks = load_tasks()
        task_name = tasks[idx].get("Task", f"Task {idx}")
        update_cell(data_row(idx), COL_STATUS, "Skipped")
        await update.message.reply_text(f"⏭ *{task_name}* skipped.", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Invalid task number.")


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/delete 0`", parse_mode="Markdown")
        return
    try:
        idx = int(context.args[0])
        tasks = load_tasks()
        task_name = tasks[idx].get("Task", f"Task {idx}")
        sheet.delete_rows(data_row(idx))
        await update.message.reply_text(f"🗑 *{task_name}* deleted.", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Invalid task number.")


async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete all tasks where Status is Done or Skipped."""
    tasks = load_tasks()
    # Delete from bottom up so row indices don't shift
    rows_to_delete = [
        data_row(i)
        for i, t in enumerate(tasks)
        if t.get("Status") in ("Done", "Skipped")
    ]
    for row in sorted(rows_to_delete, reverse=True):
        sheet.delete_rows(row)

    count = len(rows_to_delete)
    if count == 0:
        await update.message.reply_text("Nothing to clear — no completed tasks.")
    else:
        await update.message.reply_text(f"🧹 Cleared {count} completed task(s).")


async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset all Daily repeat tasks back to Pending. One-button daily plan reset."""
    tasks = load_tasks()
    today = datetime.now().strftime("%Y-%m-%d")
    reset_count = 0

    for i, t in enumerate(tasks):
        if t.get("Repeat") == "Daily" and t.get("Status") in ("Done", "Skipped", "Pending"):
            update_cell(data_row(i), COL_STATUS, "Pending")
            update_cell(data_row(i), COL_LASTRESET, today)
            reset_count += 1

    if reset_count == 0:
        await update.message.reply_text("No daily tasks found. Add one with: `add gym morning daily`", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"🔁 *Daily plan reset!* {reset_count} task(s) ready for today.\n\nType /list to see your day.",
            parse_mode="Markdown"
        )


async def progress_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set goal progress for a task. Usage: /progress 0 80"""
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/progress 0 80` (task index, percentage)", parse_mode="Markdown")
        return
    try:
        idx = int(context.args[0])
        pct = max(0, min(100, int(context.args[1])))
        tasks = load_tasks()
        task_name = tasks[idx].get("Task", f"Task {idx}")
        update_cell(data_row(idx), COL_PROGRESS, pct)
        if pct == 100:
            update_cell(data_row(idx), COL_STATUS, "Done")
        await update.message.reply_text(
            f"🎯 *{task_name}*\n{progress_bar(pct)}",
            parse_mode="Markdown"
        )
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Invalid task number or percentage.")


# =========================
# INLINE BUTTON CALLBACKS
# =========================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, idx_str = query.data.split(":")
    idx = int(idx_str)
    tasks = load_tasks()

    if idx >= len(tasks):
        await query.edit_message_text("❌ Task not found.")
        return

    task_name = tasks[idx].get("Task", f"Task {idx}")

    if action == "done":
        update_cell(data_row(idx), COL_STATUS, "Done")
        await query.edit_message_text(f"✅ *{task_name}* marked Done!", parse_mode="Markdown")

    elif action == "skip":
        update_cell(data_row(idx), COL_STATUS, "Skipped")
        await query.edit_message_text(f"⏭ *{task_name}* skipped.", parse_mode="Markdown")

    elif action == "delete":
        sheet.delete_rows(data_row(idx))
        await query.edit_message_text(f"🗑 *{task_name}* deleted.", parse_mode="Markdown")


# =========================
# SMART ADD (NATURAL INPUT)
# =========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if not text.lower().startswith("add"):
        return

    raw = text[3:].strip()
    parts = re.split(r",| and |\n", raw)
    added = []

    for p in parts:
        p = p.strip()
        if not p:
            continue

        row = {
            "Task":       p,
            "Time":       smart_time(p),
            "Status":     "Pending",
            "Priority":   detect_priority(p),
            "Type":       detect_type(p),
            "Repeat":     detect_repeat(p),
            "Goal":       detect_goal(p),
            "Progress":   0,
            "Last Reset": "",
        }
        add_task(row)

        # Find the row index of what we just added (last row)
        all_tasks = load_tasks()
        new_idx = len(all_tasks) - 1

        p_emoji = PRIORITY_EMOJI.get(row["Priority"], "🟡")
        r_emoji = REPEAT_EMOJI.get(row["Repeat"], "")
        summary = f"{p_emoji} *{row['Task']}* | {row['Time']} {r_emoji}"
        if row["Goal"]:
            summary += f"\n🎯 Goal: {row['Goal']}"

        # Send with inline Done/Skip/Delete buttons
        await update.message.reply_text(
            f"✅ Added: {summary}",
            parse_mode="Markdown",
            reply_markup=task_keyboard(new_idx)
        )
        added.append(p)

    if not added:
        await update.message.reply_text("❓ Couldn't parse that. Try: `add gym morning daily high`", parse_mode="Markdown")


# =========================
# BACKGROUND CHECKER
# =========================
async def checker(app):
    while True:
        try:
            tasks = load_tasks()
            now = now_ist().strftime("%H:%M")

            for i, t in enumerate(tasks):
                if t.get("Status") == "Pending" and t.get("Time") == now:
                    p_emoji = PRIORITY_EMOJI.get(t.get("Priority", "Medium"), "🟡")
                    await app.bot.send_message(
                        chat_id=CHAT_ID,
                        text=f"🔔 *Reminder:* {p_emoji} {t['Task']}",
                        parse_mode="Markdown",
                        reply_markup=task_keyboard(i)
                    )
        except Exception as e:
            print(f"[checker error] {e}")

        await asyncio.sleep(60)


# =========================
# DAILY AUTO-RESET (MIDNIGHT IST)
# =========================
async def midnight_reset(app):
    """Auto-reset daily tasks at midnight IST every day."""
    while True:
        now = now_ist()
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        wait_seconds = (next_midnight - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        try:
            tasks = load_tasks()
            today = now_ist().strftime("%Y-%m-%d")
            count = 0
            for i, t in enumerate(tasks):
                if t.get("Repeat") == "Daily":
                    update_cell(data_row(i), COL_STATUS, "Pending")
                    update_cell(data_row(i), COL_LASTRESET, today)
                    count += 1

            if count > 0 and CHAT_ID:
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🌅 *Good morning!* Your {count} daily task(s) have been reset.\n\nType /list to see your day.",
                    parse_mode="Markdown"
                )
        except Exception as e:
            print(f"[midnight_reset error] {e}")


# =========================
# MAIN
# =========================
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("list",     list_tasks))
    app.add_handler(CommandHandler("done",     done_cmd))
    app.add_handler(CommandHandler("skip",     skip_cmd))
    app.add_handler(CommandHandler("delete",   delete_cmd))
    app.add_handler(CommandHandler("clear",    clear_cmd))
    app.add_handler(CommandHandler("daily",    daily_cmd))
    app.add_handler(CommandHandler("progress", progress_cmd))
    app.add_handler(CommandHandler("help",     help_cmd))

    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    async def post_init(app):
        asyncio.create_task(checker(app))
        asyncio.create_task(midnight_reset(app))

    app.post_init = post_init

    print("🚀 LifeOS Agent running...")
    app.run_polling()


if __name__ == "__main__":
    main()
