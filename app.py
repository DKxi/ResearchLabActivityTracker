"""
app.py
======
Research Lab Activity Tracker — main Streamlit application.

Run with:
    streamlit run app.py

Structure of this file
-----------------------
1. Page config + session-state bootstrap
2. Small shared helpers (time math, validation, CSV export, etc.)
3. Login page
4. One render_*_tab() function per tab:
     Tab 1 - New Entry
     Tab 2 - Entry History
     Tab 3 - Totals Dashboard
     Tab 4 - Professor Summary
     Tab 5 - Lab Partner Contributions
     Tab 6 - User Management (admin only)
5. main() that wires everything together based on session state.

All database access goes through the `database` module; all password /
session helpers go through the `auth` module. This file is the UI layer only.
"""

import math
import uuid
from datetime import datetime, date, time, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import database as db


# ---------------------------------------------------------------------------
# Page configuration (must be the first Streamlit call in the script)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Research Lab Activity Tracker",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# A tiny bit of CSS polish for a cleaner, more "modern" look.
st.markdown(
    """
    <style>
        .block-container {padding-top: 2rem;}
        div[data-testid="stMetricValue"] {font-size: 1.6rem;}
        .stTabs [data-baseweb="tab-list"] {gap: 6px;}
        .stTabs [data-baseweb="tab"] {
            padding: 8px 16px; border-radius: 6px 6px 0 0;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# Make sure the database file + tables exist before anything else runs.
# This is idempotent and safe to call on every single rerun.
try:
    db.init_database()
except Exception as exc:
    st.error(f"❌ Fatal error initializing the database: {exc}")
    st.stop()

# Ensure every session-state key the app relies on has a default value.
auth.init_session_state(st)


# ---------------------------------------------------------------------------
# Shared helper functions
# ---------------------------------------------------------------------------
def calculate_hours(entry_time: time, exit_time: time) -> float:
    """
    Compute the elapsed hours between two datetime.time objects on the same
    calendar day. Returns a (possibly negative) float; callers are expected
    to validate that the result is positive before saving.
    """
    dummy_day = date(2000, 1, 1)
    start_dt = datetime.combine(dummy_day, entry_time)
    end_dt = datetime.combine(dummy_day, exit_time)
    delta = end_dt - start_dt
    return delta.total_seconds() / 3600.0


def validate_entry_form(professor_name, lab_name, project_name, lab_activity,
                         entry_time, exit_time) -> list:
    """
    Validate the New Entry form. Returns a list of human-readable error
    strings; an empty list means the form is valid and safe to save.
    """
    errors = []
    if not professor_name or not professor_name.strip():
        errors.append("Professor Name is required.")
    if not lab_name or not lab_name.strip():
        errors.append("Lab Name is required.")
    if not project_name or not project_name.strip():
        errors.append("Project Name is required.")
    if not lab_activity or not lab_activity.strip():
        errors.append("Lab Activity Performed is required.")

    hours = calculate_hours(entry_time, exit_time)
    if hours <= 0:
        errors.append("Exit Time must be after Entry Time.")
    return errors


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Convert a DataFrame to CSV bytes suitable for st.download_button."""
    return df.to_csv(index=False).encode("utf-8")


def show_success_toast(message: str, duration_seconds: float = 5.0, fade_seconds: float = 1.0):
    """
    Render a transient "Saved!" style popup in the corner of the screen that
    stays fully visible for `duration_seconds`, then smoothly fades out over
    `fade_seconds`, instead of a permanent st.success() banner.

    Implementation notes:
    - Streamlit has no built-in "toast with a custom duration", so this is a
      small hand-rolled HTML/CSS notification injected via st.markdown.
    - A fresh, random element id is generated on every call. This matters:
      if the same id/markup were reused across reruns, the browser can treat
      it as "the same element" and skip replaying the CSS animation. A new
      id guarantees the fade always restarts cleanly.
    - This only works if the page *doesn't* immediately rerun again right
      after this is drawn (a rerun would erase it before the timer finishes).
      That's why the Save Entry flow below defers its rerun until the
      *next* user interaction rather than calling st.rerun() itself.
    """
    toast_id = f"toast_{uuid.uuid4().hex}"
    total = duration_seconds + fade_seconds
    visible_pct = (duration_seconds / total) * 100
    st.markdown(
        f"""
        <style>
        @keyframes fadeout_{toast_id} {{
            0%   {{ opacity: 1; }}
            {visible_pct:.1f}% {{ opacity: 1; }}
            100% {{ opacity: 0; }}
        }}
        #{toast_id} {{
            position: fixed;
            top: 80px;
            right: 28px;
            z-index: 9999;
            background-color: #16a34a;
            color: #ffffff;
            padding: 14px 22px;
            border-radius: 10px;
            box-shadow: 0 6px 18px rgba(0,0,0,0.25);
            font-size: 0.95rem;
            font-weight: 500;
            opacity: 1;
            animation: fadeout_{toast_id} {total}s ease forwards;
            pointer-events: none;
        }}
        </style>
        <div id="{toast_id}">✅ {message}</div>
        """,
        unsafe_allow_html=True,
    )


def paginate_dataframe(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    """
    Render page-size / page-number controls and return the DataFrame slice
    for the currently selected page. Shared by several tabs.
    """
    col_a, col_b = st.columns([1, 3])
    with col_a:
        page_size = st.selectbox(
            "Rows per page", [10, 25, 50, 100], index=1, key=f"{key_prefix}_page_size"
        )
    total_pages = max(1, math.ceil(len(df) / page_size))
    with col_b:
        page_num = st.number_input(
            f"Page (1 of {total_pages})", min_value=1, max_value=total_pages,
            value=1, step=1, key=f"{key_prefix}_page_num",
        )
    start = (page_num - 1) * page_size
    end = start + page_size
    return df.iloc[start:end]

ENTRY_DISPLAY_COLUMNS = [
    "entry_id", "entry_date", "user_name", "professor_name", "lab_name",
    "project_name", "entry_time", "exit_time", "total_hours",
    "lab_partner_name",
]


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------
def render_login_page():
    """Render the login form. On success, populates session state and reruns."""
    st.markdown(
        "<h1 style='text-align:center;'>🔬 Research Lab Activity Tracker</h1>",
        unsafe_allow_html=True,
    )
    st.markdown("<h4 style='text-align:center; color: gray;'>Please sign in to continue</h4>", unsafe_allow_html=True)

    # If we just got redirected here after a successful sign-up, show that
    # confirmation exactly once. (Same "flag in session_state, pop and
    # display" pattern used for the Save Entry toast -- this message is
    # shown via a normal st.success(), which is fine here since nothing
    # forces another rerun right after it, so the user has time to read it.)
    if st.session_state.get("_signup_pending_message"):
        st.success(st.session_state.pop("_signup_pending_message"))

    _, center_col, _ = st.columns([1, 1.2, 1])
    with center_col:
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("🔓 Login", use_container_width=True, type="primary")

        if submitted:
            if not username or not password:
                st.error("⚠️ Please enter both username and password.")
            else:
                try:
                    result = db.verify_login(username, password)
                except Exception as exc:
                    st.error(f"❌ Login failed due to a database error: {exc}")
                    result = None

                if result == "disabled":
                    st.error("🚫 This account has been disabled. Please contact an administrator.")
                elif result == "pending":
                    st.warning(
                        "⏳ Your account request is still awaiting admin approval. "
                        "Please check back later or contact an administrator."
                    )
                elif result is None:
                    st.error("❌ Invalid username or password.")
                else:
                    auth.log_user_in(st, result)
                    st.success(f"✅ Welcome back, {result['full_name'] or result['username']}!")
                    st.rerun()

        st.divider()
        st.markdown("<p style='text-align:center; color: gray;'>Don't have an account yet?</p>", unsafe_allow_html=True)
        if st.button("📝 Create an Account", use_container_width=True):
            st.session_state["show_signup"] = True
            st.rerun()


def render_signup_page():
    """
    Self-service account creation page. Anyone can submit a request here,
    but for security:
      - This path can ONLY ever create role='user' accounts -- granting
        admin rights still requires an existing admin to do it from the
        User Management tab.
      - New accounts are created with is_approved=False, meaning they
        cannot log in until an admin approves them from the new
        "Pending Approvals" panel in User Management.
    """
    st.markdown(
        "<h1 style='text-align:center;'>🔬 Research Lab Activity Tracker</h1>",
        unsafe_allow_html=True,
    )
    st.markdown("<h4 style='text-align:center; color: gray;'>Create a new account</h4>", unsafe_allow_html=True)
    st.caption("Your request will need to be approved by an administrator before you can log in.")

    _, center_col, _ = st.columns([1, 1.2, 1])
    with center_col:
        with st.form("signup_form", clear_on_submit=False):
            full_name = st.text_input("Full Name", key="signup_full_name")
            new_username = st.text_input("Choose a Username", key="signup_username")
            new_password = st.text_input("Choose a Password", type="password", key="signup_password")
            confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm")
            submitted = st.form_submit_button("✅ Submit Account Request", use_container_width=True, type="primary")

        if submitted:
            if not new_username.strip() or not new_password:
                st.error("⚠️ Username and password are required.")
            elif len(new_password) < 4:
                st.error("⚠️ Password must be at least 4 characters long.")
            elif new_password != confirm_password:
                st.error("⚠️ Passwords do not match.")
            else:
                try:
                    success, msg = db.create_user(
                        new_username.strip(), new_password, "user", full_name.strip(),
                        is_approved=False,
                    )
                except Exception as exc:
                    success, msg = False, f"Unexpected error creating account: {exc}"

                if success:
                    # Do NOT log the user in -- the account is pending until
                    # an admin approves it. Send them back to the login page
                    # with a one-time confirmation message instead.
                    st.session_state["show_signup"] = False
                    st.session_state["_signup_pending_message"] = (
                        f"✅ Account request submitted for '{new_username.strip()}'. "
                        "An administrator must approve it before you can log in."
                    )
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")

        st.divider()
        if st.button("← Back to Login", use_container_width=True):
            st.session_state["show_signup"] = False
            st.rerun()


# ---------------------------------------------------------------------------
# Tab 1 — New Entry
# ---------------------------------------------------------------------------
NEW_ENTRY_KEYS = [
    "ne_entry_date", "ne_professor_name", "ne_lab_name", "ne_project_name",
    "ne_entry_time", "ne_exit_time", "ne_lab_activity", "ne_partner_name",
    "ne_partner_contribution", "ne_notes",
]


def clear_new_entry_form():
    """
    on_click callback for the 'Clear Form' button.

    IMPORTANT: this must run as an on_click callback, not as a plain
    `if button_clicked:` check inside the function body. Streamlit raises
    a StreamlitAPIException if you try to delete/modify
    st.session_state[key] for a key whose widget has *already* been drawn
    earlier in the same script run -- which is exactly what was happening
    before (the widgets were created above, then this ran afterwards in
    the same run). on_click callbacks execute *before* the rest of the
    script (and its widgets) are redrawn, so the deletion is safe here and
    the widgets correctly reset to their defaults on the next render.
    """
    for key in NEW_ENTRY_KEYS:
        if key in st.session_state:
            st.session_state["ne_professor_name"] = ""
            st.session_state["ne_lab_name"] = ""
            st.session_state["ne_project_name"] = ""
            st.session_state["ne_entry_time"] = st.session_state.get("ne_entry_time", time(9, 0))
            st.session_state["ne_exit_time"] = st.session_state.get("ne_exit_time", time(17, 0))
            st.session_state["ne_lab_activity"] = ""
            st.session_state["ne_partner_name"] = ""
            st.session_state["ne_partner_contribution"] = ""
            st.session_state["ne_notes"] = ""
            st.session_state["ne_entry_date"] = st.session_state.get("ne_entry_date", date.today())
            del st.session_state[key]


def _save_new_entry_callback():
    """
    on_click callback for the 'Save Entry' button. Reads the submitted
    values directly out of session_state (Streamlit syncs widget values
    into session_state before running callbacks), validates them, saves to
    the database, and -- on success -- clears the form via
    clear_new_entry_form(). Doing all of this in a callback (instead of in
    the main render function) is what makes the form-clearing safe; see
    the note on clear_new_entry_form() above.

    Results are stashed in session_state flags ("_ne_toast" / "_ne_errors")
    so the main render function can display them once the script resumes.
    """
    professor_name = st.session_state.get("ne_professor_name", "")
    lab_name = st.session_state.get("ne_lab_name", "")
    project_name = st.session_state.get("ne_project_name", "")
    lab_activity = st.session_state.get("ne_lab_activity", "")
    entry_time = st.session_state.get("ne_entry_time", time(9, 0))
    exit_time = st.session_state.get("ne_exit_time", time(17, 0))
    entry_date = st.session_state.get("ne_entry_date", date.today())
    lab_partner_name = st.session_state.get("ne_partner_name", "")
    lab_partner_contribution = st.session_state.get("ne_partner_contribution", "")
    notes = st.session_state.get("ne_notes", "")

    errors = validate_entry_form(
        professor_name, lab_name, project_name, lab_activity, entry_time, exit_time
    )
    if errors:
        st.session_state["_ne_errors"] = errors
        return

    computed_hours = calculate_hours(entry_time, exit_time)
    data = {
        "entry_date": entry_date.strftime("%Y-%m-%d"),
        "user_name": st.session_state.username,
        "professor_name": professor_name.strip(),
        "lab_name": lab_name.strip(),
        "project_name": project_name.strip(),
        "entry_time": entry_time.strftime("%H:%M"),
        "exit_time": exit_time.strftime("%H:%M"),
        "total_hours": round(computed_hours, 2),
        "lab_activity": lab_activity.strip(),
        "lab_partner_name": lab_partner_name.strip() if lab_partner_name else "",
        "lab_partner_contribution": lab_partner_contribution.strip() if lab_partner_contribution else "",
        "notes": notes.strip() if notes else "",
    }
    success, result = db.add_entry(data)
    if success:
        st.session_state["_ne_toast"] = f"Entry #{result} saved successfully!"
        clear_new_entry_form()
    else:
        st.session_state["_ne_errors"] = [f"Could not save entry: {result}"]


def render_new_entry_tab():
    st.subheader("📝 Log a New Lab Visit")
    st.caption("Fields marked with * are required.")

    # Surface whatever the Save callback (above) decided last time, then
    # immediately clear the flag so it only ever shows once. Crucially,
    # we do NOT call st.rerun() anywhere in this flow -- the page just sits
    # here normally rendered, which is what lets the 5-second toast
    # animation actually finish playing instead of being wiped out instantly.
    if st.session_state.get("_ne_toast"):
        show_success_toast(st.session_state.pop("_ne_toast"))
    if st.session_state.get("_ne_errors"):
        for err in st.session_state.pop("_ne_errors"):
            st.error(f"⚠️ {err}")

    col1, col2 = st.columns(2)
    with col1:
        entry_date = st.date_input("Entry Date *", value=date.today(), key="ne_entry_date")
        professor_name = st.text_input("Professor Name *", key="ne_professor_name", placeholder="e.g. Dr. Smith")
        lab_name = st.text_input("Lab Name *", key="ne_lab_name", placeholder="e.g. Materials Science Lab")
        project_name = st.text_input("Project Name *", key="ne_project_name", placeholder="e.g. Polymer Research")
    with col2:
        entry_time = st.time_input("Entry Time *", value=time(9, 0), key="ne_entry_time")
        exit_time = st.time_input("Exit Time *", value=time(17, 0), key="ne_exit_time")
        lab_partner_name = st.text_input("Lab Partner Name (optional)", key="ne_partner_name")

    # Live, auto-calculated total hours (recomputed on every rerun, which
    # happens automatically whenever a widget above changes).
    computed_hours = calculate_hours(entry_time, exit_time)
    if computed_hours > 0:
        st.info(f"⏱️ **Auto-calculated Total Hours: {computed_hours:.2f} hrs**")
    else:
        st.warning("⚠️ Exit Time must be after Entry Time to calculate hours.")

    lab_activity = st.text_area(
        "Lab Activity Performed *", key="ne_lab_activity", height=110,
        placeholder="Describe the work performed during this lab visit...",
    )
    lab_partner_contribution = st.text_area(
        "Lab Partner Contribution", key="ne_partner_contribution", height=90,
        placeholder="What did your lab partner contribute, if any?",
    )
    notes = st.text_area("Additional Notes", key="ne_notes", height=90)

    col_save, col_clear = st.columns(2)
    col_save.button(
        "💾 Save Entry", type="primary", use_container_width=True,
        on_click=_save_new_entry_callback,
    )
    col_clear.button(
        "🔄 Clear Form", use_container_width=True,
        on_click=clear_new_entry_form,
    )


# ---------------------------------------------------------------------------
# Tab 2 — Entry History
# ---------------------------------------------------------------------------
def render_entry_details_and_actions(entry: dict):
    """Show full details for one entry plus View/Edit/Delete controls."""
    print("see1111=====================", entry['user_name'])
    print("see2222=====================",st.session_state.get("user_id"))
    #print("see3333=====================", entry['user_id'])
    my_user = db.get_user_by_username(entry['user_name'])

    print("see3333=====================", my_user['user_id'])


    if auth.is_user(st, my_user['user_id']) is False and auth.is_admin(st) is False:
        st.warning("⚠️ You can only view your own entries. Please contact an administrator if you believe this is an error.")
        return
    

    st.markdown(f"#### Entry #{entry['entry_id']} — {entry['lab_name']} ({entry['entry_date']})")

    detail_cols = st.columns(3)
    detail_cols[0].markdown(f"**Logged by:** {entry['user_name']}")
    detail_cols[0].markdown(f"**Professor:** {entry['professor_name']}")
    detail_cols[1].markdown(f"**Project:** {entry['project_name']}")
    detail_cols[1].markdown(f"**Time:** {entry['entry_time']} → {entry['exit_time']}")
    detail_cols[2].markdown(f"**Total Hours:** {entry['total_hours']:.2f}")
    detail_cols[2].markdown(f"**Lab Partner:** {entry['lab_partner_name'] or '—'}")

    st.markdown("**Lab Activity Performed:**")
    st.write(entry["lab_activity"] or "—")
    if entry["lab_partner_contribution"]:
        st.markdown("**Lab Partner Contribution:**")
        st.write(entry["lab_partner_contribution"])
    if entry["notes"]:
        st.markdown("**Notes:**")
        st.write(entry["notes"])
    st.caption(f"Created: {entry['created_timestamp']}")

    st.divider()
    action_cols = st.columns(2)

    # ---- Edit -------------------------------------------------------------
    with action_cols[0]:
        with st.expander("✏️ Edit this entry"):
            with st.form(f"edit_form_{entry['entry_id']}"):
                e_date = st.date_input(
                    "Entry Date", value=datetime.strptime(entry["entry_date"], "%Y-%m-%d").date(),
                    key=f"edit_date_{entry['entry_id']}",
                )
                e_prof = st.text_input("Professor Name", value=entry["professor_name"], key=f"edit_prof_{entry['entry_id']}")
                e_lab = st.text_input("Lab Name", value=entry["lab_name"], key=f"edit_lab_{entry['entry_id']}")
                e_proj = st.text_input("Project Name", value=entry["project_name"], key=f"edit_proj_{entry['entry_id']}")
                e_entry_time = st.time_input(
                    "Entry Time", value=datetime.strptime(entry["entry_time"], "%H:%M").time(),
                    key=f"edit_etime_{entry['entry_id']}",
                )
                e_exit_time = st.time_input(
                    "Exit Time", value=datetime.strptime(entry["exit_time"], "%H:%M").time(),
                    key=f"edit_xtime_{entry['entry_id']}",
                )
                e_activity = st.text_area("Lab Activity Performed", value=entry["lab_activity"], key=f"edit_act_{entry['entry_id']}")
                e_partner = st.text_input("Lab Partner Name", value=entry["lab_partner_name"] or "", key=f"edit_partner_{entry['entry_id']}")
                e_contrib = st.text_area(
                    "Lab Partner Contribution", value=entry["lab_partner_contribution"] or "",
                    key=f"edit_contrib_{entry['entry_id']}",
                )
                e_notes = st.text_area("Notes", value=entry["notes"] or "", key=f"edit_notes_{entry['entry_id']}")

                update_clicked = st.form_submit_button("💾 Update Entry", type="primary")

                if update_clicked:
                    errors = validate_entry_form(e_prof, e_lab, e_proj, e_activity, e_entry_time, e_exit_time)
                    if errors:
                        for err in errors:
                            st.error(f"⚠️ {err}")
                    else:
                        new_hours = calculate_hours(e_entry_time, e_exit_time)
                        update_data = {
                            "entry_date": e_date.strftime("%Y-%m-%d"),
                            "professor_name": e_prof.strip(),
                            "lab_name": e_lab.strip(),
                            "project_name": e_proj.strip(),
                            "entry_time": e_entry_time.strftime("%H:%M"),
                            "exit_time": e_exit_time.strftime("%H:%M"),
                            "total_hours": round(new_hours, 2),
                            "lab_activity": e_activity.strip(),
                            "lab_partner_name": e_partner.strip() if e_partner else "",
                            "lab_partner_contribution": e_contrib.strip() if e_contrib else "",
                            "notes": e_notes.strip() if e_notes else "",
                        }
                        success, msg = db.update_entry(entry["entry_id"], update_data)
                        if success:
                            st.success(f"✅ {msg}")
                            st.rerun()
                        else:
                            st.error(f"❌ {msg}")

    # ---- Delete (admin only) ----------------------------------------------
    with action_cols[1]:
        if auth.is_admin(st):
            with st.expander("🗑️ Delete this entry (Admin only)"):
                st.warning("This action is permanent and cannot be undone.")
                confirm = st.checkbox("I confirm I want to delete this entry.", key=f"confirm_del_{entry['entry_id']}")
                if st.button("🗑️ Delete Entry", key=f"del_btn_{entry['entry_id']}", disabled=not confirm):
                    success, msg = db.delete_entry(entry["entry_id"])
                    if success:
                        st.success(f"✅ {msg}")
                        st.rerun()
                    else:
                        st.error(f"❌ {msg}")
        else:
            st.info("🔒 Only administrators can delete entries.")


def render_history_tab():
    st.subheader("📋 Entry History")

    with st.expander("🔍 Search & Filter", expanded=True):
        c1, c2, c3 = st.columns(3)
        f_professor = c1.text_input("Professor Name", key="hist_f_professor")
        f_lab = c2.text_input("Lab Name", key="hist_f_lab")
        f_project = c3.text_input("Project Name", key="hist_f_project")

        c4, c5, c6 = st.columns(3)
        use_date_filter = c4.checkbox("Filter by date range", key="hist_use_date")
        f_date_from = c5.date_input(
            "From", value=date.today() - timedelta(days=30), key="hist_date_from", disabled=not use_date_filter
        )
        f_date_to = c6.date_input("To", value=date.today(), key="hist_date_to", disabled=not use_date_filter)

    my_user = db.get_user_by_id( st.session_state.get("user_id"))

    print("see=======================", my_user['username'])
    print("see=======================", st.session_state.get("user_id"))
    print("see=======================", my_user)
    
    filters = {
        "professor_name": f_professor.strip() if f_professor else "",
        "lab_name": f_lab.strip() if f_lab else "",
        "project_name": f_project.strip() if f_project else "",
        "user_name": my_user['username'] if my_user else None,
        "role": my_user['role'] if my_user else None,
    }


    if use_date_filter:
        filters["date_from"] = f_date_from.strftime("%Y-%m-%d")
        filters["date_to"] = f_date_to.strftime("%Y-%m-%d")

    try:
        df = db.get_entries(filters)
    except Exception as exc:
        st.error(f"❌ Could not load entries: {exc}")
        return

    if df.empty:
        st.info("No entries match the current filters.")
        return

    st.caption(f"Showing **{len(df)}** matching entr{'y' if len(df) == 1 else 'ies'} "
               f"(click any column header in the table to sort).")

    page_df = paginate_dataframe(df, key_prefix="hist")
    st.dataframe(page_df[ENTRY_DISPLAY_COLUMNS], use_container_width=True, hide_index=True)

    st.download_button(
        "📥 Export Filtered Results to CSV",
        data=df_to_csv_bytes(df),
        file_name=f"lab_entries_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    st.divider()
    st.markdown("##### 🔎 View / Edit / Delete a Specific Entry")
    entry_ids = df["entry_id"].tolist()
    selected_id = st.selectbox("Select Entry ID", entry_ids, key="hist_selected_entry")
    if selected_id:
        entry = db.get_entry_by_id(int(selected_id))
        if entry:
            render_entry_details_and_actions(entry)


# ---------------------------------------------------------------------------
# Tab 3 — Totals Dashboard
# ---------------------------------------------------------------------------
def render_dashboard_tab():
    st.subheader("📊 Totals Dashboard")

    try:
        df = db.get_entries()
    except Exception as exc:
        st.error(f"❌ Could not load dashboard data: {exc}")
        return

    if df.empty:
        st.info("No lab entries have been logged yet. Add one from the 'New Entry' tab to see analytics here.")
        return

    total_visits = len(df)
    total_hours = df["total_hours"].sum()
    avg_hours = total_hours / total_visits if total_visits else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Lab Visits", f"{total_visits:,}")
    m2.metric("Total Hours Logged", f"{total_hours:,.1f} hrs")
    m3.metric("Avg Hours / Visit", f"{avg_hours:.2f} hrs")
    m4.metric("Active Projects", f"{df['project_name'].nunique():,}")

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### Hours by Professor")
        prof_hours = (
            df.groupby("professor_name")["total_hours"].sum().reset_index()
            .sort_values("total_hours", ascending=False)
        )
        fig = px.bar(prof_hours, x="professor_name", y="total_hours",
                     labels={"professor_name": "Professor", "total_hours": "Total Hours"},
                     color="total_hours", color_continuous_scale="Blues")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("##### Hours by Project")
        proj_hours = df.groupby("project_name")["total_hours"].sum().reset_index()
        fig2 = px.pie(proj_hours, names="project_name", values="total_hours", hole=0.35)
        st.plotly_chart(fig2, use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("##### Hours by Month")
        month_df = df.copy()
        month_df["month"] = pd.to_datetime(month_df["entry_date"]).dt.to_period("M").astype(str)
        month_hours = month_df.groupby("month")["total_hours"].sum().reset_index().sort_values("month")
        fig3 = px.line(month_hours, x="month", y="total_hours", markers=True,
                        labels={"month": "Month", "total_hours": "Total Hours"})
        st.plotly_chart(fig3, use_container_width=True)

    with col4:
        st.markdown("##### Hours by User")
        user_hours = (
            df.groupby("user_name")["total_hours"].sum().reset_index()
            .sort_values("total_hours", ascending=False)
        )
        fig4 = px.bar(user_hours, x="user_name", y="total_hours",
                      labels={"user_name": "User", "total_hours": "Total Hours"},
                      color="total_hours", color_continuous_scale="Greens")
        st.plotly_chart(fig4, use_container_width=True)


# ---------------------------------------------------------------------------
# Tab 4 — Professor Summary
# ---------------------------------------------------------------------------
def render_professor_summary_tab():
    st.subheader("👨‍🏫 Professor Summary")

    try:
        df = db.get_entries()
    except Exception as exc:
        st.error(f"❌ Could not load data: {exc}")
        return

    if df.empty:
        st.info("No lab entries have been logged yet.")
        return

    search = st.text_input("🔍 Filter by Professor Name", key="prof_summary_search")
    if search:
        df = df[df["professor_name"].str.contains(search, case=False, na=False)]
        if df.empty:
            st.info("No professors match that search.")
            return

    rows = []
    for prof, group in df.groupby("professor_name"):
        top_activities = group["lab_activity"].value_counts().head(3)
        activities_str = "; ".join(
            f"{act[:60]}{'…' if len(act) > 60 else ''} ({cnt}x)"
            for act, cnt in top_activities.items() if act
        ) or "—"
        rows.append(
            {
                "Professor Name": prof,
                "Number of Visits": len(group),
                "Total Hours": round(group["total_hours"].sum(), 2),
                "Most Common Activities": activities_str,
            }
        )

    summary_df = pd.DataFrame(rows).sort_values("Total Hours", ascending=False)
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    st.download_button(
        "📥 Export Professor Summary to CSV",
        data=df_to_csv_bytes(summary_df),
        file_name="professor_summary.csv",
        mime="text/csv",
    )

    fig = px.bar(summary_df, x="Professor Name", y="Total Hours", color="Number of Visits",
                 color_continuous_scale="Purples")
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Tab 5 — Lab Partner Contributions
# ---------------------------------------------------------------------------
def render_partner_tab():
    st.subheader("🤝 Lab Partner Contributions")

    try:
        df = db.get_entries()
    except Exception as exc:
        st.error(f"❌ Could not load data: {exc}")
        return

    df = df[df["lab_partner_name"].fillna("").str.strip() != ""]
    if df.empty:
        st.info("No lab entries have recorded a lab partner yet.")
        return

    search = st.text_input("🔍 Search by Lab Partner Name", key="partner_search")
    if search:
        df = df[df["lab_partner_name"].str.contains(search, case=False, na=False)]
        if df.empty:
            st.info("No lab partners match that search.")
            return

    rows = []
    for partner, group in df.groupby("lab_partner_name"):
        contributions = [c for c in group["lab_partner_contribution"].tolist() if c and c.strip()]
        summary = " | ".join(contributions[:3])
        if len(contributions) > 3:
            summary += f" (+{len(contributions) - 3} more)"
        rows.append(
            {
                "Lab Partner Name": partner,
                "Number of Collaborations": len(group),
                "Total Hours Together": round(group["total_hours"].sum(), 2),
                "Contribution Summaries": summary or "—",
            }
        )

    partner_df = pd.DataFrame(rows).sort_values("Number of Collaborations", ascending=False)
    st.dataframe(partner_df, use_container_width=True, hide_index=True)

    st.download_button(
        "📥 Export Lab Partner Summary to CSV",
        data=df_to_csv_bytes(partner_df),
        file_name="lab_partner_summary.csv",
        mime="text/csv",
    )

    fig = px.bar(partner_df, x="Lab Partner Name", y="Number of Collaborations",
                 color="Total Hours Together", color_continuous_scale="Oranges")
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Tab 6 — User Management (admin only)
# ---------------------------------------------------------------------------
def render_user_management_tab():
    st.subheader("👥 User Management")

    try:
        pending_count = len(db.get_pending_users())
    except Exception:
        pending_count = 0
    pending_label = f"⏳ Pending Approvals ({pending_count})" if pending_count else "⏳ Pending Approvals"

    sub_tabs = st.tabs([pending_label, "➕ Add User", "⚙️ Manage Users", "📈 User Activity Statistics"])

    # ---- Pending Approvals ---------------------------------------------------
    with sub_tabs[0]:
        st.caption("Accounts created via the public 'Create an Account' page land here "
                   "and cannot log in until you approve them.")
        try:
            pending_df = db.get_pending_users()
        except Exception as exc:
            st.error(f"❌ Could not load pending account requests: {exc}")
            pending_df = pd.DataFrame()

        if pending_df.empty:
            st.info("No pending account requests right now.")
        else:
            for _, row in pending_df.iterrows():
                pending_id = int(row["user_id"])
                with st.container(border=True):
                    info_col, approve_col, reject_col = st.columns([3, 1, 1])
                    info_col.markdown(
                        f"**{row['full_name'] or row['username']}**  \n"
                        f"@{row['username']} &nbsp;·&nbsp; requested {row['created_date']}"
                    )
                    if approve_col.button("✅ Approve", key=f"approve_{pending_id}", use_container_width=True):
                        success, msg = db.approve_user(pending_id)
                        st.success(msg) if success else st.error(msg)
                        st.rerun()
                    if reject_col.button("🗑️ Reject", key=f"reject_{pending_id}", use_container_width=True):
                        success, msg = db.reject_pending_user(pending_id)
                        st.success(msg) if success else st.error(msg)
                        st.rerun()

    # ---- Add User -----------------------------------------------------------
    with sub_tabs[1]:
        with st.form("add_user_form", clear_on_submit=True):
            new_username = st.text_input("Username")
            new_full_name = st.text_input("Full Name")
            new_password = st.text_input("Password", type="password")
            new_role = st.selectbox("Role", ["user", "admin"])
            add_clicked = st.form_submit_button("➕ Add User", type="primary")

        if add_clicked:
            if not new_username.strip() or not new_password:
                st.error("⚠️ Username and password are required.")
            else:
                # is_approved defaults to True here -- accounts added directly
                # by an admin are usable immediately, unlike public sign-ups.
                success, msg = db.create_user(new_username, new_password, new_role, new_full_name)
                if success:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")

    # ---- Manage Users (edit / disable / reset password) ---------------------
    with sub_tabs[2]:
        try:
            users_df = db.get_all_users_df()
        except Exception as exc:
            st.error(f"❌ Could not load users: {exc}")
            return

        st.dataframe(users_df, use_container_width=True, hide_index=True)

        if users_df.empty:
            return

        st.divider()
        selected_username = st.selectbox("Select a user to manage", users_df["username"].tolist(), key="um_selected")
        user_row = users_df[users_df["username"] == selected_username].iloc[0]
        user_id = int(user_row["user_id"])
        is_self = selected_username == st.session_state.username

        col_edit, col_status, col_pw = st.columns(3)

        # Edit full name / role
        with col_edit:
            st.markdown("**✏️ Edit Details**")
            edit_full_name = st.text_input("Full Name", value=user_row["full_name"] or "", key=f"um_fn_{user_id}")
            edit_role = st.selectbox(
                "Role", ["user", "admin"],
                index=0 if user_row["role"] == "user" else 1,
                key=f"um_role_{user_id}",
                disabled=is_self,  # prevent accidentally locking yourself out of admin
            )
            if st.button("💾 Save Changes", key=f"um_save_{user_id}"):
                success, msg = db.update_user(user_id, full_name=edit_full_name, role=edit_role)
                if success:
                    st.success(f"✅ {msg}")
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")

        # Account status: approve (if pending) / disable / enable
        with col_status:
            st.markdown("**🚦 Account Status**")
            if is_self:
                st.info("You cannot disable your own account.")
            elif user_row["status"] == "Pending Approval":
                st.caption("This account is still awaiting approval.")
                if st.button("✅ Approve User", key=f"um_approve_{user_id}"):
                    success, msg = db.approve_user(user_id)
                    st.success(msg) if success else st.error(msg)
                    st.rerun()
            elif user_row["status"] == "Active":
                if st.button("🚫 Disable User", key=f"um_disable_{user_id}"):
                    success, msg = db.set_user_active(user_id, False)
                    st.success(msg) if success else st.error(msg)
                    st.rerun()
            else:  # Disabled
                if st.button("✅ Enable User", key=f"um_enable_{user_id}"):
                    success, msg = db.set_user_active(user_id, True)
                    st.success(msg) if success else st.error(msg)
                    st.rerun()

        # Reset password
        with col_pw:
            st.markdown("**🔑 Reset Password**")
            new_pw = st.text_input("New Password", type="password", key=f"um_pw_{user_id}")
            if st.button("🔑 Reset Password", key=f"um_pwbtn_{user_id}"):
                if not new_pw:
                    st.error("⚠️ Please enter a new password.")
                else:
                    success, msg = db.reset_password(user_id, new_pw)
                    st.success(msg) if success else st.error(msg)

    # ---- User Activity Statistics -------------------------------------------
    with sub_tabs[3]:
        try:
            entries_df = db.get_entries()
        except Exception as exc:
            st.error(f"❌ Could not load activity statistics: {exc}")
            return

        if entries_df.empty:
            st.info("No lab entries logged yet.")
            return

        stats = (
            entries_df.groupby("user_name")
            .agg(Visits=("entry_id", "count"), Total_Hours=("total_hours", "sum"))
            .reset_index()
            .rename(columns={"user_name": "Username", "Total_Hours": "Total Hours"})
            .sort_values("Total Hours", ascending=False)
        )
        st.dataframe(stats, use_container_width=True, hide_index=True)
        fig = px.bar(stats, x="Username", y="Total Hours", color="Visits", color_continuous_scale="Teal")
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Main application shell (post-login)
# ---------------------------------------------------------------------------
def render_main_app():
    with st.sidebar:
        st.markdown(f"### 👋 Welcome, {st.session_state.full_name or st.session_state.username}")
        st.caption(f"Role: **{st.session_state.role.upper()}**")

        if auth.is_admin(st):
            try:
                pending_count = len(db.get_pending_users())
            except Exception:
                pending_count = 0
            if pending_count:
                st.warning(f"🔔 {pending_count} account request(s) awaiting your approval "
                           "(see the User Management tab).")

        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            auth.log_user_out(st)
            st.rerun()
        st.divider()
        st.caption("Research Lab Activity Tracker")
        st.caption("v1.0 — built with Streamlit + SQLite")

    st.title("🔬 Research Lab Activity Tracker")

    if auth.is_admin(st):
        tab_titles = [
            "📝 New Entry", "📋 Entry History", "📊 Totals Dashboard",
            "👨‍🏫 Professor Summary", "🤝 Lab Partner Contributions", "👥 User Management",
        ]
    else:
        tab_titles = [
            "📝 New Entry", "📋 Entry History", "📊 Totals Dashboard",
            "👨‍🏫 Professor Summary", "🤝 Lab Partner Contributions",
        ]

    tabs = st.tabs(tab_titles)

    with tabs[0]:
        render_new_entry_tab()
    with tabs[1]:
        render_history_tab()
    with tabs[2]:
        render_dashboard_tab()
    with tabs[3]:
        render_professor_summary_tab()
    with tabs[4]:
        render_partner_tab()
    if auth.is_admin(st):
        with tabs[5]:
            render_user_management_tab()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    if st.session_state.logged_in:
        render_main_app()
    elif st.session_state.get("show_signup"):
        render_signup_page()
    else:
        render_login_page()


if __name__ == "__main__":
    main()