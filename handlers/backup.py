import os
import shutil
import sys
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import DB_PATH, ADMIN_IDS, BACKUP_OPERATOR
from handlers.start import ensure_private

# Staging path — downloaded file waits here until confirmed
RESTORE_STAGING = DB_PATH + '.restore_staging'


def _can_use_backup(user_id: int) -> bool:
    if BACKUP_OPERATOR == "all":
        return True
    return user_id in ADMIN_IDS


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update):
        return

    if not _can_use_backup(update.effective_user.id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return

    if not os.path.exists(DB_PATH):
        await update.message.reply_text("❌ База данных не найдена.")
        return

    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"meetings_backup_{timestamp}.db"
        with open(DB_PATH, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption=f"💾 Backup: {timestamp}"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def cmd_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update):
        return

    if not _can_use_backup(update.effective_user.id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return

    await update.message.reply_text(
        "📂 Отправьте файл `.db` для восстановления базы данных.",
        parse_mode="Markdown"
    )
    context.user_data['awaiting_restore'] = True


async def handle_restore_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1: receive file, save to staging, ask confirmation."""
    if not context.user_data.get('awaiting_restore'):
        return

    if not _can_use_backup(update.effective_user.id):
        return

    doc = update.message.document
    if not doc or not doc.file_name.endswith('.db'):
        await update.message.reply_text("❌ Нужен файл с расширением `.db`.")
        return

    context.user_data.pop('awaiting_restore', None)

    try:
        # Download directly to staging path on disk
        file = await context.bot.get_file(doc.file_id)
        await file.download_to_drive(RESTORE_STAGING)

        # Validate SQLite
        with open(RESTORE_STAGING, 'rb') as f:
            header = f.read(16)
        if not header.startswith(b'SQLite format 3'):
            os.unlink(RESTORE_STAGING)
            await update.message.reply_text("❌ Файл не является базой SQLite.")
            return

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Применить и перезапустить", callback_data="restore_apply"),
            InlineKeyboardButton("❌ Отмена", callback_data="restore_cancel"),
        ]])
        await update.message.reply_text(
            f"📂 Файл *{doc.file_name}* получен и проверен.\n\n"
            f"⚠️ Текущая база будет заменена. Применить?",
            parse_mode="Markdown",
            reply_markup=kb
        )
    except Exception as e:
        if os.path.exists(RESTORE_STAGING):
            os.unlink(RESTORE_STAGING)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_restart_callback(update, context):
    """Step 2: apply or cancel."""
    query = update.callback_query
    await query.answer()

    if query.data == "restore_apply":
        if not os.path.exists(RESTORE_STAGING):
            await query.message.edit_text("❌ Файл не найден. Начните заново через /restore.")
            return
        try:
            # Backup current DB
            if os.path.exists(DB_PATH):
                shutil.copy2(DB_PATH, DB_PATH + '.bak')
            # Apply staging
            shutil.copy2(RESTORE_STAGING, DB_PATH)
            os.unlink(RESTORE_STAGING)
        except Exception as e:
            await query.message.edit_text(f"❌ Ошибка при замене базы: {e}")
            return

        await query.message.edit_text("✅ База восстановлена. Перезапускаю бота...")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    elif query.data == "restore_cancel":
        if os.path.exists(RESTORE_STAGING):
            os.unlink(RESTORE_STAGING)
        await query.message.edit_text("❌ Восстановление отменено. База не изменена.")
