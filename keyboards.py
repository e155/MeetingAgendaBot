from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def name(user):
    return user.full_name or user.username or f"user_{user.id}"


def main_private_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Повестка", callback_data="show_agenda"),
            InlineKeyboardButton("➕ Добавить пункт", callback_data="cmd_agenda"),
        ],
        [
            InlineKeyboardButton("📌 Задачи", callback_data="show_tasks"),
            InlineKeyboardButton("✅ История", callback_data="show_history"),
        ],
        [
            InlineKeyboardButton("🟢 Начать митинг", callback_data="cmd_newmeeting"),
        ],
    ])


def decision_type_kb(agenda_item_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Done — принято", callback_data=f"dec_done_{agenda_item_id}"),
        InlineKeyboardButton("📌 ToDo — в задачи", callback_data=f"dec_todo_{agenda_item_id}"),
    ]])


def task_list_kb(tasks):
    rows = []
    for t in tasks:
        label = t['title'][:28] + ("…" if len(t['title']) > 28 else "")
        rows.append([
            InlineKeyboardButton(f"✅ {label}", callback_data=f"done_task_{t['id']}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"reassign_task_{t['id']}"),
        ])
    return InlineKeyboardMarkup(rows) if rows else None


def confirm_close_kb(task_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Да, закрыть", callback_data=f"confirm_close_{task_id}"),
        InlineKeyboardButton("❌ Нет", callback_data=f"cancel_close_{task_id}"),
    ]])


def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel_conv")]])


def assignee_kb(users, allow_skip=True):
    """Keyboard with known group members + skip/cancel options."""
    rows = []
    # Up to 8 users, 2 per row
    for i in range(0, min(len(users), 8), 2):
        row = []
        for u in users[i:i+2]:
            label = u['full_name'] or u['username'] or f"id{u['user_id']}"
            row.append(InlineKeyboardButton(label, callback_data=f"assignee_{u['user_id']}_{label[:20]}"))
        rows.append(row)
    footer = []
    if allow_skip:
        footer.append(InlineKeyboardButton("— Без ответственного", callback_data="assignee_skip"))
    footer.append(InlineKeyboardButton("❌ Отмена", callback_data="cancel_conv"))
    rows.append(footer)
    return InlineKeyboardMarkup(rows)
