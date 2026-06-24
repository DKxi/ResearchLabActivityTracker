# 🔬 Research Lab Activity Tracker

A production-ready Streamlit application for logging, tracking, and analyzing
research lab activity — built with **Streamlit**, **SQLite3**, **pandas**,
and **Plotly**.

---

## ✨ Features

- 🔐 **Login page** with role-based access (Admin / User), bcrypt-hashed passwords
- 📝 **New Entry** form with live auto-calculated total hours and validation
- 📋 **Entry History** with search/filter, sorting, pagination, CSV export,
  and view/edit/delete (delete is Admin-only)
- 📊 **Totals Dashboard** with bar/pie/line Plotly charts
- 👨‍🏫 **Professor Summary** with visit counts, total hours, and most common activities
- 🤝 **Lab Partner Contributions** summary, searchable and exportable
- 👥 **User Management** (Admin only): add, edit, disable, reset password, activity stats
- Automatic SQLite database initialization on first run (no manual setup step)

---

## 📦 Requirements

- Python 3.9+
- See `requirements.txt`:
  ```
  streamlit>=1.31.0
  bcrypt>=4.1.2
  pandas>=2.1.0
  plotly>=5.18.0
  ```

---

## 🚀 Setup & Run Instructions

1. **Unzip / place the files** in a folder, e.g. `research_lab_tracker/`.
   You should have:
   ```
   research_lab_tracker/
   ├── app.py
   ├── auth.py
   ├── database.py
   ├── seed_sample_data.py
   ├── requirements.txt
   └── README.md
   ```

2. **(Recommended) Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the app:**
   ```bash
   streamlit run app.py
   ```
   Streamlit will open the app in your browser (typically `http://localhost:8501`).
   On first launch, `lab_tracker.db` is created automatically in the same
   folder, with the tables and a default admin account already in place.

5. **Log in** with the default administrator account:
   ```
   Username: admin
   Password: admin123
   ```
   From the **User Management** tab, the admin can add additional accounts
   for lab members.

6. **(Optional) Load sample data** to explore the dashboards immediately,
   instead of typing in entries by hand:
   ```bash
   python seed_sample_data.py
   ```
   This adds 3 sample users (`jdoe`, `asmith`, `rpatel`, all with password
   `password123`) and 12 sample lab entries spanning several months,
   professors, labs, and projects. Safe to run before or after the first
   `streamlit run app.py` — it creates the database itself if needed.

---

## 🗄️ Database Schema

**`users`**
| Column         | Type    | Notes                                  |
|----------------|---------|-----------------------------------------|
| user_id        | INTEGER | Primary key, autoincrement              |
| username       | TEXT    | Unique                                  |
| password_hash  | TEXT    | bcrypt hash (never stored in plaintext) |
| role           | TEXT    | `'admin'` or `'user'`                   |
| full_name      | TEXT    |                                          |
| is_active      | INTEGER | 1 = active, 0 = disabled                |
| created_date   | TEXT    | Timestamp of account creation           |

**`lab_entries`**
| Column                   | Type    | Notes                          |
|---------------------------|---------|---------------------------------|
| entry_id                 | INTEGER | Primary key, autoincrement      |
| entry_date               | TEXT    | `YYYY-MM-DD`                     |
| user_name                | TEXT    | Username of the entry's creator  |
| professor_name           | TEXT    |                                  |
| lab_name                 | TEXT    |                                  |
| project_name             | TEXT    |                                  |
| entry_time               | TEXT    | `HH:MM`                          |
| exit_time                | TEXT    | `HH:MM`                          |
| total_hours              | REAL    | Auto-calculated, exit − entry    |
| lab_activity              | TEXT    | Multi-line free text             |
| lab_partner_name          | TEXT    | Optional                        |
| lab_partner_contribution  | TEXT    | Multi-line free text, optional   |
| notes                    | TEXT    | Optional                        |
| created_timestamp        | TEXT    | Stamped automatically on insert  |

---

## 🔑 Notes on Authentication & Permissions

- Passwords are hashed with **bcrypt** (random salt per password, never
  stored or compared in plaintext).
- **Any logged-in user** can create entries, view history, and edit any
  entry (useful in a shared-lab setting where partners often log on each
  other's behalf).
- **Only Admins** can delete entries, manage users, and access the User
  Management tab.
- An Admin cannot disable their own account (prevents accidental lockout).
- Disabled accounts cannot log in, but their historical lab entries remain
  intact for reporting purposes.

---

## 🧪 Sample Test Data

Run `python seed_sample_data.py` (see step 6 above) for ready-made sample
users and lab entries. You can re-run it any time to add another batch of
sample entries (it will skip creating duplicate users).

---

## 🛠️ Project Structure

| File                   | Purpose                                                          |
|------------------------|--------------------------------------------------------------------|
| `app.py`               | Streamlit UI — login page + all 6 tabs                            |
| `database.py`          | All SQLite3 access (schema, init, CRUD) — no Streamlit dependency  |
| `auth.py`              | Password hashing (bcrypt) + session-state helpers                  |
| `seed_sample_data.py`  | Optional script to populate sample users & lab entries             |
| `requirements.txt`     | Python dependencies                                                |
| `lab_tracker.db`       | SQLite database file (auto-created on first run)                   |

---

## ⚠️ Troubleshooting

- **"No module named 'streamlit'" / 'bcrypt' / 'plotly'`:** run
  `pip install -r requirements.txt` inside the same Python environment you
  use to run `streamlit run app.py`.
- **Locked out as the only admin:** stop the app, delete `lab_tracker.db`,
  and restart — a fresh database with the default `admin` / `admin123`
  account will be created. (This deletes all existing data, so only do
  this in development.)
- **Port already in use:** run `streamlit run app.py --server.port 8502`
  (or any free port).
