import asyncio
"""
Group chat handlers: /newmeeting, /next, /decision, /pending, /summary
/decision, /pending, /next, /summary — only for the meeting organizer.
"""
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from database.db import (
    get_active_meeting, create_meeting, get_meeting,
    get_agenda, set_current_agenda_idx, set_agenda_item_status,
    add_decision, add_pending, add_task, end_meeting,
    get_decisions, get_open_tasks, get_pending, flush_pending_agenda,
    get_unresolved_from_last_meeting, add_agenda_item
)
from keyboards import decision_type_kb, cancel_kb

DEC_TEXT, DEC_RESP, DEC_TYPE = range(30, 33)
PEND_NOTE, PEND_RESP = range(33, 35)


async def _delete_command(update):
    """Silently delete the command message from the group."""
    try:
        await update.message.delete()
    except Exception:
        pass  # No permission or already deleted — ignore

STATUS_ICON = {'pending': '⏳', 'discussing': '🔵', 'done': '✅', 'pending_next': '🔄'}


def _name(user):
    return user.full_name or user.username or f"id{user.id}"


def _now_time():
    from datetime import datetime
    return datetime.now().strftime("%H:%M")


def _now_date():
    from datetime import datetime
    return datetime.now().strftime("%d.%m.%Y")


async def _check_organizer(update: Update) -> bool:
    """Returns True if the user is the meeting organizer or a bot admin."""
    from config import ADMIN_IDS
    chat = update.effective_chat
    user = update.effective_user
    meeting = get_active_meeting(chat.id)

    if not meeting:
        await update.message.reply_text("⚠️ Нет активного митинга.")
        return False

    is_organizer = meeting.get('organizer_id') == user.id
    is_admin = user.id in ADMIN_IDS

    if not is_organizer and not is_admin:
        await update.message.reply_text(
            "⛔ Эта команда доступна только организатору митинга или администратору бота."
        )
        return False

    return True


async def _post_current_item(context, chat_id, meeting_id):
    """Post current agenda item card to the group chat."""
    meeting = get_meeting(meeting_id)
    items = get_agenda(meeting_id)
    idx = meeting.get('current_agenda_idx', 0)
    total = len(items)

    if idx >= total:
        await context.bot.send_message(
            chat_id,
            "📋 Все пункты повестки пройдены.\n"
            "Используйте /summary для завершения митинга."
        )
        return

    item = items[idx]
    # Only set to 'discussing' if still 'pending' — don't overwrite done/pending_next
    if item['status'] == 'pending':
        set_agenda_item_status(item['id'], 'discussing')
        item['status'] = 'discussing'

    text = f"🔵 *Пункт {idx + 1}/{total}: {item['title']}*\n"
    if item.get('details'):
        text += f"_{item['details']}_\n"
    if item.get('added_by_name'):
        text += f"👤 {item['added_by_name']}\n"
    text += f"\n_/decision — решение  |  /pending — отложить  |  /next — следующий  |  /summary — завершить_"

    await context.bot.send_message(chat_id, text, parse_mode="Markdown")


async def _advance(context, chat_id, meeting_id, close_status=None):
    """
    Move index forward and post next item.
    close_status: if set, updates current item status before advancing.
    None = leave status unchanged (used by /next).
    Returns True if advanced to next, False if no more items.
    """
    meeting = get_meeting(meeting_id)
    items = get_agenda(meeting_id)
    idx = meeting.get('current_agenda_idx', 0)

    if idx < len(items) and close_status is not None:
        cur = items[idx]
        set_agenda_item_status(cur['id'], close_status)

    # Find next item that is not done
    active_after = [i for i, item in enumerate(items) if i > idx and item['status'] != 'done']
    if not active_after:
        return False

    next_idx = active_after[0]
    set_current_agenda_idx(meeting_id, next_idx)
    await _post_current_item(context, chat_id, meeting_id)
    return True


# ── /newmeeting ─────────────────────────────────────────────

async def cmd_newmeeting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Эта команда работает только в группе.")
        return

    user = update.effective_user
    group_id = chat.id
    existing = get_active_meeting(group_id)
    if existing:
        await update.message.reply_text(
            f"⚠️ Митинг *«{existing['title']}»* уже идёт.\n"
            f"Завершите его через /summary.",
            parse_mode="Markdown"
        )
        return

    args = context.args
    title = " ".join(args).strip() if args else f"Митинг {_now_date()}"

    # Auto-backup DB before creating meeting
    try:
        import shutil, os as _os
        from config import DB_PATH
        backup_dir = _os.path.join(_os.path.dirname(DB_PATH), "backups")
        _os.makedirs(backup_dir, exist_ok=True)
        from datetime import datetime as _dt
        ts = _dt.now().strftime('%Y%m%d_%H%M%S')
        shutil.copy2(DB_PATH, _os.path.join(backup_dir, f"auto_{ts}.db"))
    except Exception:
        pass  # backup failure must never block the meeting

    meeting_id = create_meeting(group_id, title, user.id)
    flushed = flush_pending_agenda(group_id, meeting_id)

    # Carry over unresolved items from previous meeting (skipped via /next, pending_next)
    unresolved = get_unresolved_from_last_meeting(group_id)
    carried = 0
    for item in unresolved:
        # Skip if same title already in queue (avoid duplicates from /pending)
        existing = get_agenda(meeting_id)
        if not any(i['title'] == item['title'] for i in existing):
            add_agenda_item(meeting_id, item['title'], item.get('details'), item.get('added_by'))
            carried += 1

    items = get_agenda(meeting_id)

    organizer_mention = f"@{user.username}" if user.username else _name(user)
    header = (
        f"🟢 *Митинг начат: {title}*\n"
        f"👤 Организатор: {_name(user)}\n\n"
        f"_{organizer_mention} — вы организатор митинга, только вы можете управлять повесткой и вносить решения. "
        f"Для передачи управления используйте /handover @username_\n\n"
    )
    if items:
        header += "📋 *Повестка:*\n"
        for i, item in enumerate(items, 1):
            header += f"{i}. {item['title']}\n"
        header += "\nНачинаем обсуждение 👇"
    else:
        header += "_Повестка не сформирована. Участники могут добавить пункты через /agenda в ЛС с ботом._"

    await context.bot.send_message(update.effective_chat.id, header, parse_mode="Markdown")
    await _delete_command(update)

    if items:
        set_current_agenda_idx(meeting_id, 0)
        await _post_current_item(context, group_id, meeting_id)
    else:
        await update.message.reply_text(
            "Добавьте пункты повестки через /agenda в личном диалоге с ботом.\n"
            "Когда будете готовы начать обсуждение — напишите /next в группе."
        )


# ── /next ───────────────────────────────────────────────────

async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    if not await _check_organizer(update):
        return

    await _delete_command(update)
    chat_id = update.effective_chat.id
    meeting = get_active_meeting(chat_id)
    items = get_agenda(meeting['id'])

    if not items:
        await context.bot.send_message(
            chat_id,
            "📋 Повестка пуста. Добавьте пункты через /agenda в личном диалоге с ботом."
        )
        return

    idx = meeting.get('current_agenda_idx', 0)

    # Only cycle through unresolved items (not done)
    active = [i for i, item in enumerate(items) if item['status'] != 'done']

    if not active:
        await context.bot.send_message(
            chat_id,
            "✅ Все пункты повестки закрыты. Используйте /summary для завершения."
        )
        await _delete_command(update)
        return

    # Find next active item after current idx (cyclic)
    next_idx = None
    for i in active:
        if i > idx:
            next_idx = i
            break
    if next_idx is None:
        next_idx = active[0]  # wrap around

    set_current_agenda_idx(meeting['id'], next_idx)
    await _post_current_item(context, chat_id, meeting['id'])
    await _delete_command(update)


# ── /handover ───────────────────────────────────────────────

async def cmd_handover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transfer organizer role to another user. Only current organizer or admin."""
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    if not await _check_organizer(update):
        return

    chat = update.effective_chat
    meeting = get_active_meeting(chat.id)

    # Parse @username or reply
    target_user = None
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif context.args:
        # Try to find user by username in DB
        from database.db import get_conn
        username = context.args[0].lstrip('@')
        conn = get_conn()
        row = conn.execute(
            "SELECT user_id, full_name, username FROM users WHERE username=? OR full_name=?",
            (username, username)
        ).fetchone()
        conn.close()
        if row:
            class _U:
                def __init__(self, r):
                    self.id = r[0]; self.full_name = r[1]; self.username = r[2]
            target_user = _U(row)
        else:
            # User not in local DB — try Telegram API lookup
            try:
                tg_chat = await context.bot.get_chat(f"@{username}")
                class _U:
                    def __init__(self, u):
                        self.id = u.id
                        self.full_name = u.full_name or u.first_name or username
                        self.username = u.username or username
                target_user = _U(tg_chat)
            except Exception:
                pass

    if not target_user:
        await context.bot.send_message(
            chat.id,
            "⚠️ Укажите нового ведущего: ответьте на его сообщение или напишите /handover @username"
        )
        await _delete_command(update)
        return

    # Update organizer in DB
    from database.db import get_conn
    conn = get_conn()
    conn.execute("UPDATE meetings SET organizer_id=? WHERE id=?", (target_user.id, meeting['id']))
    conn.commit()
    conn.close()

    new_name = getattr(target_user, 'full_name', None) or getattr(target_user, 'username', f"id{target_user.id}")
    old_name = _name(update.effective_user)

    await context.bot.send_message(
        chat.id,
        f"🔄 Роль ведущего передана от *{old_name}* к *{new_name}*",
        parse_mode="Markdown"
    )
    await _delete_command(update)


# ── /decision ───────────────────────────────────────────────

async def cmd_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"cmd_decision called: chat={update.effective_chat.id}, user={update.effective_user.id}")
    if update.effective_chat.type not in ("group", "supergroup"):
        logger.info("cmd_decision: not a group")
        return ConversationHandler.END
    if not await _check_organizer(update):
        logger.info("cmd_decision: not organizer or no meeting")
        return ConversationHandler.END
    logger.info("cmd_decision: passed checks, entering conversation")

    chat = update.effective_chat
    meeting = get_active_meeting(chat.id)
    items = get_agenda(meeting['id'])
    idx = meeting.get('current_agenda_idx', 0)
    current_item = items[idx] if items and idx < len(items) else None

    context.chat_data['dec_meeting_id'] = meeting['id']
    context.chat_data['dec_group_id'] = chat.id
    context.chat_data['dec_user_id'] = update.effective_user.id
    context.chat_data['dec_agenda_item'] = current_item

    item_hint = f" по пункту *«{current_item['title']}»*" if current_item else ""
    bot_msg = await context.bot.send_message(
        update.effective_chat.id,
        f"✅ *Решение{item_hint}*\n\nВведите текст решения:",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    context.chat_data['dec_bot_msgs'] = [bot_msg.message_id]
    await _delete_command(update)
    return DEC_TEXT


async def dec_text_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only organizer can continue the dialog they started
    meeting_id = context.chat_data.get('dec_meeting_id')
    if not meeting_id:
        return ConversationHandler.END
    meeting = get_meeting(meeting_id)
    if meeting and meeting.get('organizer_id') != update.effective_user.id:
        return DEC_TEXT  # ignore message, stay in state

    context.chat_data['dec_text'] = update.message.text.strip()
    await _delete_command(update)
    bot_msg = await context.bot.send_message(
        update.effective_chat.id,
        "Укажите ответственного (имя, @username или «-»):",
        reply_markup=cancel_kb()
    )
    context.chat_data.setdefault('dec_bot_msgs', []).append(bot_msg.message_id)
    return DEC_RESP


async def dec_resp_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    meeting_id = context.chat_data.get('dec_meeting_id')
    if not meeting_id:
        return ConversationHandler.END
    meeting = get_meeting(meeting_id)
    if meeting and meeting.get('organizer_id') != update.effective_user.id:
        return DEC_RESP  # ignore, stay in state

    text = update.message.text.strip()
    context.chat_data['dec_responsible'] = None if text == '-' else text
    await _delete_command(update)
    current_item = context.chat_data.get('dec_agenda_item')
    item_id = current_item['id'] if current_item else 0

    bot_msg = await context.bot.send_message(
        update.effective_chat.id,
        "Как зафиксировать решение?",
        reply_markup=decision_type_kb(item_id)
    )
    context.chat_data.setdefault('dec_bot_msgs', []).append(bot_msg.message_id)
    return DEC_TYPE


async def dec_type_callback(update, context):
    """Handle Done/ToDo button press — final step of /decision conv."""
    from telegram.ext import ConversationHandler as CH
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    dec_type = "done" if data.startswith("dec_done_") else "todo"
    agenda_item_id = int(data.split("_")[-1]) or None

    cd = context.chat_data
    dec_text = cd.get('dec_text')
    responsible = cd.get('dec_responsible')
    meeting_id = cd.get('dec_meeting_id')
    g_id = cd.get('dec_group_id')

    if not dec_text or not meeting_id:
        await query.message.reply_text("⚠️ Данные устарели. Начните /decision заново.")
        return CH.END

    from database.db import add_decision, add_task, set_agenda_item_status, get_open_tasks
    add_decision(meeting_id, agenda_item_id, dec_text, responsible, dec_type, user.id)

    if dec_type == "todo":
        add_task(
            group_id=g_id,
            meeting_id=meeting_id,
            title=dec_text,
            details=None,
            assignee=responsible,
            deadline=None,
            created_by=user.id
        )

    if agenda_item_id:
        set_agenda_item_status(agenda_item_id, 'done')

    type_icon = "✅" if dec_type == "done" else "📌"
    type_label = "Decision made" if dec_type == "done" else "Added as task"
    resp_text = f"\n👤 {responsible}" if responsible else ""
    todo_note = "\n_Task created_" if dec_type == "todo" else ""

    for msg_id in context.chat_data.get('dec_bot_msgs', []):
        try:
            await context.bot.delete_message(g_id, msg_id)
        except Exception:
            pass
    context.chat_data.pop('dec_bot_msgs', None)

    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        g_id,
        f"{type_icon} *{type_label}:*\n{dec_text}{resp_text}{todo_note}",
        parse_mode="Markdown"
    )

    has_next = await _advance(context, g_id, meeting_id, close_status='done')
    if not has_next:
        await context.bot.send_message(
            g_id,
            "📋 Все пункты пройдены. Используйте /summary для завершения."
        )
    return CH.END


# ── /pending ────────────────────────────────────────────────

async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        return ConversationHandler.END
    if not await _check_organizer(update):
        return ConversationHandler.END

    chat = update.effective_chat
    meeting = get_active_meeting(chat.id)
    items = get_agenda(meeting['id'])
    idx = meeting.get('current_agenda_idx', 0)
    current_item = items[idx] if items and idx < len(items) else None

    context.chat_data['pend_meeting_id'] = meeting['id']
    context.chat_data['pend_group_id'] = chat.id
    context.chat_data['pend_agenda_item'] = current_item

    item_hint = f" *«{current_item['title']}»*" if current_item else ""
    bot_msg = await context.bot.send_message(
        update.effective_chat.id,
        f"🔄 *Откладываем пункт{item_hint}*\n\n"
        f"Заметка — что осталось нерешённым (или «-»):",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    context.chat_data['pend_bot_msgs'] = [bot_msg.message_id]
    await _delete_command(update)
    return PEND_NOTE


async def pend_note_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    meeting_id = context.chat_data.get('pend_meeting_id')
    if not meeting_id:
        return ConversationHandler.END
    meeting = get_meeting(meeting_id)
    if meeting and meeting.get('organizer_id') != update.effective_user.id:
        return PEND_NOTE  # ignore

    text = update.message.text.strip()
    context.chat_data['pend_note'] = None if text == '-' else text
    await _delete_command(update)
    bot_msg = await context.bot.send_message(
        update.effective_chat.id,
        "Ответственный за проработку (или «-»):",
        reply_markup=cancel_kb()
    )
    context.chat_data.setdefault('pend_bot_msgs', []).append(bot_msg.message_id)
    return PEND_RESP


async def pend_resp_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    meeting_id = context.chat_data.get('pend_meeting_id')
    if not meeting_id:
        return ConversationHandler.END
    meeting = get_meeting(meeting_id)
    if meeting and meeting.get('organizer_id') != update.effective_user.id:
        return PEND_RESP  # ignore

    text = update.message.text.strip()
    responsible = None if text == '-' else text
    cd = context.chat_data
    group_id = cd['pend_group_id']
    current_item = cd.get('pend_agenda_item')
    item_id = current_item['id'] if current_item else None
    item_title = current_item['title'] if current_item else '—'

    add_pending(meeting_id, item_id, cd.get('pend_note'), responsible)
    if item_id:
        set_agenda_item_status(item_id, 'pending_next')

    resp_text = f"\n👤 {responsible}" if responsible else ""
    note_text = f"\n📝 {cd['pend_note']}" if cd.get('pend_note') else ""
    # Delete all dialog messages (bot questions + organizer answers)
    for msg_id in context.chat_data.get('pend_bot_msgs', []):
        try:
            await context.bot.delete_message(group_id, msg_id)
        except Exception:
            pass
    context.chat_data.pop('pend_bot_msgs', None)
    await _delete_command(update)

    # Post clean summary
    await context.bot.send_message(
        group_id,
        f"🔄 *Отложено до следующего митинга:* {item_title}{note_text}{resp_text}",
        parse_mode="Markdown"
    )

    has_next = await _advance(context, group_id, meeting_id, close_status='pending_next')
    if not has_next:
        await context.bot.send_message(
            group_id,
            "📋 Все пункты пройдены. Используйте /summary для завершения."
        )
    return ConversationHandler.END


# ── /summary ────────────────────────────────────────────────

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    if not await _check_organizer(update):
        return

    meeting = get_active_meeting(update.effective_chat.id)
    await _do_summary(context, update.effective_chat.id, meeting['id'], update)


async def _do_summary(context, group_id, meeting_id, update_to_delete=None):
    meeting = get_meeting(meeting_id)
    agenda = get_agenda(meeting_id)
    decisions = get_decisions(meeting_id)
    pending = get_pending(meeting_id)
    open_tasks = get_open_tasks(group_id)

    end_meeting(meeting_id)

    # Generate PDF and send to group
    import tempfile, os
    from handlers.pdf_export import build_pdf, send_pdf, REPORTLAB_OK
    pdf_path = None
    if REPORTLAB_OK:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            pdf_path = tmp.name
        try:
            build_pdf(meeting, agenda, decisions, pending, open_tasks, pdf_path)
            safe = "".join(c for c in meeting['title'] if c.isalnum() or c in ' _-')[:30].strip()
            filename = f"protocol_{safe}.pdf"
            with open(pdf_path, 'rb') as f:
                await context.bot.send_document(
                    group_id, document=f, filename=filename,
                    caption=f"Meeting agenda: {meeting['title']}"
                )
        except Exception as e:
            await context.bot.send_message(group_id, f"PDF error: {e}")

    await asyncio.sleep(1)

    # Send email report (non-blocking)
    from handlers.email_report import send_email_report
    await send_email_report(meeting, agenda, decisions, pending, open_tasks, pdf_path)

    if pdf_path and os.path.exists(pdf_path):
        os.unlink(pdf_path)

    lines = [
        f"🏁 *Итоги митинга: {meeting['title']}*",
        f"🕐 {(meeting.get('started_at') or '')[:16]} → {_now_time()}",
        ""
    ]

    agenda_num_map = {item['id']: i for i, item in enumerate(agenda, 1)}

    lines.append("📋 *Повестка:*")
    for i, item in enumerate(agenda, 1):
        icon = STATUS_ICON.get(item['status'], '⏳')
        lines.append(f"{icon} {i}. {item['title']}")
    lines.append("")

    if decisions:
        lines.append("✅ *Решения:*")
        for d in decisions:
            icon = "✅" if d['decision_type'] == 'done' else "📌"
            resp = f" — {d['responsible']}" if d.get('responsible') else ""
            num = agenda_num_map.get(d.get('agenda_item_id'), '?')
            lines.append(f"{icon} {num}. {d['text']}{resp}")
        lines.append("")

    if pending:
        lines.append("🔄 *Отложено на следующий митинг:*")
        for p in pending:
            resp = f" ({p['responsible']})" if p.get('responsible') else ""
            note = f": {p['note']}" if p.get('note') else ""
            num = agenda_num_map.get(p.get('agenda_item_id'), '?')
            lines.append(f"🔄 {num}. {p.get('agenda_title') or '—'}{note}{resp}")
        lines.append("")

    if open_tasks:
        lines.append("📌 *Открытые задачи:*")
        for t in open_tasks:
            assignee = t['assignee'] or '—'
            deadline = t['deadline'] or '—'
            lines.append(f"• {t['title']}\n  👤 {assignee}  📅 {deadline}")

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    bot_username = context.bot.username
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 Открыть бот", url=f"https://t.me/{bot_username}")
    ]])
    await context.bot.send_message(group_id, "\n".join(lines), parse_mode="Markdown", reply_markup=kb)
    if update_to_delete:
        await _delete_command(update_to_delete)
