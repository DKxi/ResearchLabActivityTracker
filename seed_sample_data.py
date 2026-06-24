"""
seed_sample_data.py
====================
Optional helper script that populates the Research Lab Activity Tracker
database with realistic sample data — extra users and a few weeks' worth of
lab entries — so you can explore every tab (History, Dashboard, Professor
Summary, Lab Partner Contributions, User Management) without manually typing
in test data first.

Usage:
    python seed_sample_data.py

This script is idempotent-ish: it will not duplicate users (it skips any
username that already exists), but re-running it WILL add another batch of
sample lab entries. Run it once after the first `streamlit run app.py`
launch (which creates the database) or simply run it first — it calls
init_database() itself, so the database/tables will be created automatically
if they don't exist yet.
"""

import database as db

# ---------------------------------------------------------------------------
# 1. Make sure the database + tables exist (and the default admin account).
# ---------------------------------------------------------------------------
db.init_database()
print(f"Database ready at: {db.DB_PATH}")

# ---------------------------------------------------------------------------
# 2. Sample regular users.
# ---------------------------------------------------------------------------
SAMPLE_USERS = [
    ("jdoe", "password123", "user", "Jane Doe"),
    ("asmith", "password123", "user", "Alex Smith"),
    ("rpatel", "password123", "user", "Raj Patel"),
]

print("\nCreating sample users...")
for username, password, role, full_name in SAMPLE_USERS:
    success, message = db.create_user(username, password, role, full_name)
    print(f"  - {username}: {message}")

# ---------------------------------------------------------------------------
# 3. Sample lab entries spread across several professors, labs, projects,
#    users, and months so every dashboard chart has something to show.
# ---------------------------------------------------------------------------
SAMPLE_ENTRIES = [
    dict(entry_date="2026-04-03", user_name="jdoe", professor_name="Dr. Alice Chen",
         lab_name="Materials Science Lab", project_name="Polymer Durability Study",
         entry_time="09:00", exit_time="13:30", total_hours=4.5,
         lab_activity="Prepared polymer samples and ran initial stress tests.",
         lab_partner_name="Maria Gomez", lab_partner_contribution="Calibrated the stress-test rig.",
         notes="First batch of samples looked promising."),
    dict(entry_date="2026-04-10", user_name="jdoe", professor_name="Dr. Alice Chen",
         lab_name="Materials Science Lab", project_name="Polymer Durability Study",
         entry_time="09:00", exit_time="12:00", total_hours=3.0,
         lab_activity="Prepared polymer samples and ran initial stress tests.",
         lab_partner_name="Maria Gomez", lab_partner_contribution="Recorded measurements in the log.",
         notes=""),
    dict(entry_date="2026-04-17", user_name="asmith", professor_name="Dr. Alice Chen",
         lab_name="Materials Science Lab", project_name="Composite Strength Analysis",
         entry_time="10:00", exit_time="16:00", total_hours=6.0,
         lab_activity="Ran tensile strength tests on composite samples.",
         lab_partner_name="", lab_partner_contribution="", notes="Equipment recalibrated mid-session."),
    dict(entry_date="2026-04-22", user_name="rpatel", professor_name="Dr. Marcus Lee",
         lab_name="Cell Biology Lab", project_name="Cancer Cell Signaling",
         entry_time="08:30", exit_time="15:00", total_hours=6.5,
         lab_activity="Cultured cell lines and prepared slides for imaging.",
         lab_partner_name="Sam Lin", lab_partner_contribution="Performed fluorescence imaging.",
         notes=""),
    dict(entry_date="2026-05-01", user_name="rpatel", professor_name="Dr. Marcus Lee",
         lab_name="Cell Biology Lab", project_name="Cancer Cell Signaling",
         entry_time="08:30", exit_time="14:00", total_hours=5.5,
         lab_activity="Cultured cell lines and prepared slides for imaging.",
         lab_partner_name="Sam Lin", lab_partner_contribution="Analyzed imaging results.",
         notes="Found an interesting anomaly in batch C."),
    dict(entry_date="2026-05-06", user_name="jdoe", professor_name="Dr. Priya Nair",
         lab_name="Robotics Lab", project_name="Autonomous Navigation",
         entry_time="13:00", exit_time="18:30", total_hours=5.5,
         lab_activity="Tuned PID controller parameters for the navigation stack.",
         lab_partner_name="Tom Becker", lab_partner_contribution="Wrote the test harness script.",
         notes=""),
    dict(entry_date="2026-05-14", user_name="asmith", professor_name="Dr. Priya Nair",
         lab_name="Robotics Lab", project_name="Autonomous Navigation",
         entry_time="13:00", exit_time="17:00", total_hours=4.0,
         lab_activity="Tuned PID controller parameters for the navigation stack.",
         lab_partner_name="Tom Becker", lab_partner_contribution="Logged sensor data for analysis.",
         notes="Navigation accuracy improved by ~12%."),
    dict(entry_date="2026-05-20", user_name="rpatel", professor_name="Dr. Marcus Lee",
         lab_name="Cell Biology Lab", project_name="Cancer Cell Signaling",
         entry_time="09:00", exit_time="13:00", total_hours=4.0,
         lab_activity="Ran western blot to confirm protein expression levels.",
         lab_partner_name="", lab_partner_contribution="", notes=""),
    dict(entry_date="2026-06-02", user_name="jdoe", professor_name="Dr. Alice Chen",
         lab_name="Materials Science Lab", project_name="Polymer Durability Study",
         entry_time="09:30", exit_time="14:00", total_hours=4.5,
         lab_activity="Performed accelerated aging tests on Batch 12 samples.",
         lab_partner_name="Maria Gomez", lab_partner_contribution="Set up the environmental chamber.",
         notes="Batch 12 showed reduced degradation vs. Batch 11."),
    dict(entry_date="2026-06-09", user_name="asmith", professor_name="Dr. Priya Nair",
         lab_name="Robotics Lab", project_name="Swarm Coordination",
         entry_time="11:00", exit_time="16:30", total_hours=5.5,
         lab_activity="Implemented and tested a new swarm coordination algorithm.",
         lab_partner_name="Tom Becker", lab_partner_contribution="Built the simulation environment.",
         notes=""),
    dict(entry_date="2026-06-15", user_name="rpatel", professor_name="Dr. Marcus Lee",
         lab_name="Cell Biology Lab", project_name="Cancer Cell Signaling",
         entry_time="08:00", exit_time="12:30", total_hours=4.5,
         lab_activity="Ran western blot to confirm protein expression levels.",
         lab_partner_name="Sam Lin", lab_partner_contribution="Prepared reagents.",
         notes=""),
    dict(entry_date="2026-06-20", user_name="jdoe", professor_name="Dr. Priya Nair",
         lab_name="Robotics Lab", project_name="Autonomous Navigation",
         entry_time="13:00", exit_time="19:00", total_hours=6.0,
         lab_activity="Tuned PID controller parameters for the navigation stack.",
         lab_partner_name="", lab_partner_contribution="", notes="Final tuning pass before demo."),
]

print("\nInserting sample lab entries...")
inserted = 0
for entry in SAMPLE_ENTRIES:
    success, result = db.add_entry(entry)
    if success:
        inserted += 1
    else:
        print(f"  ! Failed to insert entry for {entry['entry_date']}: {result}")

print(f"\nDone. Inserted {inserted} of {len(SAMPLE_ENTRIES)} sample lab entries.")
print("\nYou can now log in with any of the following accounts:")
print("  Admin -> username: admin     password: admin123")
for username, password, role, full_name in SAMPLE_USERS:
    print(f"  User  -> username: {username:<8} password: {password}  ({full_name})")
