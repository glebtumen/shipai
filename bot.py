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
from html.parser import HTMLParser

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

# Admin user IDs
ADMIN_USER_IDS = {505429653, 409472138}

def admin_required(func):
    """Decorator to check if user is admin before executing command"""
    async def wrapper(message: Message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id not in ADMIN_USER_IDS:
            await message.reply("❌ Доступ запрещен. Эта команда доступна только администраторам.")
            logging.warning(f"Unauthorized access attempt by user {user_id} (@{message.from_user.username})")
            return
        return await func(message, *args, **kwargs)
    return wrapper

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
@admin_required
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
@admin_required
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
@admin_required
async def new_article_command(message: Message, state: FSMContext):
    await message.reply("Отправьте текст оригинальной публикации.")
    await state.set_state(ArticleSubmission.waiting_for_text)


@article_router.message(ArticleSubmission.waiting_for_text)
async def process_article_text(message: Message, state: FSMContext):
    original_text = message.text
    await message.reply("Текст в обработке...")

    try:
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=API_KEY)

        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "user", "content": TEXT_PROCESSING_PROMPT},
                {"role": "user", "content": original_text},
            ],
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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


class TelegramHTMLSanitizer(HTMLParser):
    """HTML parser to sanitize content for Telegram"""
    
    def __init__(self):
        super().__init__()
        self.result = []
        self.allowed_tags = {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'code', 'pre'}
        self.tag_stack = []
        
    def handle_starttag(self, tag, attrs):
        if tag in self.allowed_tags:
            self.result.append(f'<{tag}>')
            self.tag_stack.append(tag)
        elif tag in ['ul', 'ol']:
            # Start of list - add newline
            self.result.append('\n')
        elif tag == 'li':
            # List item - add bullet point
            self.result.append('• ')
            
    def handle_endtag(self, tag):
        if tag in self.allowed_tags and self.tag_stack and self.tag_stack[-1] == tag:
            self.result.append(f'</{tag}>')
            self.tag_stack.pop()
        elif tag == 'li':
            # End of list item - add newline
            self.result.append('\n')
        elif tag in ['ul', 'ol']:
            # End of list - add extra newline
            self.result.append('\n')
            
    def handle_data(self, data):
        self.result.append(data)
        
    def get_sanitized_text(self):
        # Close any unclosed tags
        while self.tag_stack:
            tag = self.tag_stack.pop()
            self.result.append(f'</{tag}>')
        
        # Join and clean up extra whitespace
        text = ''.join(self.result)
        # Remove multiple consecutive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


def sanitize_html_for_telegram(text):
    """Sanitize HTML content for Telegram posting"""
    try:
        parser = TelegramHTMLSanitizer()
        parser.feed(text)
        return parser.get_sanitized_text()
    except Exception as e:
        logging.error(f"Error sanitizing HTML: {e}")
        # Fallback: strip all HTML tags
        clean_text = re.sub(r'<[^>]+>', '', text)
        return clean_text


async def post_article_to_channel(article_id, text, image_path=None):
    try:
        # Sanitize HTML content for Telegram
        sanitized_text = sanitize_html_for_telegram(text)
        
        # Check if text is too long for caption (1700 bytes limit thats around 1024 chars)
        text_bytes = len(sanitized_text.encode('utf-8'))
        
        if text_bytes > 1700:
            # Text is too long for caption, send as text-only message
            logging.info(f"Article {article_id} text too long ({text_bytes} bytes), sending as text-only")
            await bot.send_message(chat_id=CHANNEL_NAME, text=sanitized_text)
        else:
            # Text fits in caption
            if image_path and os.path.exists(image_path):
                photo = FSInputFile(image_path)
                await bot.send_photo(
                    chat_id=CHANNEL_NAME,
                    photo=photo,
                    caption=sanitized_text,
                )
            else:
                await bot.send_message(chat_id=CHANNEL_NAME, text=sanitized_text)

        # Mark article as posted
        delete_article(article_id)
        logging.info(f"Статья {article_id} была опубликована успешно!")

    except Exception as e:
        logging.error(f"Error posting article {article_id}: {e}")


async def schedule_posts():
    """
    Database-driven scheduler that:
    1. Posts articles that are ready (scheduled_at <= now)
    2. Schedules new articles (scheduled_at is None)
    """
    articles = get_queued_articles()
    if not articles:
        return

    now = datetime.now()
    logging.info(f"Scheduler running at {now}")

    # STEP 1: Check for articles ready to post
    ready_articles = []
    scheduled_articles = []
    unscheduled_articles = []
    
    for article in articles:
        article_id, text, processed_text, image_path, status, created_at, scheduled_at = article
        
        if scheduled_at:  # Article has a scheduled time
            try:
                # Parse the scheduled time from database
                if isinstance(scheduled_at, str):
                    scheduled_time = datetime.fromisoformat(scheduled_at)
                else:
                    scheduled_time = scheduled_at
                
                if scheduled_time <= now:
                    # Article is ready to post
                    ready_articles.append(article)
                else:
                    # Article is scheduled for future
                    scheduled_articles.append((article, scheduled_time))
            except Exception as e:
                logging.error(f"Error parsing scheduled_at for article {article_id}: {e}")
        else:
            # Article needs to be scheduled
            unscheduled_articles.append(article)
    
    # Post ready articles immediately
    for article in ready_articles:
        article_id, text, processed_text, image_path, status, created_at, scheduled_at = article
        logging.info(f"Posting article {article_id} (scheduled for {scheduled_at})")
        await post_article_to_channel(article_id, processed_text, image_path)
    
    # STEP 2: Schedule new articles if any
    if unscheduled_articles:
        logging.info(f"Found {len(unscheduled_articles)} unscheduled articles to schedule")
        
        # Get current time slots
        today_9am = now.replace(hour=9, minute=0, second=0, microsecond=0)
        today_8pm = now.replace(hour=20, minute=0, second=0, microsecond=0)
        slot_interval_minutes = (11 * 60) // 5  # 132 minutes between posts

        # Get all already scheduled times from database
        occupied_slots = set()
        for article, scheduled_time in scheduled_articles:
            occupied_slots.add(scheduled_time)

        # Generate potential time slots for multiple days
        potential_slots = []
        
        # Calculate slots for today
        time_slots_today = []
        for i in range(5):
            slot_time = today_9am + timedelta(minutes=slot_interval_minutes * i)
            time_slots_today.append(slot_time)

        # Determine which slots are available today based on current time
        if now < today_9am:
            # Before 9am, all slots for today are potentially available
            potential_slots.extend(time_slots_today)
        elif now > today_8pm:
            # After 8pm, skip today and start with tomorrow
            pass
        else:
            # During posting hours, find remaining slots for today
            for slot_time in time_slots_today:
                if slot_time > now:
                    potential_slots.append(slot_time)

        # Add slots for next few days to ensure we have enough slots
        for day_offset in range(1, 8):  # Next 7 days
            future_day_9am = today_9am + timedelta(days=day_offset)
            for i in range(5):
                slot_time = future_day_9am + timedelta(minutes=slot_interval_minutes * i)
                potential_slots.append(slot_time)

        # Filter out occupied slots to get truly available slots
        available_slots = [slot for slot in potential_slots if slot not in occupied_slots]
        
        logging.info(f"Found {len(occupied_slots)} occupied slots, {len(available_slots)} available slots")

        # Schedule unscheduled articles to available slots
        for slot_index, article in enumerate(unscheduled_articles):
            article_id, text, processed_text, image_path, status, created_at, scheduled_at = article

            # Get the next available slot
            if slot_index < len(available_slots):
                post_time = available_slots[slot_index]
                
                # Update database with scheduled time
                update_time_scheduled(article_id, post_time)
                logging.info(f"Scheduled article {article_id} for posting at {post_time}")
            else:
                logging.warning(f"No available slots for article {article_id}")
    
    # Log summary
    if ready_articles:
        logging.info(f"Posted {len(ready_articles)} articles this run")
    if scheduled_articles:
        logging.info(f"Found {len(scheduled_articles)} articles scheduled for future")
    if unscheduled_articles:
        logging.info(f"Scheduled {min(len(unscheduled_articles), len(available_slots) if 'available_slots' in locals() else 0)} new articles")


# Schedule the post scheduler to run every minute
scheduler.add_job(schedule_posts, "interval", minutes=1)


async def test_posting():
    """Test function to schedule posts for +2 minutes from current time"""
    from database import add_article
    
    # Sample test articles with various edge cases
    test_articles = [
        {
            "original": "Normal article test",
            "processed": "🚢 <b>Test Article 1</b>\n\nThis is a normal test article with proper formatting.\n\n#залоговыйлоцман"
        },
        {
            "original": "Article with unsupported HTML",
            "processed": "🚢 <b>Test Article 2</b>\n\n<ul><li>Item 1</li><li>Item 2</li></ul>\n\nThis has <em>unclosed emphasis and unsupported lists.\n\n#залоговыйлоцман"
        },
        {
            "original": "Very long article",
            "processed": """🚢 <b>Very Long Test Article</b>

This is a very long test article that should exceed the 1024 byte limit for Telegram captions. Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.

Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit, sed quia consequuntur magni dolores eos qui ratione voluptatem sequi nesciunt.

At vero eos et accusamus et iusto odio dignissimos ducimus qui blanditiis praesentibus voluptatum deleniti atque corrupti quos dolores et quas molestias excepturi sint occaecati cupiditate non provident, similique sunt in culpa qui officia deserunt mollitia animi, id est laborum et dolorum fuga.

#залоговыйлоцман"""
        }
    ]
    
    # Add test articles to database
    for i, article in enumerate(test_articles, 1):
        add_article(article["original"], article["processed"])
        logging.info(f"Added test article {i} to database")
    
    # Get current time and schedule for +2 minutes
    now = datetime.now()
    test_time = now + timedelta(minutes=2)
    
    # Get the newly added articles
    articles = get_queued_articles()
    recent_articles = articles[-len(test_articles):]  # Get the last N articles
    
    # Schedule each test article for posting
    for i, article in enumerate(recent_articles):
        article_id = article[0]
        processed_text = article[2]
        image_path = article[3]
        
        # Schedule each article 30 seconds apart starting from +2 minutes
        post_time = test_time + timedelta(seconds=30 * i)
        
        update_time_scheduled(article_id, post_time)
        
        job_id = f"test_article_{article_id}"
        scheduler.add_job(
            post_article_to_channel,
            "date",
            run_date=post_time,
            args=[article_id, processed_text, image_path],
            id=job_id,
        )
        
        logging.info(f"Scheduled test article {article_id} for posting at {post_time}")
    
    print(f"Test articles scheduled! First post at: {test_time}")
    print("Posts will be sent every 30 seconds starting from +2 minutes")


async def main():
    # Start scheduler
    scheduler.start()

    # Start bot polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    # Uncomment the line below to run tests instead of normal operation
    # asyncio.run(test_posting())
    
    asyncio.run(main())
