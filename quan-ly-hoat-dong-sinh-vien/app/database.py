import sqlite3
from pathlib import Path
from flask import current_app, g

SCHEMA_VERSION = 1


def get_db():
    if "db" not in g:
        path = Path(current_app.config["DATABASE"])
        path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 10000")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript("""
    BEGIN IMMEDIATE;
    CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL, full_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','lecturer','student')),
      status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive','locked')),
      last_login_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS students(
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id), student_code TEXT NOT NULL UNIQUE,
      class_name TEXT DEFAULT '', faculty TEXT DEFAULT '', phone TEXT DEFAULT '', date_of_birth TEXT DEFAULT '',
      gender TEXT DEFAULT '', address TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS lecturers(
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id), lecturer_code TEXT NOT NULL UNIQUE,
      department TEXT DEFAULT '', phone TEXT DEFAULT '', position TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS activities(
      id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Khác',
      organizer TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '', start_time TEXT NOT NULL, end_time TEXT NOT NULL,
      registration_deadline TEXT NOT NULL, max_participants INTEGER NOT NULL CHECK(max_participants > 0),
      activity_points REAL NOT NULL DEFAULT 0 CHECK(activity_points >= 0),
      status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('draft','open','closed','completed','cancelled')),
      created_by INTEGER NOT NULL REFERENCES users(id), updated_by INTEGER REFERENCES users(id),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_activities_status_start ON activities(status,start_time);
    CREATE TABLE IF NOT EXISTS registrations(
      id INTEGER PRIMARY KEY, activity_id INTEGER NOT NULL REFERENCES activities(id), student_id INTEGER NOT NULL REFERENCES students(id),
      status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','cancelled')),
      registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, reviewed_by INTEGER REFERENCES users(id), reviewed_at TEXT,
      status_note TEXT DEFAULT '', cancelled_at TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(activity_id,student_id)
    );
    CREATE INDEX IF NOT EXISTS idx_registrations_status ON registrations(status,activity_id);
    CREATE TABLE IF NOT EXISTS attendance(
      id INTEGER PRIMARY KEY, registration_id INTEGER NOT NULL UNIQUE REFERENCES registrations(id),
      status TEXT NOT NULL CHECK(status IN ('present','absent','late')), check_in_time TEXT, note TEXT DEFAULT '',
      marked_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS activity_scores(
      id INTEGER PRIMARY KEY, registration_id INTEGER NOT NULL UNIQUE REFERENCES registrations(id), score REAL NOT NULL CHECK(score >= 0),
      note TEXT DEFAULT '', created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS notifications(
      id INTEGER PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, type TEXT NOT NULL DEFAULT 'general',
      recipient_user_id INTEGER REFERENCES users(id), created_by INTEGER NOT NULL REFERENCES users(id),
      related_activity_id INTEGER REFERENCES activities(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS notification_reads(
      notification_id INTEGER NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, read_at TEXT,
      PRIMARY KEY(notification_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS system_settings(setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL,
      updated_by INTEGER REFERENCES users(id), updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS user_settings(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      setting_key TEXT NOT NULL, setting_value TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(user_id,setting_key));
    CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
      entity_type TEXT NOT NULL, entity_id TEXT, details TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
    INSERT INTO schema_version(version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
    COMMIT;
    """)


def audit(user_id, action, entity_type, entity_id=None, details=""):
    get_db().execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",
                     (user_id, action, entity_type, str(entity_id) if entity_id is not None else None, details[:500]))

