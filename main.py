import os
import logging
from typing import Optional, List, Literal

from dotenv import load_dotenv
import anthropic
from notion_client import Client as NotionClient
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)
from pydantic import BaseModel

from database import init_db, get_user, save_user, delete_user

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Conversation states
NOTION_TOKEN_STATE, DATABASE_ID_STATE = range(2)

SETUP_INSTRUCTIONS = """
<b>Step 2: Set up your Notion database</b>

1. Create a new full-page <b>database</b> in Notion
2. Add these <b>Text</b> properties:
   • Met At
   • Company
   • Role
   • Interests
   • Family
   • Notes
3. Click <b>···</b> → <b>Connections</b> → add your integration
4. Copy the database ID from the URL:
   <code>notion.so/[THIS-PART]?v=...</code>

Send me the database ID 👇
"""


class Contact(BaseModel):
    name: str
    met_at: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    interests: Optional[List[str]] = None
    family: Optional[str] = None
    notes: Optional[str] = None


class Intent(BaseModel):
    type: Literal["save", "search"]


class SearchMatch(BaseModel):
    name: str
    summary: str
    reason: str


class SearchResponse(BaseModel):
    matches: List[SearchMatch]
    no_match_message: Optional[str] = None


def classify_intent(text: str) -> str:
    response = claude.messages.parse(
        model="claude-opus-4-6",
        max_tokens=100,
        system=(
            "Classify the user's message as either 'save' or 'search'.\n"
            "'save' means they are describing someone they just met or want to record.\n"
            "'search' means they are looking for someone already saved (e.g. asking who, find someone, recall a person).\n"
            "Return only the JSON with the classification."
        ),
        messages=[{"role": "user", "content": text}],
        output_format=Intent,
    )
    return response.parsed_output.type


def fetch_all_contacts(notion_token: str, database_id: str) -> list[dict]:
    # Use the stable 2022-06-28 API version so /databases/{id}/query is available
    # regardless of which notion-client version is installed.
    notion = NotionClient(auth=notion_token, notion_version="2022-06-28")
    contacts = []
    cursor = None

    while True:
        body = {"start_cursor": cursor} if cursor else {}
        result = notion.request(
            path=f"databases/{database_id}/query",
            method="POST",
            body=body,
        )

        for page in result["results"]:
            props = page["properties"]

            def get_title(prop):
                parts = prop.get("title", [])
                return "".join(p["plain_text"] for p in parts) if parts else None

            def get_rich_text(prop):
                parts = prop.get("rich_text", [])
                return "".join(p["plain_text"] for p in parts) if parts else None

            contacts.append({
                "Name": get_title(props.get("Name", {})),
                "Met At": get_rich_text(props.get("Met At", {})),
                "Company": get_rich_text(props.get("Company", {})),
                "Role": get_rich_text(props.get("Role", {})),
                "Interests": get_rich_text(props.get("Interests", {})),
                "Family": get_rich_text(props.get("Family", {})),
                "Notes": get_rich_text(props.get("Notes", {})),
            })

        if result.get("has_more"):
            cursor = result["next_cursor"]
        else:
            break

    return contacts


def search_contacts(query: str, notion_token: str, database_id: str) -> str:
    contacts = fetch_all_contacts(notion_token, database_id)

    if not contacts:
        return "Your contact list is empty. Send me a description of someone you met to get started!"

    contacts_text = "\n\n".join(
        "\n".join(f"{k}: {v}" for k, v in c.items() if v)
        for c in contacts
    )

    response = claude.messages.parse(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=(
            "You are a personal contact search assistant. Given a list of saved contacts and a search query, "
            "return the most relevant matches. For each match, provide a one-line summary of who they are and "
            "why they match the query. If no contacts match, set no_match_message to a friendly message instead."
        ),
        messages=[{
            "role": "user",
            "content": f"Contacts:\n{contacts_text}\n\nSearch query: {query}",
        }],
        output_format=SearchResponse,
    )

    result = response.parsed_output

    if result.no_match_message:
        return result.no_match_message

    lines = ["<b>Here's who I found:</b>\n"]
    for match in result.matches:
        lines.append(f"<b>{match.name}</b>")
        lines.append(f"{match.summary}")
        lines.append(f"<i>Why: {match.reason}</i>\n")

    return "\n".join(lines)


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


def save_to_notion(contact: Contact, notion_token: str, database_id: str) -> str:
    notion = NotionClient(auth=notion_token)

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
        parent={"database_id": database_id},
        properties=properties,
    )
    return page["url"]


# --- Setup conversation handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            "You're all set! Send me a description of someone you met and I'll save them to your Notion.\n\n"
            "Use /setup to reconnect Notion or /reset to start over."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Welcome to <b>People Tracker</b>!\n\n"
        "<b>Step 1: Create a Notion Integration</b>\n\n"
        "1. Go to <a href=\"https://www.notion.so/my-integrations\">notion.so/my-integrations</a>\n"
        "2. Go to Internal Integrations and Click <b>New integration</b>\n"
        "3. Name it anything (e.g. \"People Tracker\")\n"
        "4. Select <b>No User Information</b> in User Capabilities\n"
        "5. Press <b>Save</b>\n\n"
        "5. Copy the <b>Integration Token</b>\n\n"
        "Send me the token 👇",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return NOTION_TOKEN_STATE


async def setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Let's reconnect your Notion.\n\n"
        "<b>Step 1:</b> Go to <a href=\"https://www.notion.so/my-integrations\">notion.so/my-integrations</a> "
        "and copy your integration token.\n\n"
        "Send me the token 👇",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return NOTION_TOKEN_STATE


async def receive_notion_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()

    if not (token.startswith("ntn_") or token.startswith("secret_")):
        await update.message.reply_text(
            "❌ That doesn't look like a valid Notion token.\n"
            "It should start with <code>ntn_</code> or <code>secret_</code>.\n\n"
            "Try again 👇",
            parse_mode="HTML",
        )
        return NOTION_TOKEN_STATE

    context.user_data["notion_token"] = token
    await update.message.reply_text(SETUP_INSTRUCTIONS, parse_mode="HTML")
    return DATABASE_ID_STATE


async def receive_database_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    # Strip any accidental URL or query string the user may have pasted
    database_id = raw.split("?")[0].split("/")[-1].replace("-", "")

    notion_token = context.user_data.get("notion_token")

    try:
        notion = NotionClient(auth=notion_token)
        notion.databases.retrieve(database_id)
    except Exception:
        await update.message.reply_text(
            "❌ Couldn't connect to that database. Make sure:\n\n"
            "1. The database ID is correct\n"
            "2. You added your integration via <b>Connections</b> on the database page\n\n"
            "Try sending the ID again 👇",
            parse_mode="HTML",
        )
        return DATABASE_ID_STATE

    save_user(update.effective_user.id, notion_token, database_id)
    await update.message.reply_text(
        "✅ <b>All connected!</b>\n\n"
        "Send me a description of someone you met and I'll save them to your Notion.\n\n"
        "<i>Example: Met Sarah at John's dinner. Works at Stripe as a PM. Into rock climbing. Has a dog named Mochi.</i>",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Setup cancelled. Run /start whenever you're ready.")
    return ConversationHandler.END


# --- Main contact handler ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please run /start to connect your Notion account first.")
        return

    text = update.message.text
    intent = classify_intent(text)

    if intent == "search":
        await update.message.reply_text("🔍 Searching...")
        try:
            result = search_contacts(text, user["notion_token"], user["database_id"])
            await update.message.reply_text(result, parse_mode="HTML")
        except Exception as e:
            logger.exception("Error searching contacts")
            await update.message.reply_text(
                f"❌ Something went wrong while searching: {str(e)}\n\n"
                "If your Notion token has changed, run /setup to reconnect."
            )
    else:
        await update.message.reply_text("⏳ Processing...")
        try:
            contact = extract_contact(text)
            url = save_to_notion(contact, user["notion_token"], user["database_id"])

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
            await update.message.reply_text(
                f"❌ Something went wrong: {str(e)}\n\n"
                "If your Notion token has changed, run /setup to reconnect."
            )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    delete_user(update.effective_user.id)
    await update.message.reply_text("Your account has been reset. Run /start to reconnect your Notion.")


def main():
    init_db()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("setup", setup_command),
        ],
        states={
            NOTION_TOKEN_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_notion_token)],
            DATABASE_ID_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_database_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
