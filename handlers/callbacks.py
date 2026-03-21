from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from database.db import (
    complete_task, get_open_tasks, add_decision, add_task,
    get_agenda, set_agenda_item_status, get_meeting
)
from handlers.start import get_user_group
from handlers.tasks import start_reassign
from keyboards import task_list_kb, confirm_close_kb


from database.db import get_agenda, get_open_tasks, get_closed_tasks, get_active_meeting


async def _inline_shagenda(query, group_id):
    from database.db import get_active_meeting, get_agenda, get_pending_agenda
    STATUS_ICON = {'pending': '⏳', 'discussing': '🔵', 'done': '✅', 'pending_next': '🔄'}
    meeting = get_active_meeting(group_id)
    queue = get_pending_agenda(group_id)
    lines = []

    if queue:
        lines.append("📋 *В очереди (войдут в следующий митинг):*\n")
        for i, item in enumerate(queue, 1):
            lines.append(f"⏳ *{i}. {item['title']}*")
            if item.get('details'):
                lines.append(f"   _{item['details']}_")

    if meeting:
        items = get_agenda(meeting['id'])
        if items:
            if lines:
                lines.append("")
            lines.append(f"🔵 *Повестка митинга «{meeting['title']}»:*\n")
            for i, item in enumerate(items, 1):
                icon = STATUS_ICON.get(item['status'], '⏳')
                suffix = " ← текущий" if item['status'] == 'discussing' and meeting.get('current_agenda_idx') == i - 1 else ""
                lines.append(f"{icon} *{i}. {item['title']}*{suffix}")
                if item.get('details'):
                    lines.append(f"   _{item['details']}_")

    if not lines:
        await query.message.reply_text("📋 *Повестка пуста.* Добавьте /agenda", parse_mode="Markdown")
        return
    await query.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _inline_tasks(query, group_id):
    from database.db import get_open_tasks
    from keyboards import task_list_kb, confirm_close_kb
    tasks = get_open_tasks(group_id)
    if not tasks:
        await query.message.reply_text("📌 *Открытых задач нет.* Создайте /task", parse_mode="Markdown")
        return
    lines = ["📌 *Открытые задачи:*\n"]
    for i, t in enumerate(tasks, 1):
        assignee = t['assignee'] or '—'
        deadline = t['deadline'] or '—'
        lines.append(f"*{i}.* {t['title']}\n   👤 {assignee}  📅 {deadline}")
    await query.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=task_list_kb(tasks))


async def _inline_history(query, group_id):
    from database.db import get_closed_tasks
    tasks = get_closed_tasks(group_id)
    if not tasks:
        await query.message.reply_text("✅ Закрытых задач пока нет.")
        return
    lines = ["✅ *Выполненные задачи:*\n"]
    for i, t in enumerate(tasks, 1):
        assignee = t['assignee'] or '—'
        closed = (t.get('closed_at') or '')[:10]
        lines.append(f"*{i}.* {t['title']}\n   👤 {assignee}  ✓ {closed}")
    await query.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    chat = update.effective_chat

    # ── Cancel conversation ──────────────────────────────────
    if data == "cancel_conv":
        # Clean up any tracked dialog messages
        for key in ('dec_bot_msgs', 'pend_bot_msgs'):
            for msg_id in context.chat_data.get(key, []):
                try:
                    await context.bot.delete_message(update.effective_chat.id, msg_id)
                except Exception:
                    pass
            context.chat_data.pop(key, None)
        try:
            await query.message.delete()
        except Exception:
            pass
        return ConversationHandler.END

    # ── Private chat menu shortcuts ──────────────────────────
    # NB: update.message is None for callback queries — use query.message

    if data == "show_agenda":
        await _inline_shagenda(query, group_id)
        return

    if data == "show_tasks":
        await _inline_tasks(query, group_id)
        return

    if data == "show_history":
        await _inline_history(query, group_id)
        return

    if data == "cmd_agenda":
        await query.message.reply_text(
            "Используйте команду /agenda чтобы добавить пункт повестки."
        )
        return

    if data == "cmd_newmeeting":
        await query.message.reply_text(
            "Команду /newmeeting нужно написать в группе, не здесь."
        )
        return

    # ── Complete task (private) ──────────────────────────────
    if data.startswith("done_task_"):
        task_id = int(data.split("_")[-1])
        from database.db import get_task
        task = get_task(task_id)
        title = task['title'][:40] if task else f"#{task_id}"
        # Save tasks list message_id so we can update it after close
        context.user_data['tasks_msg_id'] = query.message.message_id
        await query.message.reply_text(
            f"❓ Закрыть задачу?\n<b>{title}</b>",
            parse_mode="HTML",
            reply_markup=confirm_close_kb(task_id)
        )
        return

    if data.startswith("confirm_close_"):
        task_id = int(data.split("_")[-1])
        complete_task(task_id, closed_by=user.id)
        group_id = await get_user_group(user.id)
        tasks = get_open_tasks(group_id)

        # Delete confirmation message
        try:
            await query.message.delete()
        except Exception:
            pass

        # Update original tasks list message
        tasks_msg_id = context.user_data.pop('tasks_msg_id', None)
        if tasks_msg_id:
            if tasks:
                def esc(text):
                    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                lines = [f"📌 <b>Открытые задачи ({len(tasks)}):</b>\n"]
                for i, t in enumerate(tasks, 1):
                    assignee = esc(t['assignee'] or '—')
                    deadline = esc(t['deadline'] or '—')
                    lines.append(f"<b>{i}. {esc(t['title'])}</b>")
                    from handlers.tasks import _last_detail
                    last = _last_detail(t.get('details'))
                    if last:
                        lines.append(f"   <i>{esc(last)}</i>")
                    lines.append(f"   👤 {assignee}  📅 {deadline}")
                    lines.append("")
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=tasks_msg_id,
                        text="\n".join(lines),
                        parse_mode="HTML",
                        reply_markup=task_list_kb(tasks)
                    )
                except Exception:
                    pass
            else:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=tasks_msg_id,
                        text="✅ <b>Все задачи закрыты!</b>",
                        parse_mode="HTML",
                        reply_markup=None
                    )
                except Exception:
                    pass
        return

    if data.startswith("cancel_close_"):
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    # ── Reassign task (private) ──────────────────────────────
    if data.startswith("reassign_task_"):
        task_id = int(data.split("_")[-1])
        return await start_reassign(update, context, task_id)

    # ── Assignee picker (private task creation) ─────────────
    if data.startswith("assignee_") and data != "assignee_skip":
        # format: assignee_{user_id}_{name}
        parts = data.split("_", 2)
        assignee_name = parts[2] if len(parts) > 2 else "—"
        context.user_data['task_assignee'] = assignee_name
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            f"👤 Ответственный: *{assignee_name}*\n\n*Шаг 4/4* — Укажите *срок выполнения*\n_(например: 25.12.2025 или «-»)_:",
            parse_mode="Markdown",
            reply_markup=__import__('keyboards').cancel_kb()
        )
        from handlers.tasks import TASK_DEADLINE
        # Manually set conversation state via updating context
        # PTB stores state in context — we need to return TASK_DEADLINE
        # This is handled by making assignee_kb callbacks go through a ConversationHandler
        return TASK_DEADLINE

    if data == "assignee_skip":
        context.user_data['task_assignee'] = None
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            "*Шаг 4/4* — Укажите *срок выполнения*\n_(например: 25.12.2025 или «-»)_:",
            parse_mode="Markdown",
            reply_markup=__import__('keyboards').cancel_kb()
        )
        from handlers.tasks import TASK_DEADLINE
        return TASK_DEADLINE

    # dec_done_ / dec_todo_ are handled by decision_conv (DEC_TYPE state).
    # This fallback fires only if the bot restarted and conversation state was lost.
    if data.startswith("dec_done_") or data.startswith("dec_todo_"):
        await query.message.reply_text("⚠️ Данные устарели. Начните /decision заново.")
        return
