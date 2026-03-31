import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ─── НАСТРОЙКИ ───────────────────────────────────────────────────────────────

BOT_TOKEN = "8438096428:AAHle1k7VOdkSlTWbN9xTePgl--cU0tDbtQ"

# ─── ЛОГИРОВАНИЕ ─────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── ХРАНИЛИЩЕ НАПОМИНАНИЙ ───────────────────────────────────────────────────

# { chat_id: [ {"id": str, "time": datetime, "text": str, "job": Job} ] }
reminders: Dict[int, List[dict]] = {}


# ─── ПАРСЕР ВРЕМЕНИ ──────────────────────────────────────────────────────────

def parse_reminder(text: str):
    """
    Разбирает текст вида:
      "в 14:00 пойти к врачу"
      "через 30 минут выпить воду"
      "завтра в 9:00 встреча"
    Возвращает (datetime, reminder_text) или (None, None)
    """
    now = datetime.now()
    text = text.strip()

    # ── Формат: "через N минут/часов ..." ────────────────────────────────────
    m = re.match(
        r"через\s+(\d+)\s+(минут[ауы]?|час[оа]?в?)\s+(.*)",
        text,
        re.IGNORECASE,
    )
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        reminder_text = m.group(3).strip()
        if unit.startswith("мин"):
            dt = now + timedelta(minutes=amount)
        else:
            dt = now + timedelta(hours=amount)
        return dt, reminder_text

    # ── Формат: "[завтра] в HH:MM ..." ───────────────────────────────────────
    m = re.match(
        r"(завтра\s+)?в\s+(\d{1,2})[:\.](\d{2})\s+(.*)",
        text,
        re.IGNORECASE,
    )
    if m:
        tomorrow = bool(m.group(1))
        hour = int(m.group(2))
        minute = int(m.group(3))
        reminder_text = m.group(4).strip()
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if tomorrow:
            dt += timedelta(days=1)
        elif dt <= now:
            dt += timedelta(days=1)  # если время уже прошло — завтра
        return dt, reminder_text

    # ── Формат: "HH:MM ..." (без слова "в") ──────────────────────────────────
    m = re.match(r"(\d{1,2})[:\.](\d{2})\s+(.*)", text, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        reminder_text = m.group(3).strip()
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt, reminder_text

    return None, None


# ─── ОТПРАВКА НАПОМИНАНИЯ ────────────────────────────────────────────────────

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    reminder_id = job.data["id"]
    reminder_text = job.data["text"]

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔔 *Напоминание!*\n\n{reminder_text}",
        parse_mode="Markdown",
    )

    # Удаляем из списка
    if chat_id in reminders:
        reminders[chat_id] = [
            r for r in reminders[chat_id] if r["id"] != reminder_id
        ]


# ─── КОМАНДЫ ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Команды:*\n"
        "/list — посмотреть все напоминания\n"
        "/clear — удалить все напоминания",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛟 *Помощь*\n\n"
        "*Форматы времени:*\n"
        "• `в 14:00 текст` — сегодня в 14:00\n"
        "• `завтра в 9:30 текст` — завтра в 09:30\n"
        "• `через 20 минут текст` — через 20 минут\n"
        "• `через 2 часа текст` — через 2 часа\n"
        "• `15:00 текст` — без слова «в»\n\n"
        "Если время уже прошло — напомню завтра в это время.",
        parse_mode="Markdown",
    )


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_reminders = reminders.get(chat_id, [])

    if not user_reminders:
        await update.message.reply_text("📭 У тебя нет активных напоминаний.")
        return

    lines = ["📋 *Твои напоминания:*\n"]
    keyboard = []
    for r in user_reminders:
        time_str = r["time"].strftime("%d.%m %H:%M")
        lines.append(f"⏰ *{time_str}* — {r['text']}")
        keyboard.append(
            [InlineKeyboardButton(f"❌ Удалить: {time_str} {r['text'][:20]}", callback_data=f"del_{r['id']}")]
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def clear_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_reminders = reminders.get(chat_id, [])

    for r in user_reminders:
        r["job"].schedule_removal()

    reminders[chat_id] = []
    await update.message.reply_text("🗑 Все напоминания удалены.")


async def delete_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    reminder_id = query.data.replace("del_", "")

    user_reminders = reminders.get(chat_id, [])
    found = next((r for r in user_reminders if r["id"] == reminder_id), None)

    if found:
        found["job"].schedule_removal()
        reminders[chat_id] = [r for r in user_reminders if r["id"] != reminder_id]
        await query.edit_message_text(f"✅ Напоминание «{found['text']}» удалено.")
    else:
        await query.edit_message_text("⚠️ Напоминание не найдено (возможно, уже сработало).")


# ─── ОБРАБОТКА СООБЩЕНИЙ ─────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    dt, reminder_text = parse_reminder(text)

    if dt is None:
        await update.message.reply_text("🤔 Не понял. Пример: `в 14:00 пойти к врачу`", parse_mode="Markdown")
        return

    # Генерируем уникальный ID
    reminder_id = f"{chat_id}_{int(dt.timestamp())}"

    # Планируем задачу
    delay = (dt - datetime.now()).total_seconds()
    job = context.job_queue.run_once(
        send_reminder,
        when=delay,
        chat_id=chat_id,
        data={"id": reminder_id, "text": reminder_text},
    )

    # Сохраняем
    if chat_id not in reminders:
        reminders[chat_id] = []
    reminders[chat_id].append({
        "id": reminder_id,
        "time": dt,
        "text": reminder_text,
        "job": job,
    })

    time_str = dt.strftime("%d.%m.%Y в %H:%M")
    await update.message.reply_text(
        f"✅ Напоминание сохранено!\n\n"
        f"📅 *{time_str}*\n"
        f"📝 {reminder_text}",
        parse_mode="Markdown",
    )


# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_reminders))
    app.add_handler(CommandHandler("clear", clear_reminders))
    app.add_handler(CallbackQueryHandler(delete_reminder_callback, pattern=r"^del_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
