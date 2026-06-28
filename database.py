"""
database.py
============
All SQLite3 database access for the Research Lab Activity Tracker lives here.

Design notes
------------
- We use *direct sqlite3 queries* (no ORM) as permitted by the requirements.
- A brand new connection is opened for every operation and closed immediately
  afterwards. SQLite connections are cheap to open, and this avoids any
  cross-thread / cross-session issues that can occur when a single shared
  connection is cached inside a multi-user Streamlit server process.
- Every write operation is wrapped in try/except so a database error never
  crashes the Streamlit app -- callers receive a (success: bool, message: str)
  tuple (or raise a clearly-described exception) so the UI layer can show a
  friendly st.error()/st.success() notification.
- Read operations that feed tables/charts return a pandas DataFrame, which is
  the most convenient shape for Streamlit + Plotly.
"""

import os
import sqlite3
from datetime import datetime
from contextlib import contextmanager

import pandas as pd

import auth  # local module - password hashing helpers

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# The database file lives next to this script so the app works regardless of
# the directory it is launched from.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lab_tracker.db")

# Default admin credentials (created automatically on first run).
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------
@contextmanager
def get_connection():
    """
    Context manager that yields a sqlite3 connection configured with:
      - row_factory = sqlite3.Row   -> rows behave like dicts (row['col'])
      - foreign key support (not strictly required here, but good practice)
    The connection is always closed when the `with` block exits, even if an
    exception is raised, and any uncommitted change is rolled back on error.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_str() -> str:
    """Return the current timestamp formatted for storage as TEXT in SQLite."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------
def init_database() -> None:
    """
    Create the database file (if it does not already exist) and ensure both
    tables exist. Also seeds a default admin account the very first time the
    app is run, so the application is usable immediately without any manual
    setup step.

    Safe to call on every app start -- all statements use
    "CREATE TABLE IF NOT EXISTS" and the admin seed only happens if no admin
    row is present.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # --- Users table -----------------------------------------------
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                username       TEXT NOT NULL UNIQUE,
                password_hash  TEXT NOT NULL,
                role           TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                full_name      TEXT,
                is_active      INTEGER NOT NULL DEFAULT 1,
                is_approved    INTEGER NOT NULL DEFAULT 1,
                created_date   TEXT NOT NULL
            )
            """
        )

        # --- Migration for databases created before the approval feature
        # existed: SQLite has no "ADD COLUMN IF NOT EXISTS", so check first.
        # New accounts created before this column existed are treated as
        # already-approved (default 1), so nobody who could already log in
        # is suddenly locked out by this upgrade.
        existing_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(users)").fetchall()}
        if "is_approved" not in existing_columns:
            cursor.execute("ALTER TABLE users ADD COLUMN is_approved INTEGER NOT NULL DEFAULT 1")

        # --- Lab_Entries table -------------------------------------------
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS lab_entries (
                entry_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date               TEXT NOT NULL,
                user_name                TEXT NOT NULL,
                professor_name           TEXT NOT NULL,
                lab_name                 TEXT NOT NULL,
                project_name             TEXT NOT NULL,
                entry_time               TEXT NOT NULL,
                exit_time                TEXT NOT NULL,
                total_hours              REAL NOT NULL,
                lab_activity             TEXT,
                lab_partner_name         TEXT,
                lab_partner_contribution TEXT,
                notes                    TEXT,
                created_timestamp        TEXT NOT NULL
            )
            """
        )

        # Helpful indexes for the search/filter features in Tab 2-5.
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_professor ON lab_entries(professor_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_lab ON lab_entries(lab_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_project ON lab_entries(project_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_date ON lab_entries(entry_date)")

        # --- Seed default admin account, only if it doesn't already exist
        cursor.execute("SELECT 1 FROM users WHERE username = ?", (DEFAULT_ADMIN_USERNAME,))
        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO users (username, password_hash, role, full_name, is_active, created_date)
                VALUES (?, ?, 'admin', 'Administrator', 1, ?)
                """,
                (
                    DEFAULT_ADMIN_USERNAME,
                    auth.hash_password(DEFAULT_ADMIN_PASSWORD),
                    now_str(),
                ),
            )


# ---------------------------------------------------------------------------
# USER management functions
# ---------------------------------------------------------------------------
def get_user_by_username(username: str):
    """Return a dict for the matching user row, or None if not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_users_df() -> pd.DataFrame:
    """Return all users (minus password hashes) as a DataFrame for display."""
    with get_connection() as conn:
        df = pd.read_sql_query(
            """
            SELECT user_id, username, full_name, role,
                   CASE
                       WHEN is_approved = 0 THEN 'Pending Approval'
                       WHEN is_active = 0 THEN 'Disabled'
                       ELSE 'Active'
                   END AS status,
                   created_date
            FROM users
            ORDER BY user_id ASC
            """,
            conn,
        )
    return df


def get_pending_users() -> pd.DataFrame:
    """Return self-registered accounts that are still awaiting admin approval."""
    with get_connection() as conn:
        df = pd.read_sql_query(
            """
            SELECT user_id, username, full_name, created_date
            FROM users
            WHERE is_approved = 0
            ORDER BY created_date ASC
            """,
            conn,
        )
    return df


def create_user(username: str, password: str, role: str, full_name: str = "", is_approved: bool = True):
    """
    Insert a new user. Returns (success: bool, message: str).
    Fails gracefully (instead of raising) if the username is already taken.

    `is_approved` defaults to True because this function is used both by:
      - Admins adding a user directly from User Management (should be
        usable immediately), and
      - The public self-registration page (which passes is_approved=False
        so the account exists but cannot log in until an admin approves it).
    """
    username = (username or "").strip()
    if not username or not password:
        return False, "Username and password are required."
    if role not in ("admin", "user"):
        return False, "Role must be 'admin' or 'user'."

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, role, full_name, is_active, is_approved, created_date)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    username, auth.hash_password(password), role, full_name.strip(),
                    1 if is_approved else 0, now_str(),
                ),
            )
        return True, f"User '{username}' created successfully."
    except sqlite3.IntegrityError:
        return False, f"Username '{username}' already exists. Please choose another."
    except Exception as exc:  # pragma: no cover - defensive catch-all
        return False, f"Unexpected database error while creating user: {exc}"


def approve_user(user_id: int):
    """Approve a pending self-registered account so it can log in."""
    try:
        with get_connection() as conn:
            conn.execute("UPDATE users SET is_approved = 1 WHERE user_id = ?", (user_id,))
        return True, "Account approved -- the user can now log in."
    except Exception as exc:
        return False, f"Unexpected database error while approving user: {exc}"


def reject_pending_user(user_id: int):
    """
    Permanently remove a pending account request. The WHERE clause is
    scoped to is_approved = 0 on purpose, so this can never accidentally
    delete an already-active account, even if called with the wrong id.
    """
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM users WHERE user_id = ? AND is_approved = 0", (user_id,)
            )
            if cursor.rowcount == 0:
                return False, "That account is not a pending request (it may already be approved)."
        return True, "Account request rejected and removed."
    except Exception as exc:
        return False, f"Unexpected database error while rejecting user: {exc}"


def update_user(user_id: int, full_name: str = None, role: str = None):
    """Update a user's full name and/or role. Returns (success, message)."""
    try:
        with get_connection() as conn:
            if full_name is not None:
                conn.execute(
                    "UPDATE users SET full_name = ? WHERE user_id = ?", (full_name.strip(), user_id)
                )
            if role is not None:
                if role not in ("admin", "user"):
                    return False, "Role must be 'admin' or 'user'."
                conn.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
        return True, "User updated successfully."
    except Exception as exc:
        return False, f"Unexpected database error while updating user: {exc}"


def set_user_active(user_id: int, is_active: bool):
    """Enable / disable a user account (soft-disable, used instead of delete)."""
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET is_active = ? WHERE user_id = ?", (1 if is_active else 0, user_id)
            )
        return True, "User status updated."
    except Exception as exc:
        return False, f"Unexpected database error while updating status: {exc}"


def reset_password(user_id: int, new_password: str):
    """Admin-triggered password reset -- no knowledge of the old password required."""
    if not new_password or len(new_password) < 4:
        return False, "New password must be at least 4 characters long."
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE user_id = ?",
                (auth.hash_password(new_password), user_id),
            )
        return True, "Password reset successfully."
    except Exception as exc:
        return False, f"Unexpected database error while resetting password: {exc}"


def verify_login(username: str, password: str):
    """
    Validate credentials against the users table.

    Returns one of:
      - dict(user row)  -> login successful
      - "disabled"      -> account exists but has been disabled by an admin
      - "pending"       -> self-registered account awaiting admin approval
      - None            -> username not found or password incorrect
    """
    user = get_user_by_username((username or "").strip())
    if user is None:
        return None
    if not auth.verify_password(password, user["password_hash"]):
        return None
    if not user["is_active"]:
        return "disabled"
    if not user.get("is_approved", 1):
        return "pending"
    return user


# ---------------------------------------------------------------------------
# LAB ENTRY functions
# ---------------------------------------------------------------------------
def add_entry(data: dict):
    """
    Insert a new lab entry. `data` must contain all the fields listed below.
    Returns (success: bool, message_or_entry_id).
    """
    required_keys = [
        "entry_date", "user_name", "professor_name", "lab_name", "project_name",
        "entry_time", "exit_time", "total_hours", "lab_activity",
        "lab_partner_name", "lab_partner_contribution", "notes",
    ]
    missing = [k for k in required_keys if k not in data]
    if missing:
        return False, f"Internal error: missing fields {missing}"

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO lab_entries (
                    entry_date, user_name, professor_name, lab_name, project_name,
                    entry_time, exit_time, total_hours, lab_activity,
                    lab_partner_name, lab_partner_contribution, notes, created_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["entry_date"], data["user_name"], data["professor_name"],
                    data["lab_name"], data["project_name"], data["entry_time"],
                    data["exit_time"], data["total_hours"], data["lab_activity"],
                    data["lab_partner_name"], data["lab_partner_contribution"],
                    data["notes"], now_str(),
                ),
            )
        return True, cursor.lastrowid
    except Exception as exc:
        return False, f"Unexpected database error while saving entry: {exc}"


def update_entry(entry_id: int, data: dict):
    """Update an existing lab entry by entry_id. Returns (success, message)."""
    try:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE lab_entries SET
                    entry_date = ?, professor_name = ?, lab_name = ?, project_name = ?,
                    entry_time = ?, exit_time = ?, total_hours = ?, lab_activity = ?,
                    lab_partner_name = ?, lab_partner_contribution = ?, notes = ?
                WHERE entry_id = ?
                """,
                (
                    data["entry_date"], data["professor_name"], data["lab_name"],
                    data["project_name"], data["entry_time"], data["exit_time"],
                    data["total_hours"], data["lab_activity"], data["lab_partner_name"],
                    data["lab_partner_contribution"], data["notes"], entry_id,
                ),
            )
        return True, "Entry updated successfully."
    except Exception as exc:
        return False, f"Unexpected database error while updating entry: {exc}"


def delete_entry(entry_id: int):
    """Permanently delete a lab entry. Returns (success, message)."""
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM lab_entries WHERE entry_id = ?", (entry_id,))
        return True, "Entry deleted successfully."
    except Exception as exc:
        return False, f"Unexpected database error while deleting entry: {exc}"


def get_entry_by_id(entry_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM lab_entries WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        return dict(row) if row else None


def get_entries(filters: dict = None) -> pd.DataFrame:
    """
    Return lab_entries as a DataFrame, optionally filtered.

    Supported filter keys (all optional):
      professor_name, lab_name, project_name  -> case-insensitive substring match
      date_from, date_to                      -> ISO date strings (YYYY-MM-DD)
    """
    query = "SELECT * FROM lab_entries WHERE 1=1"
    params = []

    if filters:
        if filters.get("professor_name"):
            query += " AND professor_name LIKE ?"
            params.append(f"%{filters['professor_name']}%")
        if filters.get("lab_name"):
            query += " AND lab_name LIKE ?"
            params.append(f"%{filters['lab_name']}%")
        if filters.get("project_name"):
            query += " AND project_name LIKE ?"
            params.append(f"%{filters['project_name']}%")
        if filters.get("date_from"):
            query += " AND entry_date >= ?"
            params.append(filters["date_from"])
        if filters.get("date_to"):
            query += " AND entry_date <= ?"
            params.append(filters["date_to"])

    query += " ORDER BY entry_date DESC, entry_id DESC"

    with get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return df