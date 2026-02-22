import os
import logging
from typing import Optional, List

from dotenv import load_dotenv
import anthropic
from notion_client import Client as NotionClient
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
notion = NotionClient(auth=os.getenv("NOTION_TOKEN"))
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


class Contact(BaseModel):
    name: str
    met_at: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    interests: Optional[List[str]] = None
    family: Optional[str] = None
    notes: Optional[str] = None


def extract_contact(text: str) -> Contact:
    response = claude.messages.parse(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=(
            "Extract structured contact information from the user's casual description of someone they met. "
            "Pull out the person's name, where they met (event/place), company, job role, interests (as a list), "
            "family details (spouse, kids, pets, etc.), and any other notes. "
            "If a field is not mentioned, leave it null."
        ),
        messages=[{"role": "user", "content": text}],
        output_format=Contact,
    )
    return response.parsed_output


def save_to_notion(contact: Contact) -> str:
    properties = {
        "Name": {"title": [{"text": {"content": contact.name}}]},
    }

    if contact.met_at:
        properties["Met At"] = {"rich_text": [{"text": {"content": contact.met_at}}]}
    if contact.company:
        properties["Company"] = {"rich_text": [{"text": {"content": contact.company}}]}
    if contact.role:
        properties["Role"] = {"rich_text": [{"text": {"content": contact.role}}]}
    if contact.interests:
        properties["Interests"] = {"rich_text": [{"text": {"content": ", ".join(contact.interests)}}]}
    if contact.family:
        properties["Family"] = {"rich_text": [{"text": {"content": contact.family}}]}
    if contact.notes:
        properties["Notes"] = {"rich_text": [{"text": {"content": contact.notes}}]}

    page = notion.pages.create(
        parent={"database_id": NOTION_DB_ID},
        properties=properties,
    )
    return page["url"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! Send me a description of someone you met and I'll save them to Notion.\n\n"
        "<b>Example:</b>\n"
        "<i>Met Sarah at John's dinner. Works at Stripe as a PM. Into rock climbing and ceramics. Has a dog named Mochi.</i>",
        parse_mode="HTML",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    await update.message.reply_text("⏳ Processing...")

    try:
        contact = extract_contact(text)
        url = save_to_notion(contact)

        lines = [f"✅ Saved <b>{contact.name}</b>"]
        if contact.met_at:
            lines.append(f"📍 Met at: {contact.met_at}")
        if contact.role or contact.company:
            work = " · ".join(filter(None, [contact.role, contact.company]))
            lines.append(f"💼 Work: {work}")
        if contact.interests:
            lines.append(f"🎯 Interests: {', '.join(contact.interests)}")
        if contact.family:
            lines.append(f"👨‍👩‍👧 Family: {contact.family}")
        if contact.notes:
            lines.append(f"📝 Notes: {contact.notes}")
        lines.append(f'\n<a href="{url}">View in Notion →</a>')

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        logger.exception("Error processing message")
        await update.message.reply_text(f"❌ Something went wrong: {str(e)}")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
