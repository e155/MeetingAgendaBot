from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from database.db import (
    get_active_meeting, add_agenda_item, get_agenda,
    get_pending_agenda, add_pending_agenda_item,
    get_unresolved_from_last_meeting
)
from handlers.start import ensure_private, auto_register
from keyboards import cancel_kb

AG_TITLE, AG_DETAILS = range(2)


async def cmd_agenda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update):
        return ConversationHandler.END

    user = update.effective_user
    group_id = await auto_register(update, context)
    meeting = get_active_meeting(group_id)

    context.user_data['ag_meeting_id'] = meeting['id'] if meeting else None
    context.user_data['ag_group_id'] = group_id

    hint = (f"Будет добавлен в текущий митинг *«{meeting['title']}»*" if meeting
            else "Митинга нет — пункт попадёт в очередь и войдёт в повестку при старте следующего митинга")

    await update.message.reply_text(
        f"📋 *Шаг 1/2* — Введите *название* пункта повестки:\n\n_{hint}_",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return AG_TITLE


async def ag_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ag_title'] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Название: *{context.user_data['ag_title']}*\n\n"
        f"📋 *Шаг 2/2* — Добавьте *детали* (или «-» чтобы пропустить):",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return AG_DETAILS


async def ag_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    details = update.message.text.strip()
    details = None if details == '-' else details
    title = context.user_data['ag_title']
    meeting_id = context.user_data.get('ag_meeting_id')
    group_id = context.user_data.get('ag_group_id')

    if meeting_id:
        add_agenda_item(meeting_id, title, details, user.id)
        items = get_agenda(meeting_id)
        dest_text = "добавлен в повестку текущего митинга"
        count_text = f"Всего в повестке: {len(items)} пунктов."
    else:
        add_pending_agenda_item(group_id, title, details, user.id)
        queue = get_pending_agenda(group_id)
        dest_text = "добавлен в очередь — войдёт в повестку при старте митинга"
        count_text = f"В очереди: {len(queue)} пунктов."

    author = user.full_name or user.username or f"id{user.id}"
    await update.message.reply_text(
        f"✅ Пункт *{title}* {dest_text}!\n"
        + (f"_{details}_\n" if details else "")
        + f"👤 Автор: {author}\n"
        + f"\n{count_text}",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def cmd_shagenda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update):
        return

    group_id = await auto_register(update, context)
    meeting = get_active_meeting(group_id)
    queue = get_pending_agenda(group_id)

    STATUS_ICON = {'pending': '⏳', 'discussing': '🔵', 'done': '✅', 'pending_next': '🔄'}
    lines = []

    # Section 1: unresolved from last meeting (only when no active meeting)
    if not meeting:
        unresolved = get_unresolved_from_last_meeting(group_id)
        if unresolved:
            lines.append("🔄 *Нерешённые пункты прошлого митинга:*\n")
            for i, item in enumerate(unresolved, 1):
                icon = STATUS_ICON.get(item['status'], '🔄')
                lines.append(f"{icon} *{i}. {item['title']}*")
                if item.get('details'):
                    lines.append(f"   _{item['details']}_")
                if item.get('added_by_name'):
                    lines.append(f"   👤 {item['added_by_name']}")

    # Section 2: pending queue
    if queue:
        if lines:
            lines.append("")
        lines.append("📋 *В очереди (войдут в следующий митинг):*\n")
        for i, item in enumerate(queue, 1):
            lines.append(f"⏳ *{i}. {item['title']}*")
            if item.get('details'):
                lines.append(f"   _{item['details']}_")
            if item.get('added_by_name'):
                lines.append(f"   👤 {item['added_by_name']}")

    # Section 3: active meeting agenda
    if meeting:
        items = get_agenda(meeting['id'])
        if items:
            if lines:
                lines.append("")
            lines.append(f"🔵 *Повестка митинга «{meeting['title']}»:*\n")
            for i, item in enumerate(items, 1):
                icon = STATUS_ICON.get(item['status'], '⏳')
                suffix = (" ← текущий" if item['status'] == 'discussing'
                          and meeting.get('current_agenda_idx') == i - 1 else "")
                lines.append(f"{icon} *{i}. {item['title']}*{suffix}")
                if item.get('details'):
                    lines.append(f"   _{item['details']}_")
                if item.get('added_by_name'):
                    lines.append(f"   👤 {item['added_by_name']}")

    if not lines:
        await update.message.reply_text(
            "📋 *Повестка пуста.*\nДобавьте пункты командой /agenda",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
