# ShipAI 🚢

## ✨ Features

- **AI-Powered Text Processing**: Automatically enhances and optimizes your content using OpenAI
- **Smart Scheduling**: Automatically schedules posts across 5 optimal time slots daily
- **Image Support**: Attach images to your posts with automatic handling
- **Queue Management**: View, edit, and manage your content queue
- **Immediate Posting**: Option to post content immediately when needed
- **Timezone Support**: Configurable timezone for accurate scheduling
- **Persistent Storage**: SQLite database for reliable data storage

## 🎯 Scheduling Logic

ShipAI automatically schedules your posts at optimal times:

- **9:00** - Morning engagement
- **11:12** - Mid-morning activity
- **13:24** - Lunch break browsing
- **15:36** - Afternoon check-in
- **17:48** - Evening wind-down

Posts are distributed evenly throughout the day with approximately 2 hours and 12 minutes between each post.

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- Telegram Bot Token ([Get one from @BotFather](https://t.me/botfather))
- OpenAI API Key ([Get one here](https://platform.openai.com/api-keys))

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/glebtumen/shipai.git
   cd shipai
   ```

2. **Set up environment variables**

   ```bash
   cp .env.example .env
   ```

   Edit `.env` with your credentials:

   ```env
   BOT_TOKEN=your_telegram_bot_token
   API_KEY=your_openai_api_key
   CHANNEL_NAME=@your_channel_username
   MODEL=gpt-4.1-nano
   DATABASE_FILE=articles.db
   ```

3. **Deploy with Docker**
   ```bash
   docker-compose -f compose.dev.yaml up -d
   ```

## 🎮 Bot Commands

| Command          | Description                                |
| ---------------- | ------------------------------------------ |
| `/start`         | Welcome message and bot introduction       |
| `/new_article`   | Add a new article to the posting queue     |
| `/queue`         | View all scheduled articles                |
| `/delete <id>`   | Remove an article from the queue           |
| `/post_now <id>` | Post an article immediately to the channel |
| `/cancel`        | Cancel the current operation               |
| `/help`          | Show available commands                    |

## 📋 Usage Workflow

1. **Start the bot**: Send `/start` to get familiar with available commands
2. **Add content**: Use `/new_article` and send your original text
3. **AI Processing**: The bot automatically enhances your text using OpenAI
4. **Add image** (optional): Upload an image or skip this step
5. **Auto-scheduling**: Your content is automatically scheduled to the next available time slot
6. **Manage queue**: Use `/queue` to view scheduled posts, `/delete` to remove items

## ⚙️ Configuration

### Timezone Configuration

The bot supports timezone configuration through the `TZ` environment variable in docker-compose:

```yaml
environment:
  - TZ=Europe/Moscow # Set your timezone
```

Supported timezone formats:

- `Europe/Moscow` (UTC+3)
- `America/New_York` (EST/EDT)
- `Asia/Tokyo` (JST)
- `UTC` (Universal Time)

## 🛠️ Development

### Local Development Setup

1. **Install Python dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables**

   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Run locally**
   ```bash
   python bot.py
   ```

### Dependencies

- **aiogram** (3.12.0) - Telegram Bot API framework
- **openai** (1.93.0) - OpenAI API client
- **apscheduler** (3.10.4) - Advanced Python Scheduler
- **python-dotenv** (1.1.1) - Environment variable management
