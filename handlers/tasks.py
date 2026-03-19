from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from database.db import (
    get_active_meeting, add_task, get_open_tasks,
    get_closed_tasks, complete_task, get_task, update_task
)
from handlers.start import ensure_private, get_user_group
from keyboards import task_list_kb, cancel_kb, assignee_kb, name

TASK_TITLE, TASK_DETAILS, TASK_ASSIGNEE, TASK_DEADLINE = range(4)
REASSIGN_TITLE, REASSIGN_DETAILS, REASSIGN_ASSIGNEE, REASSIGN_DEADLINE = range(10, 14)

def _last_detail(details):
    """Return only the most recent entry from details history."""
    if not details:
        return None
    parts = details.split('\n--- ')
    last = parts[-1].strip()
    if '---\n' in last:
        last = last.split('---\n', 1)[-1].strip()
    return last or None



def _task_summary(t):
    assignee = t.get('assignee') or '—'
    deadline = t.get('deadline') or '—'
    details = t.get('details')
    lines = [f"📌 *{t['title']}*"]
    if details:
        lines.append(f"_{details}_")
    lines.append(f"👤 {assignee}  |  📅 {deadline}")
    return "\n".join(lines)


# ── Create task ─────────────────────────────────────────────

async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update):
        return ConversationHandler.END

    user = update.effective_user
    group_id = await get_user_group(user.id)
    meeting = get_active_meeting(group_id)

    context.user_data['task_group_id'] = group_id
    context.user_data['task_meeting_id'] = meeting['id'] if meeting else None
    context.user_data['task_created_by'] = user.id

    await update.message.reply_text(
        "📌 *Создание задачи*\n\n*Шаг 1/4* — Введите *название* задачи:",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return TASK_TITLE


async def task_title_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['task_title'] = update.message.text.strip()
    await update.message.reply_text(
        f"*Шаг 2/4* — Введите *детали* задачи\n_(или «-» чтобы пропустить)_:",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return TASK_DETAILS


async def task_details_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data['task_details'] = None if text == '-' else text

    from database.db import get_group_users
    group_id = context.user_data.get('task_group_id')
    users = get_group_users(group_id) if group_id else []

    if users:
        await update.message.reply_text(
            "*Шаг 3/4* — Выберите *ответственного* или введите имя вручную:",
            parse_mode="Markdown",
            reply_markup=assignee_kb(users)
        )
    else:
        await update.message.reply_text(
            "*Шаг 3/4* — Укажите *ответственного* (имя или @username, или «-»):",
            parse_mode="Markdown",
            reply_markup=cancel_kb()
        )
    return TASK_ASSIGNEE


async def task_assignee_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data['task_assignee'] = None if text == '-' else text
    await update.message.reply_text(
        "*Шаг 4/4* — Укажите *срок выполнения*\n_(например: 25.12.2025 или «-»)_:",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return TASK_DEADLINE


async def task_assignee_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle assignee selection from inline keyboard inside task_conv."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "assignee_skip":
        context.user_data['task_assignee'] = None
    elif data.startswith("assignee_"):
        parts = data.split("_", 2)
        context.user_data['task_assignee'] = parts[2] if len(parts) > 2 else None

    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await query.message.reply_text(
        "*Шаг 4/4* — Укажите *срок выполнения*\n_(например: 25.12.2025 или «-»)_:",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return TASK_DEADLINE


async def task_deadline_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    deadline = None if text == '-' else text

    ud = context.user_data
    task_id = add_task(
        group_id=ud['task_group_id'],
        meeting_id=ud.get('task_meeting_id'),
        title=ud['task_title'],
        details=ud.get('task_details'),
        assignee=ud.get('task_assignee'),
        deadline=deadline,
        created_by=ud['task_created_by']
    )

    task = get_task(task_id)
    await update.message.reply_text(
        f"✅ *Задача создана!*\n\n{_task_summary(task)}",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ── List open tasks ─────────────────────────────────────────

async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update):
        return

    user = update.effective_user
    group_id = await get_user_group(user.id)
    tasks = get_open_tasks(group_id)

    if not tasks:
        await update.message.reply_text(
            "📌 *Открытых задач нет.*\nСоздайте командой /task",
            parse_mode="Markdown"
        )
        return

    def esc(text):
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lines = [f"📌 <b>Открытые задачи ({len(tasks)}):</b>\n"]
    for i, t in enumerate(tasks, 1):
        assignee = esc(t['assignee'] or '—')
        deadline = esc(t['deadline'] or '—')
        lines.append(f"<b>{i}. {esc(t['title'])}</b>")
        last = _last_detail(t.get('details'))
        if last:
            lines.append(f"   <i>{esc(last)}</i>")
        lines.append(f"   👤 {assignee}  📅 {deadline}")
        meta = []
        if t.get('created_by_name'):
            meta.append(f"создал: {esc(t['created_by_name'])}")
        if t.get('updated_by_name'):
            meta.append(f"изменил: {esc(t['updated_by_name'])}")
        if meta:
            lines.append(f"   ✏️ {', '.join(meta)}")
        lines.append("")

    kb = task_list_kb(tasks)
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb
    )


# ── Task history ────────────────────────────────────────────

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_private(update):
        return

    user = update.effective_user
    group_id = await get_user_group(user.id)
    tasks = get_closed_tasks(group_id)

    if not tasks:
        await update.message.reply_text("✅ Закрытых задач пока нет.")
        return

    def esc(text):
        """Escape HTML special chars."""
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    header = f"✅ <b>Выполненные задачи (последние {len(tasks)}):</b>\n"
    current = header

    for i, t in enumerate(tasks, 1):
        assignee = esc(t['assignee'] or '—')
        closed = (t.get('closed_at') or '')[:10]
        block = [f"<b>{i}. {esc(t['title'])}</b>"]
        if t.get('details'):
            block.append(f"   <i>{esc(t['details'])}</i>")
        block.append(f"   👤 {assignee}  ✓ {closed}")
        meta = []
        if t.get('created_by_name'):
            meta.append(f"создал: {esc(t['created_by_name'])}")
        if t.get('closed_by_name'):
            meta.append(f"закрыл: {esc(t['closed_by_name'])}")
        if meta:
            block.append(f"   ✏️ {', '.join(meta)}")
        block.append("")

        entry = "\n".join(block)
        if len(current) + len(entry) > 3800:
            await update.message.reply_text(current, parse_mode="HTML")
            current = entry
        else:
            current += entry

    if current.strip():
        await update.message.reply_text(current, parse_mode="HTML")


# ── Reassign (from callback) ────────────────────────────────

async def start_reassign(update: Update, context: ContextTypes.DEFAULT_TYPE, task_id: int):
    task = get_task(task_id)
    if not task:
        await update.callback_query.answer("Задача не найдена.")
        return ConversationHandler.END

    context.user_data['reassign_task_id'] = task_id
    context.user_data['reassign_orig'] = task

    await update.callback_query.message.reply_text(
        f"🔄 *Передача задачи:*\n_{task['title']}_\n\n"
        f"*Шаг 1/4* — Новое *название* (или «-» оставить текущее «{task['title']}»):",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return REASSIGN_TITLE


async def reassign_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    orig = context.user_data['reassign_orig']
    context.user_data['reassign_title'] = orig['title'] if text == '-' else text
    await update.message.reply_text(
        f"*Шаг 2/4* — *Детали* задачи (или «-»):",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return REASSIGN_DETAILS


async def reassign_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    orig = context.user_data['reassign_orig']
    context.user_data['reassign_details'] = orig.get('details') if text == '-' else text

    from database.db import get_group_users, get_user
    user = update.effective_user
    u = get_user(user.id)
    group_id = u['group_id'] if u else None
    users = get_group_users(group_id) if group_id else []

    if users:
        await update.message.reply_text(
            "*Шаг 3/4* — Выберите *нового ответственного* или введите имя вручную:",
            parse_mode="Markdown",
            reply_markup=assignee_kb(users)
        )
    else:
        await update.message.reply_text(
            "*Шаг 3/4* — *Новый ответственный* (@username или имя, или «-»):",
            parse_mode="Markdown",
            reply_markup=cancel_kb()
        )
    return REASSIGN_ASSIGNEE


async def reassign_assignee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data['reassign_assignee'] = None if text == '-' else text
    await update.message.reply_text(
        f"*Шаг 4/4* — *Срок выполнения* (или «-»):",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return REASSIGN_DEADLINE


async def reassign_assignee_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle assignee selection from inline keyboard inside reassign_conv."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "assignee_skip":
        context.user_data['reassign_assignee'] = None
    elif data.startswith("assignee_"):
        parts = data.split("_", 2)
        context.user_data['reassign_assignee'] = parts[2] if len(parts) > 2 else None

    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await query.message.reply_text(
        "*Шаг 4/4* — *Срок выполнения* (или «-»):",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return REASSIGN_DEADLINE


async def reassign_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    deadline = None if text == '-' else text
    ud = context.user_data

    from database.db import get_task
    from datetime import datetime
    existing = get_task(ud['reassign_task_id'])
    user = update.effective_user
    author = user.full_name or user.username or f"id{user.id}"
    new_details = ud.get('reassign_details')

    # Append to history instead of overwriting
    if new_details and new_details != '-':
        timestamp = datetime.now().strftime('%d.%m.%Y %H:%M')
        old_details = existing.get('details') or ''
        if old_details:
            combined = f"{old_details}\n--- {timestamp} ({author}) ---\n{new_details}"
        else:
            combined = new_details
    else:
        combined = existing.get('details')  # keep unchanged

    update_task(
        ud['reassign_task_id'],
        ud['reassign_title'],
        combined,
        ud['reassign_assignee'],
        deadline,
        updated_by=update.effective_user.id
    )
    task = get_task(ud['reassign_task_id'])
    await update.message.reply_text(
        f"✅ *Задача передана!*\n\n{_task_summary(task)}",
        parse_mode="Markdown"
    )
    return ConversationHandler.END
