import asyncio
import logging
import sys
from datetime import datetime, timedelta
import os
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from html import escape
import re

from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    FSInputFile,
)

from config import (
    BOT_TOKEN,
    API_KEY,
    TEXT_PROCESSING_PROMPT,
    CHANNEL_NAME,
    MODEL,
)
from database import (
    initialize_database,
    add_article,
    get_queued_articles,
    get_article_by_id,
    delete_article,
    update_time_scheduled,
)
from openai import OpenAI

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Initialize database
initialize_database()

# Create router for article submission
article_router = Router()


class ArticleSubmission(StatesGroup):
    waiting_for_text = State()
    waiting_for_image = State()


@article_router.message(Command("start"))
async def start_command(message: Message):
    help_text = """Добро пожаловать в ShipAI! 🚢

Доступные команды:
/new_article - Добавить публикацию в очередь
/queue - Посмотреть очередь публикаций
/delete id - Удалить публикацию из очереди
/post_now id - Отправить публикацию немедленно в канал
/cancel - Отменить текущую операцию
/help - Показать это сообщение

Чтобы начать, используйте /new_article для добавления первой публикации!
"""

    await message.answer(help_text, parse_mode="HTML")


@article_router.message(Command("help"))
async def help_command(message: Message):
    help_text = """Доступные команды:
/new_article - Добавить публикацию в очередь
/queue - Посмотреть очередь публикаций
/delete id - Удалить публикацию из очереди
/post_now id - Отправить публикацию немедленно в канал
/cancel - Отменить текущую операцию
/help - Показать это сообщение"""

    await message.reply(help_text)


@article_router.message(Command("new_article"))
async def new_article_command(message: Message, state: FSMContext):
    await message.reply("Отправьте текст оригинальной публикации.")
    await state.set_state(ArticleSubmission.waiting_for_text)


@article_router.message(ArticleSubmission.waiting_for_text)
async def process_article_text(message: Message, state: FSMContext):
    original_text = message.text
    await message.reply("Текст в обработке...")

    try:
        client = OpenAI(api_key=API_KEY)

        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "user", "content": TEXT_PROCESSING_PROMPT},
                {"role": "user", "content": original_text},
            ],
            max_tokens=350,
        )

        processed_text = completion.choices[0].message.content

        # Create keyboard for image submission
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Skip")], [KeyboardButton(text="Cancel")]],
            resize_keyboard=True,
        )

        await message.reply(
            "Текст обработан успешно! Пожалуйста, отправьте изображение (необязательно) или нажмите Skip, чтобы продолжить без изображения.",
            reply_markup=keyboard,
        )
        await state.update_data(
            original_text=original_text, processed_text=processed_text
        )
        await state.set_state(ArticleSubmission.waiting_for_image)

    except Exception as e:
        logging.error(f"Error processing text: {e}")
        await message.reply(
            "Ошибка при обработке текста. Пожалуйста, попробуйте еще раз."
        )
        await state.clear()


@article_router.message(
    ArticleSubmission.waiting_for_image, F.text.casefold() == "skip"
)
async def skip_article_image(message: Message, state: FSMContext):
    data = await state.get_data()
    add_article(data["original_text"], data["processed_text"])

    await message.reply(
        "Статья добавлена в очередь без изображения!",
        reply_markup=ReplyKeyboardRemove(),
    )

    help_text = """Доступные команды:
/new_article - Добавить публикацию в очередь
/queue - Посмотреть очередь публикаций
/delete id - Удалить публикацию из очереди
/post_now id - Отправить публикацию немедленно в канал
/cancel - Отменить текущую операцию
/help - Показать это сообщение"""

    await message.answer(help_text, parse_mode="HTML")

    await state.clear()


@article_router.message(Command("cancel"))
@article_router.message(F.text.casefold() == "cancel")
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.reply("Нет активной операции для отмены.")
        return

    logging.info("Cancelling state %r", current_state)
    await state.clear()
    await message.reply("Операция отменена.", reply_markup=ReplyKeyboardRemove())


@article_router.message(ArticleSubmission.waiting_for_image, F.content_type == "photo")
async def process_article_image(message: Message, state: FSMContext):
    photo = message.photo[-1]

    # Create images directory if it doesn't exist
    os.makedirs("images", exist_ok=True)

    image_path = f"images/{photo.file_unique_id}.jpg"
    await bot.download(photo, destination=image_path)

    data = await state.get_data()
    add_article(data["original_text"], data["processed_text"], image_path=image_path)

    await message.reply(
        "Статья с изображением добавлена в очередь!", reply_markup=ReplyKeyboardRemove()
    )
    help_text = """
Доступные команды:
/new_article - Добавить публикацию в очередь
/queue - Посмотреть очередь публикаций
/delete id - Удалить публикацию из очереди
/post_now id - Отправить публикацию немедленно в канал
/cancel - Отменить текущую операцию
/help - Показать это сообщение
"""

    await message.answer(help_text, parse_mode="HTML")
    await state.clear()


# Queue management router
queue_router = Router()


@queue_router.message(Command("queue"))
async def view_queue(message: Message):
    articles = get_queued_articles()
    if not articles:
        await message.reply("Очередь публикаций пуста.")
    else:
        queue_message = "Очередь публикаций:\n\n"
        for article in articles:
            queue_message += f"ID: {article[0]}\n{article[2][:60]}...\nЗапланировано на: {article[6]}\n\n"
            text = escape(queue_message)

        await message.reply(text, parse_mode="HTML")


@queue_router.message(Command("delete"))
async def delete_article_from_queue(message: Message):
    try:
        # Extract article ID from command arguments
        command_args = message.text.split()
        if len(command_args) < 2:
            await message.reply(
                "Пожалуйста, укажите ID публикации. Использование: /delete id"
            )
            return

        article_id = int(command_args[1])
        delete_article(article_id)
        await message.reply(f"Статья с ID {article_id} удалена из очереди.")

    except ValueError:
        await message.reply("Пожалуйста, укажите действительный ID публикации.")
    except Exception as e:
        logging.error(f"Error deleting article: {e}")
        await message.reply(
            "Ошибка при удалении публикации. Пожалуйста, попробуйте еще раз."
        )


@queue_router.message(Command("post_now"))
async def post_now_command(message: Message):
    try:
        # Extract article ID from command arguments
        command_args = message.text.split()
        if len(command_args) < 2:
            await message.reply(
                "Пожалуйста, укажите ID публикации. Использование: /post_now id"
            )
            return

        article_id = int(command_args[1])
        article = get_article_by_id(article_id)

        if not article:
            await message.reply(f"Статья с ID {article_id} не найдена в очереди.")
            return

        # Extract article data
        _, text, processed_text, image_url, status, created_at, scheduled_at = article

        # Post the article immediately
        await post_article_to_channel(article_id, processed_text, image_url)
        await message.reply(f"Статья с ID {article_id} отправлена немедленно в канал!")

        help_text = """Доступные команды:
/new_article - Добавить публикацию в очередь
/queue - Посмотреть очередь публикаций
/delete id - Удалить публикацию из очереди
/post_now id - Отправить публикацию немедленно в канал
/cancel - Отменить текущую операцию
/help - Показать это сообщение"""

        await message.answer(help_text, parse_mode="HTML")

    except ValueError:
        await message.reply("Пожалуйста, укажите действительный ID публикации.")
    except Exception as e:
        logging.error(f"Error posting article immediately: {e}")
        await message.reply(
            "Ошибка при отправке публикации. Пожалуйста, попробуйте еще раз."
        )


# Register routers
dp.include_router(article_router)
dp.include_router(queue_router)

# Scheduling
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()


async def post_article_to_channel(article_id, text, image_path=None):
    try:

        if image_path and os.path.exists(image_path):
            photo = FSInputFile(image_path)
            await bot.send_photo(
                chat_id=CHANNEL_NAME,
                photo=photo,
                caption=text,
            )
        else:
            await bot.send_message(chat_id=CHANNEL_NAME, text=text)

        # Mark article as posted
        delete_article(article_id)
        logging.info(f"Статья {article_id} была опубликована успешно!")

    except Exception as e:
        logging.error(f"Error posting article {article_id}: {e}")


async def schedule_posts():
    articles = get_queued_articles()
    if not articles:
        return

    # Get current time
    now = datetime.now()
    today_9am = now.replace(hour=9, minute=0, second=0, microsecond=0)
    today_8pm = now.replace(hour=20, minute=0, second=0, microsecond=0)

    # Time slots: 9:00, 11:12, 13:24, 15:36, 17:48 (approximately every 2h 12m)
    slot_interval_minutes = (11 * 60) // 5  # 132 minutes between posts

    # Calculate all time slots for today
    time_slots = []
    for i in range(5):
        slot_time = today_9am + timedelta(minutes=slot_interval_minutes * i)
        time_slots.append(slot_time)

    print(time_slots)

    # Determine which slots are still available today
    available_slots = []
    if now < today_9am:
        # Before 9am, all slots for today are available
        available_slots = time_slots
    elif now > today_8pm:
        # After 8pm, schedule for tomorrow
        tomorrow_9am = today_9am + timedelta(days=1)
        available_slots = [
            tomorrow_9am + timedelta(minutes=slot_interval_minutes * i)
            for i in range(5)
        ]
    else:
        # During posting hours, find remaining slots for today
        for slot_time in time_slots:
            if slot_time > now:
                available_slots.append(slot_time)

        # If no slots left today, add tomorrow's slots
        if not available_slots:
            tomorrow_9am = today_9am + timedelta(days=1)
            available_slots = [
                tomorrow_9am + timedelta(minutes=slot_interval_minutes * i)
                for i in range(5)
            ]

    # Schedule articles to available slots
    slot_index = 0
    for article in articles:
        (
            article_id,
            text,
            processed_text,
            image_path,
            status,
            created_at,
            scheduled_at,
        ) = article

        if not scheduled_at:
            job_id = f"article_{article_id}"
            # Check if job already exists
            try:
                existing_job = scheduler.get_job(job_id)
                if existing_job:
                    continue  # Skip if already scheduled
            except:
                pass  # Job doesn't exist, continue with scheduling

            # Get the next available slot
            if slot_index < len(available_slots):
                post_time = available_slots[slot_index]
            else:
                # If we've used all available slots, schedule for next day
                days_ahead = (slot_index - len(available_slots)) // 5 + 1
                slot_in_day = (slot_index - len(available_slots)) % 5
                next_day = today_9am + timedelta(days=days_ahead)
                post_time = next_day + timedelta(
                    minutes=slot_interval_minutes * slot_in_day
                )

            update_time_scheduled(article_id, post_time)

            scheduler.add_job(
                post_article_to_channel,
                "date",
                run_date=post_time,
                args=[article_id, processed_text, image_path],
                id=job_id,
            )
            logging.info(f"Scheduled article {article_id} for posting at {post_time}")
            slot_index += 1


# Schedule the post scheduler to run every minute
scheduler.add_job(schedule_posts, "interval", minutes=1)


async def main():
    # Start scheduler
    scheduler.start()

    # Start bot polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
