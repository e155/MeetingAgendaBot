from telegram import Update
from telegram.ext import ContextTypes
from config import GROUP_ID
from database.db import upsert_user, get_user
from keyboards import main_private_kb


def _name(user):
    return user.full_name or user.username or f"user_{user.id}"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Only in private chat — registers user."""
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    upsert_user(user.id, user.username or "", _name(user), GROUP_ID)

    admin_cmds = ""
    from config import ADMIN_IDS, BACKUP_OPERATOR
    user_can_backup = BACKUP_OPERATOR == "all" or user.id in ADMIN_IDS
    if user_can_backup:
        admin_cmds = "\n\n*Администрирование:*\n• /backup — скачать резервную копию БД\n• /restore — восстановить БД из файла"

    await update.message.reply_text(
        f"👋 Привет, *{_name(user)}*!\n\n"
        f"*Личный диалог* — подготовка к митингу:\n"
        f"• /agenda — добавить пункт в повестку\n"
        f"• /shagenda — посмотреть повестку и очередь\n"
        f"• /task — создать задачу (4 шага)\n"
        f"• /tasks — открытые задачи с кнопками\n"
        f"• /history — последние 20 выполненных задач\n"
        f"{admin_cmds}\n\n"
        f"*В группе* — ведение митинга:\n"
        f"• /newmeeting — начать митинг, опубликовать повестку\n"
        f"• /next — следующий пункт (циклически, без закрытия)\n"
        f"• /decision — зафиксировать решение → Done или ToDo\n"
        f"• /pending — отложить пункт до следующего митинга\n"
        f"• /summary — завершить митинг + PDF-протокол\n\n"
        f"{'✅ Группа подключена.' if GROUP_ID else '⚠️ GROUP_ID не настроен.'}",
        parse_mode="Markdown"
    )


async def get_user_group(user_id: int) -> int:
    """Always returns a valid group_id, never 0."""
    u = get_user(user_id)
    if u and u.get("group_id") and u["group_id"] != 0:
        return u["group_id"]
    return GROUP_ID


async def auto_register(update, context) -> int:
    """Ensure user is registered with GROUP_ID. Returns group_id."""
    user = update.effective_user
    group_id = GROUP_ID
    upsert_user(user.id, user.username or "", _name(user), group_id)
    return group_id


async def ensure_private(update: Update) -> bool:
    if update.effective_chat.type == "private":
        return True
    user = update.effective_user
    try:
        await update.message.reply_text(
            f"@{user.username or user.first_name}, эта команда работает в личном диалоге с ботом."
        )
    except Exception:
        pass
    return False
