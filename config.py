from dotenv import load_dotenv
load_dotenv()
import os

# Токен бота от @BotFather
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# ID группы — узнать можно через @userinfobot или из логов бота
# Пример: -1001234567890
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))

# Путь к базе данных
DB_PATH = os.path.join(os.path.dirname(__file__), "meetings.db")

# Comma-separated user IDs allowed to use /backup and /restore when BACKUP_OPERATOR=admin
_raw = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in _raw.split(",") if x.strip().isdigit()]

# "admin" — only ADMIN_IDS can use /backup and /restore
# "all"   — any registered user in private chat can use them
BACKUP_OPERATOR = os.environ.get("BACKUP_OPERATOR", "admin").lower()

# PDF report title
PDF_TITLE = os.environ.get("PDF_TITLE", "Delphi IT Meeting Agenda")

# ── Email report settings ────────────────────────────────────
SENDMAIL  = os.environ.get("SENDMAIL", "false").lower() == "true"
SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
SMTP_FROM = os.environ.get("SMTP_FROM", "meetingbot@localhost")
SMTP_TO   = os.environ.get("SMTP_TO", "")  # comma-separated recipients
