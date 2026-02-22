# People Tracker

A Telegram bot that helps you remember people you meet. Send a casual description of someone you met, and the bot extracts their details using Claude AI and saves them to a Notion database.

## How It Works

```
You (Telegram message)
        ↓
   Telegram Bot
        ↓
   Claude AI  →  extracts name, work, interests, family, etc.
        ↓
   Notion Database  →  saves a structured contact card
```

**Example input:**
> Met Sarah at John's dinner. Works at Stripe as a PM. Into rock climbing and ceramics. Has a dog named Mochi.

**Saved to Notion as:**

| Field | Value |
|---|---|
| Name | Sarah |
| Met At | John's dinner |
| Role | PM |
| Company | Stripe |
| Interests | Rock climbing, ceramics |
| Family | Has a dog named Mochi |

---

## Setup

### Prerequisites
- Python 3.9+
- A [Telegram](https://telegram.org) account
- A [Notion](https://notion.so) account
- An [Anthropic](https://console.anthropic.com) account

### 1. Clone the repo

```bash
git clone https://github.com/your-username/people-tracker.git
cd people-tracker
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Get your API keys

**Telegram Bot Token**
1. Message `@BotFather` on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the bot token

**Notion Integration Token + Database ID**
1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → New integration
2. Name it `People Tracker`, set type to **Internal**, copy the token
3. Create a Notion database with these **Text** properties:
   - `Met At`, `Company`, `Role`, `Interests`, `Family`, `Notes`
4. Open the database → `...` → **Add connections** → select your integration
5. Copy the database ID from the URL:
   ```
   https://www.notion.so/YOUR-DATABASE-ID?v=...
                          ^^^^^^^^^^^^^^^^
   ```

**Anthropic API Key**
1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```
ANTHROPIC_API_KEY=your_anthropic_api_key
NOTION_TOKEN=your_notion_integration_token
NOTION_DATABASE_ID=your_notion_database_id
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
```

### 5. Run locally

```bash
python main.py
```

Open Telegram, find your bot, and send `/start`.

---

## Deployment (Railway)

To keep the bot running 24/7:

1. Push this repo to GitHub (make sure `.env` is in `.gitignore`)
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Select this repo
4. Add your 4 environment variables in the **Variables** tab
5. Railway will detect the `Procfile` and start the bot automatically

Railway's free tier (~$5/month credit) is more than enough for this bot.

---

## Tech Stack

| Component | Technology |
|---|---|
| Bot framework | [python-telegram-bot](https://python-telegram-bot.org) |
| AI extraction | [Claude claude-opus-4-6](https://anthropic.com) |
| Database | [Notion API](https://developers.notion.com) |
| Deployment | [Railway](https://railway.app) |

---

## Project Structure

```
people-tracker/
├── main.py          # Bot logic, Claude extraction, Notion saving
├── requirements.txt # Python dependencies
├── Procfile         # Railway start command
├── .env.example     # Environment variable template
└── .gitignore       # Excludes .env from git
```
