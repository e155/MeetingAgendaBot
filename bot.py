import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ContextTypes
)
from config import BOT_TOKEN
from database.db import init_db
from handlers.start import cmd_start
from handlers.backup import cmd_backup, cmd_restore, handle_restore_file, handle_restart_callback
from handlers.agenda import cmd_agenda, ag_title, ag_details, cmd_shagenda, AG_TITLE, AG_DETAILS
from handlers.tasks import (
    cmd_task, task_title_step, task_details_step, task_assignee_step, task_assignee_cb, task_deadline_step,
    cmd_tasks, cmd_history,
    reassign_title, reassign_details, reassign_assignee, reassign_assignee_cb, reassign_deadline,
    TASK_TITLE, TASK_DETAILS, TASK_ASSIGNEE, TASK_DEADLINE,
    REASSIGN_TITLE, REASSIGN_DETAILS, REASSIGN_ASSIGNEE, REASSIGN_DEADLINE
)
from handlers.group_meeting import (
    cmd_newmeeting, cmd_next, cmd_decision, dec_text_step, dec_resp_step,
    cmd_pending, pend_note_step, pend_resp_step, cmd_summary,
    DEC_TEXT, DEC_RESP, PEND_NOTE, PEND_RESP
)
from handlers.callbacks import callback_handler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


GROUP_FILTER = filters.ChatType.GROUPS
PRIVATE_FILTER = filters.ChatType.PRIVATE


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан!")

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Private: /agenda (2 steps) ──────────────────────────
    agenda_conv = ConversationHandler(
        entry_points=[CommandHandler("agenda", cmd_agenda, filters=PRIVATE_FILTER)],
        states={
            AG_TITLE:   [MessageHandler(PRIVATE_FILTER & filters.TEXT & ~filters.COMMAND, ag_title)],
            AG_DETAILS: [MessageHandler(PRIVATE_FILTER & filters.TEXT & ~filters.COMMAND, ag_details)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            CallbackQueryHandler(cancel_conv, pattern="^cancel_conv$"),
        ],
        per_chat=True, per_user=True,
    )

    # ── Private: /task (4 steps) ────────────────────────────
    task_conv = ConversationHandler(
        entry_points=[CommandHandler("task", cmd_task, filters=PRIVATE_FILTER)],
        states={
            TASK_TITLE:    [MessageHandler(PRIVATE_FILTER & filters.TEXT & ~filters.COMMAND, task_title_step)],
            TASK_DETAILS:  [MessageHandler(PRIVATE_FILTER & filters.TEXT & ~filters.COMMAND, task_details_step)],
            TASK_ASSIGNEE: [
                MessageHandler(PRIVATE_FILTER & filters.TEXT & ~filters.COMMAND, task_assignee_step),
                CallbackQueryHandler(task_assignee_cb, pattern="^assignee_"),
            ],
            TASK_DEADLINE: [MessageHandler(PRIVATE_FILTER & filters.TEXT & ~filters.COMMAND, task_deadline_step)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            CallbackQueryHandler(cancel_conv, pattern="^cancel_conv$"),
        ],
        per_chat=True, per_user=True,
    )

    # ── Private: reassign task (4 steps, starts from callback) ─
    reassign_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^reassign_task_")],
        states={
            REASSIGN_TITLE:    [MessageHandler(PRIVATE_FILTER & filters.TEXT & ~filters.COMMAND, reassign_title)],
            REASSIGN_DETAILS:  [MessageHandler(PRIVATE_FILTER & filters.TEXT & ~filters.COMMAND, reassign_details)],
            REASSIGN_ASSIGNEE: [
                MessageHandler(PRIVATE_FILTER & filters.TEXT & ~filters.COMMAND, reassign_assignee),
                CallbackQueryHandler(reassign_assignee_cb, pattern="^assignee_"),
            ],
            REASSIGN_DEADLINE: [MessageHandler(PRIVATE_FILTER & filters.TEXT & ~filters.COMMAND, reassign_deadline)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            CallbackQueryHandler(cancel_conv, pattern="^cancel_conv$"),
        ],
        per_chat=True, per_user=True,
    )

    # ── Group: /decision (2 steps + callback) ───────────────
    decision_conv = ConversationHandler(
        entry_points=[CommandHandler("decision", cmd_decision, filters=GROUP_FILTER)],
        states={
            DEC_TEXT: [MessageHandler(GROUP_FILTER & filters.TEXT & ~filters.COMMAND, dec_text_step)],
            DEC_RESP: [MessageHandler(GROUP_FILTER & filters.TEXT & ~filters.COMMAND, dec_resp_step)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            CallbackQueryHandler(cancel_conv, pattern="^cancel_conv$"),
        ],
        per_chat=True, per_user=False,  # group-scoped, any user can continue
    )

    # ── Group: /pending (2 steps) ───────────────────────────
    pending_conv = ConversationHandler(
        entry_points=[CommandHandler("pending", cmd_pending, filters=GROUP_FILTER)],
        states={
            PEND_NOTE: [MessageHandler(GROUP_FILTER & filters.TEXT & ~filters.COMMAND, pend_note_step)],
            PEND_RESP: [MessageHandler(GROUP_FILTER & filters.TEXT & ~filters.COMMAND, pend_resp_step)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            CallbackQueryHandler(cancel_conv, pattern="^cancel_conv$"),
        ],
        per_chat=True, per_user=False,
    )

    # ── Simple commands ──────────────────────────────────────
    app.add_handler(CommandHandler("start", cmd_start, filters=PRIVATE_FILTER))
    app.add_handler(CommandHandler("backup", cmd_backup, filters=PRIVATE_FILTER))
    app.add_handler(CommandHandler("restore", cmd_restore, filters=PRIVATE_FILTER))
    app.add_handler(MessageHandler(PRIVATE_FILTER & filters.Document.ALL, handle_restore_file))
    app.add_handler(CallbackQueryHandler(handle_restart_callback, pattern="^restore_"))
    app.add_handler(CommandHandler("shagenda", cmd_shagenda, filters=PRIVATE_FILTER))
    app.add_handler(CommandHandler("tasks", cmd_tasks, filters=PRIVATE_FILTER))
    app.add_handler(CommandHandler("history", cmd_history, filters=PRIVATE_FILTER))

    app.add_handler(CommandHandler("newmeeting", cmd_newmeeting, filters=GROUP_FILTER))
    app.add_handler(CommandHandler("next", cmd_next, filters=GROUP_FILTER))
    app.add_handler(CommandHandler("summary", cmd_summary, filters=GROUP_FILTER))

    # ── Conversation handlers ────────────────────────────────
    app.add_handler(agenda_conv)
    app.add_handler(task_conv)
    app.add_handler(reassign_conv)
    app.add_handler(decision_conv)
    app.add_handler(pending_conv)

    # ── Callbacks (catch-all, must be last) ─────────────────
    app.add_handler(CallbackQueryHandler(callback_handler))

    async def track_group_members(update, context):
        """Auto-save any user who writes in the group."""
        if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
            user = update.effective_user
            if user and not user.is_bot:
                from database.db import upsert_user
                upsert_user(user.id, user.username or "", user.full_name or "", update.effective_chat.id)

    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.ALL, track_group_members), group=99)

    async def error_handler(update, context):
        import logging
        logging.getLogger(__name__).error("Exception:", exc_info=context.error)

    app.add_error_handler(error_handler)

    async def cmd_chatid(update, context):
        await update.message.reply_text(f"Chat ID: `{update.effective_chat.id}`", parse_mode="Markdown")
    app.add_handler(CommandHandler("chatid", cmd_chatid))
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
