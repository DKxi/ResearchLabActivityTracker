"""
auth.py
-------
Authentication helper module for the Research Lab Activity Tracker.

Responsibilities of this module:
    1. Securely hash and verify user passwords using bcrypt.
    2. Provide small, well-tested helper functions that the rest of the
       application (app.py) calls into -- the UI layer never touches
       bcrypt directly, which keeps the security logic in one place.

Why bcrypt?
    bcrypt automatically generates a random salt per password and is a
    deliberately slow ("work factor" tunable) hashing algorithm, which
    makes brute-force / rainbow-table attacks far harder than a single
    fast hash like plain SHA-256. This satisfies the requirement to use
    "bcrypt or hashlib" -- we chose bcrypt because it is the stronger,
    purpose-built option for password storage.
"""

import bcrypt


def hash_password(plain_text_password: str) -> str:
    """
    Hash a plain-text password using bcrypt with a freshly generated salt.

    Args:
        plain_text_password: The user's password, as typed into the form.

    Returns:
        A UTF-8 string containing the bcrypt hash (this is what gets
        stored in the `users.password_hash` column). The salt is embedded
        inside the hash itself, so we never need to store it separately.
    """
    # bcrypt works on bytes, so encode the string first.
    password_bytes = plain_text_password.encode("utf-8")
    # gensalt() creates a new random salt every single call -- this is
    # what makes two users with the same password get different hashes.
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(password_bytes, salt)
    # Store hashes as text in SQLite, so decode back to a normal string.
    return hashed_bytes.decode("utf-8")


def verify_password(plain_text_password: str, stored_hash: str) -> bool:
    """
    Check a plain-text password against a previously stored bcrypt hash.

    Args:
        plain_text_password: The password the user just typed in.
        stored_hash: The bcrypt hash retrieved from the `users` table.

    Returns:
        True if the password matches the hash, False otherwise. Any
        unexpected/malformed hash is treated as a failed login rather
        than raising an exception, so a corrupt DB row can never crash
        the login page.
    """
    if not plain_text_password or not stored_hash:
        return False
    try:
        return bcrypt.checkpw(
            plain_text_password.encode("utf-8"),
            stored_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # ValueError is raised by bcrypt when `stored_hash` is not a
        # valid bcrypt hash (e.g. corrupted data) -- fail safe.
        return False


def init_session_state(st):
    """
    Ensure every session-state key the app relies on exists, with a safe
    default. Call this once at the very top of app.py on every rerun.

    Args:
        st: the imported `streamlit` module (passed in rather than
            imported here so this module has zero Streamlit dependency
            and stays easy to unit test in isolation).
    """
    defaults = {
        "logged_in": False,
        "user_id": None,
        "username": None,
        "full_name": None,
        "role": None,
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def log_user_in(st, user_row: dict) -> None:
    """Populate session state after a successful login."""
    st.session_state.logged_in = True
    st.session_state.user_id = user_row["user_id"]
    st.session_state.username = user_row["username"]
    st.session_state.full_name = user_row["full_name"]
    st.session_state.role = user_row["role"]


def log_user_out(st) -> None:
    """Clear session state on logout, returning the user to the login page."""
    st.session_state.logged_in = False
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.full_name = None
    st.session_state.role = None


def is_admin(st) -> bool:
    """Convenience check used throughout app.py to gate admin-only UI."""
    return st.session_state.get("role") == "admin"
