
## Project Overview
Telegram bot for managing IT meetings in corporate Telegram groups.
- Personal commands run in **private chat (DM) with the bot** — keeps group clean
- Group receives only: agenda items, decisions summaries, final PDF report
- Stack: Python 3.13, python-telegram-bot 21.6, SQLite, ReportLab, python-dotenv

## Repository Structure
```
MeetingAgendaBot/
├── bot.py                    # Entry point, handler registration
├── config.py                 # All settings from .env via python-dotenv
├── keyboards.py              # All InlineKeyboardMarkup builders
├── requirements.txt          # Pinned dependencies
├── .env                      # Secrets (not in repo)
├── .env.example              # Template
├── meetings.db               # SQLite DB (auto-created)
├── database/
│   └── db.py                 # All DB operations (SQLite, no ORM)
└── handlers/
    ├── start.py              # /start, user registration, auto_register()
    ├── agenda.py             # /agenda (2-step conv), /shagenda
    ├── tasks.py              # /task (4-step), /tasks, /history, reassign
    ├── group_meeting.py      # /newmeeting /next /decision /pending /summary /handover
    ├── callbacks.py          # All inline button handlers
    ├── pdf_export.py         # ReportLab PDF generation (DejaVu fonts)
    ├── email_report.py       # SMTP email with HTML + PDF attachment
    └── backup.py             # /backup, /restore with confirmation
```

## Architecture Decisions

### Private vs Group commands
- `/agenda`, `/task`, `/tasks`, `/history`, `/shagenda`, `/backup`, `/restore` → **private chat only**
- `/newmeeting`, `/next`, `/decision`, `/pending`, `/summary`, `/handover` → **group only**
- Group commands restricted to: meeting organizer OR users in `ADMIN_IDS`
- `/newmeeting` can be run by any group member

### Group chat cleanliness
- All commands (`/decision`, `/pending`, `/next`, `/summary`) are **deleted** after execution via `_delete_command(update)`
- Organizer's text replies in `/decision` and `/pending` dialogs are deleted
- Bot question messages are tracked in `context.chat_data['dec_bot_msgs']` / `pend_bot_msgs` and deleted after decision is made
- Only final summary messages remain visible

### Meeting flow
```
/newmeeting → publishes full agenda + first item to group
/next       → cycles through unresolved items (skips 'done' status), wraps around
/decision   → 2-step dialog in group → Done (closes item) or ToDo (creates task + closes item)
/pending    → 2-step dialog in group → defers item to next meeting, auto-advances
/summary    → posts text summary + PDF to group, sends email if SENDMAIL=true
/handover   → transfers organizer role (reply to message or @username)
```

### Agenda lifecycle
- Items added before meeting via `/agenda` → stored in `pending_agenda` table
- At `/newmeeting` → `flush_pending_agenda()` moves them to `agenda_items`
- Unresolved items from last ended meeting auto-carry to new meeting via `get_unresolved_from_last_meeting()`
- Item statuses: `pending` → `discussing` → `done` | `pending_next`
- `/next` only cycles through non-`done` items

### Task details history
- Task `details` field stores append-only history:
  ```
  Original note
  --- 17.03.2026 21:00 (Anna) ---
  Updated note after discussion
  ```
- `/tasks` shows only last entry via `_last_detail()`
- PDF shows full history with grey separators

### group_id normalization
- Telegram returns supergroup IDs in two formats: `-1009999999999` and `-9999999999`
- All write operations store as-is (from `chat.id`)
- All read operations query both forms: `WHERE group_id=? OR group_id=?`
- `_normalize_group_id()` in db.py handles conversion

### Backup/Restore
- `/backup` → sends `meetings.db` file to user in DM
- `/restore` → receives `.db` file, validates SQLite header, saves to `meetings.db.restore_staging`
- Confirmation buttons: Apply+Restart / Cancel
- On apply: copies staging → DB, then `os.execv()` restarts bot process
- Access controlled by `BACKUP_OPERATOR` env var (`admin` or `all`)

## Key Functions

### db.py
- `get_active_meeting(group_id)` → queries both group_id formats
- `flush_pending_agenda(group_id, meeting_id)` → moves pre-meeting queue to meeting
- `get_unresolved_from_last_meeting(group_id)` → items not 'done' from last ended meeting
- `_get_user_name(conn, user_id)` → looks up full_name from users table
- `complete_task(task_id, closed_by=None)` → sets status='done', saves closed_by_name

### group_meeting.py
- `_check_organizer(update)` → checks organizer_id OR ADMIN_IDS
- `_post_current_item(context, chat_id, meeting_id)` → posts agenda item card to group
- `_advance(context, chat_id, meeting_id, close_status=None)` → moves to next non-done item
- `_do_summary(context, group_id, meeting_id)` → generates text + PDF + sends email
- `_delete_command(update)` → silently deletes command message

### pdf_export.py
- `_register_fonts()` → finds DejaVu TTF in system paths or project `fonts/` dir
- `build_pdf(meeting, agenda, decisions, pending, open_tasks, output_path)`
- Color: `#3b8ad1`, Title from `PDF_TITLE` env var

### email_report.py
- Sends `multipart/mixed` with `multipart/alternative` (plain + HTML) + PDF attachment
- Plain text fallback for email clients that don't render HTML
- Exchange-compatible structure

## Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `BOT_TOKEN` | — | Required. From @BotFather |
| `GROUP_ID` | `0` | Telegram group ID (negative) |
| `ADMIN_IDS` | — | Comma-separated user IDs for admin access |
| `BACKUP_OPERATOR` | `admin` | `admin` or `all` |
| `PDF_TITLE` | `IT Meeting Agenda` | PDF/email header title |
| `SENDMAIL` | `false` | Send email report after /summary |
| `SMTP_HOST` | `localhost` | SMTP server |
| `SMTP_PORT` | `25` | SMTP port |
| `SMTP_FROM` | — | Sender address |
| `SMTP_TO` | — | Comma-separated recipients |
| `SMTP_USER` | — | Optional SMTP auth username |
| `SMTP_PASS` | — | Optional SMTP auth password |
| `SMTP_TLS` | `false` | Use STARTTLS |

## Known Issues & Workarounds
- **group_id mismatch**: Telegram sometimes returns `-100XXXXXXXXX` vs `-XXXXXXXXX`. Fixed by querying both forms in all DB reads.
- **Exchange HTML stripping**: Anonymous SMTP relay may strip HTML. Use authenticated SMTP (port 587 + SMTP_USER/SMTP_PASS) for Exchange.
- **os.execv on restore**: Hard process replacement — works but bypasses PTB graceful shutdown. Acceptable for this use case.
- **PTBUserWarning on startup**: ConversationHandler per_message=False warning — suppressed with `warnings.filterwarnings`.

## Running Locally
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
apt-get install -y fonts-dejavu-core  # for PDF cyrillic support
cp .env.example .env && nano .env
python bot.py
```

## Deployment (systemd)
```bash
# /etc/systemd/system/meeting-bot.service
[Unit]
Description=IT Meeting Bot
After=network.target

[Service]
WorkingDirectory=/root/MeetingAgendaBot
ExecStart=/root/MeetingAgendaBot/venv/bin/python bot.py
EnvironmentFile=/root/MeetingAgendaBot/.env
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
