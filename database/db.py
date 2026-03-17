import sqlite3
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            username  TEXT,
            full_name TEXT,
            group_id  INTEGER
        );

        CREATE TABLE IF NOT EXISTS meetings (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id            INTEGER NOT NULL,
            title               TEXT NOT NULL,
            organizer_id        INTEGER,
            status              TEXT DEFAULT 'active',
            current_agenda_idx  INTEGER DEFAULT 0,
            started_at          TEXT DEFAULT (datetime('now','localtime')),
            ended_at            TEXT
        );

        CREATE TABLE IF NOT EXISTS agenda_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id  INTEGER NOT NULL,
            title       TEXT NOT NULL,
            details     TEXT,
            status      TEXT DEFAULT 'pending',
            order_num   INTEGER DEFAULT 0,
            added_by    INTEGER,
            FOREIGN KEY (meeting_id) REFERENCES meetings(id)
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id      INTEGER NOT NULL,
            agenda_item_id  INTEGER,
            text            TEXT NOT NULL,
            responsible     TEXT,
            decision_type   TEXT DEFAULT 'done',
            made_by         INTEGER,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (meeting_id) REFERENCES meetings(id)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id  INTEGER,
            group_id    INTEGER NOT NULL,
            title       TEXT NOT NULL,
            details     TEXT,
            assignee    TEXT,
            deadline    TEXT,
            status      TEXT DEFAULT 'open',
            created_by  INTEGER,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            closed_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS pending_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id      INTEGER NOT NULL,
            agenda_item_id  INTEGER,
            note            TEXT,
            responsible     TEXT,
            FOREIGN KEY (meeting_id) REFERENCES meetings(id)
        );
    """)
    init_pending_agenda_table(conn)
    conn.commit()
    conn.close()


# ── Users ──────────────────────────────────────────────────

def upsert_user(user_id, username, full_name, group_id):
    conn = get_conn()
    conn.execute("""
        INSERT INTO users (user_id, username, full_name, group_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            full_name=excluded.full_name,
            group_id=excluded.group_id
    """, (user_id, username, full_name, group_id))
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Meetings ───────────────────────────────────────────────

def create_meeting(group_id, title, organizer_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO meetings (group_id, title, organizer_id) VALUES (?,?,?)",
              (group_id, title, organizer_id))
    mid = c.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_active_meeting(group_id):
    conn = get_conn()
    norm = _normalize_group_id(group_id)
    short = int(str(norm).replace("-100", "-", 1))
    row = conn.execute(
        "SELECT * FROM meetings WHERE (group_id=? OR group_id=?) AND status='active' ORDER BY id DESC LIMIT 1",
        (norm, short)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_meeting(meeting_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def end_meeting(meeting_id):
    conn = get_conn()
    conn.execute(
        "UPDATE meetings SET status='ended', ended_at=datetime('now','localtime') WHERE id=?",
        (meeting_id,)
    )
    conn.commit()
    conn.close()


def set_current_agenda_idx(meeting_id, idx):
    conn = get_conn()
    conn.execute("UPDATE meetings SET current_agenda_idx=? WHERE id=?", (idx, meeting_id))
    conn.commit()
    conn.close()


# ── Agenda ─────────────────────────────────────────────────

def add_agenda_item(meeting_id, title, details, added_by):
    conn = get_conn()
    c = conn.cursor()
    # Ensure column exists
    try:
        c.execute("ALTER TABLE agenda_items ADD COLUMN added_by_name TEXT")
    except Exception:
        pass
    n = c.execute("SELECT COUNT(*) FROM agenda_items WHERE meeting_id=?", (meeting_id,)).fetchone()[0]
    # Get author name
    author_row = c.execute("SELECT full_name, username FROM users WHERE user_id=?", (added_by,)).fetchone()
    added_by_name = (author_row[0] or author_row[1]) if author_row else None
    c.execute(
        "INSERT INTO agenda_items (meeting_id, title, details, order_num, added_by, added_by_name) VALUES (?,?,?,?,?,?)",
        (meeting_id, title, details, n + 1, added_by, added_by_name)
    )
    item_id = c.lastrowid
    conn.commit()
    conn.close()
    return item_id


def get_agenda(meeting_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM agenda_items WHERE meeting_id=? ORDER BY order_num", (meeting_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_agenda_item_status(item_id, status):
    conn = get_conn()
    conn.execute("UPDATE agenda_items SET status=? WHERE id=?", (status, item_id))
    conn.commit()
    conn.close()


# ── Decisions ──────────────────────────────────────────────

def add_decision(meeting_id, agenda_item_id, text, responsible, decision_type, made_by):
    conn = get_conn()
    conn.execute(
        "INSERT INTO decisions (meeting_id, agenda_item_id, text, responsible, decision_type, made_by) VALUES (?,?,?,?,?,?)",
        (meeting_id, agenda_item_id, text, responsible, decision_type, made_by)
    )
    conn.commit()
    conn.close()


def get_decisions(meeting_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT d.*, a.title as agenda_title FROM decisions d "
        "LEFT JOIN agenda_items a ON d.agenda_item_id=a.id "
        "WHERE d.meeting_id=? ORDER BY d.id",
        (meeting_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Tasks ──────────────────────────────────────────────────

def _get_user_name(conn, user_id):
    if not user_id:
        return None
    row = conn.execute("SELECT full_name, username FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row:
        return row[0] or row[1]
    return None


def add_task(group_id, meeting_id, title, details, assignee, deadline, created_by):
    conn = get_conn()
    # Ensure columns exist
    for col in ['created_by_name TEXT', 'updated_by INTEGER', 'updated_by_name TEXT']:
        try:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col}")
        except Exception:
            pass
    created_by_name = _get_user_name(conn, created_by)
    c = conn.cursor()
    c.execute(
        "INSERT INTO tasks (group_id, meeting_id, title, details, assignee, deadline, created_by, created_by_name) VALUES (?,?,?,?,?,?,?,?)",
        (group_id, meeting_id, title, details, assignee, deadline, created_by, created_by_name)
    )
    task_id = c.lastrowid
    conn.commit()
    conn.close()
    return task_id


def get_open_tasks(group_id):
    conn = get_conn()
    norm = _normalize_group_id(group_id)
    short = int(str(norm).replace("-100", "-", 1))
    rows = conn.execute(
        "SELECT * FROM tasks WHERE (group_id=? OR group_id=?) AND status='open' ORDER BY deadline NULLS LAST, id",
        (norm, short)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_closed_tasks(group_id, limit=20):
    conn = get_conn()
    norm = _normalize_group_id(group_id)
    short = int(str(norm).replace("-100", "-", 1))
    rows = conn.execute(
        "SELECT * FROM tasks WHERE (group_id=? OR group_id=?) AND status='done' ORDER BY closed_at DESC LIMIT ?",
        (norm, short, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def complete_task(task_id, closed_by=None):
    conn = get_conn()
    for col in ['closed_by INTEGER', 'closed_by_name TEXT']:
        try:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col}")
        except Exception:
            pass
    closed_by_name = _get_user_name(conn, closed_by)
    conn.execute(
        "UPDATE tasks SET status='done', closed_at=datetime('now','localtime'), closed_by=?, closed_by_name=? WHERE id=?",
        (closed_by, closed_by_name, task_id)
    )
    conn.commit()
    conn.close()


def get_task(task_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_task(task_id, title, details, assignee, deadline, updated_by=None):
    conn = get_conn()
    for col in ['created_by_name TEXT', 'updated_by INTEGER', 'updated_by_name TEXT']:
        try:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col}")
        except Exception:
            pass
    updated_by_name = _get_user_name(conn, updated_by)
    conn.execute(
        "UPDATE tasks SET title=?, details=?, assignee=?, deadline=?, updated_by=?, updated_by_name=? WHERE id=?",
        (title, details, assignee, deadline, updated_by, updated_by_name, task_id)
    )
    conn.commit()
    conn.close()


# ── Pending ────────────────────────────────────────────────

def add_pending(meeting_id, agenda_item_id, note, responsible):
    conn = get_conn()
    conn.execute(
        "INSERT INTO pending_items (meeting_id, agenda_item_id, note, responsible) VALUES (?,?,?,?)",
        (meeting_id, agenda_item_id, note, responsible)
    )
    conn.commit()
    conn.close()


def get_pending(meeting_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT p.*, a.title as agenda_title FROM pending_items p "
        "LEFT JOIN agenda_items a ON p.agenda_item_id=a.id "
        "WHERE p.meeting_id=?",
        (meeting_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Conversation state for group chats ────────────────────
# Stored in-memory via context.chat_data (built into PTB)


# ── Pre-meeting agenda queue ───────────────────────────────
# Items added before a meeting starts, flushed into meeting on /newmeeting

def init_pending_agenda_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_agenda (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id   INTEGER NOT NULL,
            title      TEXT NOT NULL,
            details    TEXT,
            added_by   INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)


def add_pending_agenda_item(group_id, title, details, added_by):
    conn = get_conn()
    try:
        conn.execute("ALTER TABLE pending_agenda ADD COLUMN added_by_name TEXT")
    except Exception:
        pass
    author_row = conn.execute("SELECT full_name, username FROM users WHERE user_id=?", (added_by,)).fetchone()
    added_by_name = (author_row[0] or author_row[1]) if author_row else None
    conn.execute(
        "INSERT INTO pending_agenda (group_id, title, details, added_by, added_by_name) VALUES (?,?,?,?,?)",
        (group_id, title, details, added_by, added_by_name)
    )
    conn.commit()
    conn.close()


def get_pending_agenda(group_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM pending_agenda WHERE group_id=? ORDER BY id",
        (group_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _normalize_group_id(group_id):
    """
    Telegram sometimes returns supergroup IDs with -100 prefix, sometimes without.
    Normalize to always use the -100 form for storage, and match both forms when querying.
    """
    s = str(group_id)
    if s.startswith("-100"):
        return int(s)
    elif s.startswith("-"):
        return int("-100" + s[1:])
    return group_id


def flush_pending_agenda(group_id, meeting_id):
    """Move all queued items into the meeting and clear the queue."""
    conn = get_conn()
    # Match both -100XXXXXXXXX and -XXXXXXXXX forms
    norm = _normalize_group_id(group_id)
    short = int(str(norm).replace("-100", "-", 1))
    rows = conn.execute(
        "SELECT * FROM pending_agenda WHERE group_id=? OR group_id=? ORDER BY id",
        (norm, short)
    ).fetchall()
    items = [dict(r) for r in rows]

    for item in items:
        n = conn.execute(
            "SELECT COUNT(*) FROM agenda_items WHERE meeting_id=?", (meeting_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO agenda_items (meeting_id, title, details, order_num, added_by) VALUES (?,?,?,?,?)",
            (meeting_id, item['title'], item['details'], n + 1, item['added_by'])
        )

    conn.execute("DELETE FROM pending_agenda WHERE group_id=? OR group_id=?", (norm, short))
    conn.commit()
    conn.close()
    return len(items)


def get_unresolved_from_last_meeting(group_id):
    """Return agenda items from the last ended meeting that were not resolved (not 'done')."""
    conn = get_conn()
    norm = _normalize_group_id(group_id)
    short = int(str(norm).replace("-100", "-", 1))
    row = conn.execute(
        "SELECT id FROM meetings WHERE (group_id=? OR group_id=?) AND status='ended' ORDER BY id DESC LIMIT 1",
        (norm, short)
    ).fetchone()
    if not row:
        conn.close()
        return []
    last_meeting_id = row[0]
    rows = conn.execute(
        "SELECT * FROM agenda_items WHERE meeting_id=? AND status != 'done' ORDER BY order_num",
        (last_meeting_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_group_users(group_id):
    """Return all known users of a group."""
    conn = get_conn()
    norm = _normalize_group_id(group_id)
    short = int(str(norm).replace("-100", "-", 1))
    rows = conn.execute(
        "SELECT user_id, full_name, username FROM users WHERE group_id=? OR group_id=? ORDER BY full_name",
        (norm, short)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
