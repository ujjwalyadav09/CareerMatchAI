"""SQLite storage layer (paper Sec. III-C)."""
import os
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student','company','admin')), ref_id INTEGER
);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT, skills TEXT DEFAULT '',
    interests TEXT DEFAULT '', cgpa REAL DEFAULT 0, branch TEXT DEFAULT '',
    backlogs INTEGER DEFAULT 0, grad_year INTEGER, resume_url TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, role_title TEXT DEFAULT '', domain TEXT DEFAULT '',
    description TEXT DEFAULT '', required TEXT DEFAULT '', preferred TEXT DEFAULT '',
    min_cgpa REAL DEFAULT 0, branches TEXT DEFAULT '', max_backlogs INTEGER DEFAULT 0,
    desks INTEGER DEFAULT 3, participating INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id),
    company_id INTEGER NOT NULL REFERENCES companies(id), slot INTEGER NOT NULL,
    desk INTEGER NOT NULL, score REAL, source TEXT DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','cancelled','attended','no_show')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
-- transactional guarantees: one student per desk-slot, one booking per student-slot
CREATE UNIQUE INDEX IF NOT EXISTS ux_desk_slot ON bookings(company_id, slot, desk) WHERE status != 'cancelled';
CREATE UNIQUE INDEX IF NOT EXISTS ux_student_slot ON bookings(student_id, slot) WHERE status != 'cancelled';
CREATE UNIQUE INDEX IF NOT EXISTS ux_student_company ON bookings(student_id, company_id) WHERE status != 'cancelled';
CREATE TABLE IF NOT EXISTS student_feedback (
    id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, company_id INTEGER NOT NULL,
    relevance INTEGER, usefulness INTEGER, convenience INTEGER, wait_minutes INTEGER,
    comments TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_id, company_id)
);
CREATE TABLE IF NOT EXISTS company_feedback (
    id INTEGER PRIMARY KEY, company_id INTEGER UNIQUE NOT NULL,
    candidate_quality INTEGER, skill_alignment INTEGER, to_interview INTEGER,
    shortlist_accuracy INTEGER, comments TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, company_id INTEGER NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('interview','offer')),
    UNIQUE (student_id, company_id)
);
CREATE TABLE IF NOT EXISTS ai_cache (
    key TEXT PRIMARY KEY, source TEXT NOT NULL, text TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

DEFAULT_SETTINGS = {
    "fair_name": "LPU Campus Career Fair 2026",
    "fair_date": "2026-12-05",
    "start_time": "09:00",
    "slot_len": "10",
    "num_slots": "48",
    "max_bookings": "4",
    "w_skill": "0.60",
    "w_interest": "0.25",
    "w_academic": "0.15",
    "tau": "0.35",
    "top_k": "5",
}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    con.commit()
    con.close()


# ------------------------------------------------------------------ helpers
def split(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def settings():
    rows = get_db().execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    return s


def weights(cfg=None):
    cfg = cfg or settings()
    return {"skill": float(cfg["w_skill"]), "interest": float(cfg["w_interest"]),
            "academic": float(cfg["w_academic"])}


def student_dict(row):
    d = dict(row)
    d["skills"] = split(row["skills"])
    d["interests"] = split(row["interests"])
    return d


def company_dict(row):
    d = dict(row)
    d["required"] = split(row["required"])
    d["preferred"] = split(row["preferred"])
    d["branches"] = split(row["branches"])
    return d


def all_students():
    return [student_dict(r) for r in get_db().execute("SELECT * FROM students ORDER BY name")]


def all_companies(participating_only=True):
    q = "SELECT * FROM companies" + (" WHERE participating = 1" if participating_only else "") + " ORDER BY name"
    return [company_dict(r) for r in get_db().execute(q)]


def get_student(sid):
    r = get_db().execute("SELECT * FROM students WHERE id = ?", (sid,)).fetchone()
    return student_dict(r) if r else None


def get_company(cid):
    r = get_db().execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
    return company_dict(r) if r else None


def active_bookings(where="", params=()):
    q = ("SELECT b.*, s.name AS student_name, c.name AS company_name FROM bookings b "
         "JOIN students s ON s.id = b.student_id JOIN companies c ON c.id = b.company_id "
         "WHERE b.status != 'cancelled' " + where + " ORDER BY b.slot")
    return get_db().execute(q, params).fetchall()
