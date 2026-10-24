"""SQLite storage for the Nova database.

One portable database file holds the 65 SAINT unit records plus personnel,
projects, documents, notes, calendar events, alarms and session logs. The
console seeds it deterministically on first boot and then works offline.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY,
    callsign TEXT UNIQUE NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    location TEXT NOT NULL,
    battery INTEGER NOT NULL,
    firmware TEXT NOT NULL,
    clearance TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS personnel (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    clearance TEXT NOT NULL,
    division TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    lead TEXT NOT NULL,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    time TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS alarms (
    id INTEGER PRIMARY KEY,
    time TEXT NOT NULL,
    label TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    message TEXT NOT NULL
);
"""

MODELS = [
    "SAINT Mark I",
    "SAINT Mark II",
    "SAINT Mark III",
    "SAINT-5 Prototype",
    "SAINT Heavy",
    "SAINT Scout",
    "SAINT Demolition",
]
LOCATIONS = [
    "Nova Labs — Bay 1",
    "Nova Labs — Bay 2",
    "Nova Labs — Bay 3",
    "Nova Labs — Cold Storage",
    "Nova Motor Pool",
    "Hazmat Range",
    "Telemetry Deck",
    "Assembly Line A",
    "Assembly Line B",
    "Remote Outpost 7",
    "Bunker 12",
    "Diagnostics Cradle",
]
STATUSES = ["online", "standby", "maintenance", "offline"]
CLEARANCES = ["Level 1", "Level 2", "Level 3", "Level 4"]

PERSONNEL = [
    ("Stephanie Speck", "Animal Care & Morale", "Level 2", "Community Relations", "active"),
    ("Dr. Newton Crosby", "Robotics Engineer", "Level 4", "SAINT Program", "active"),
    ("Ben Jabituya", "Systems Engineer", "Level 4", "SAINT Program", "active"),
    ("Howard Marner", "Executive Director", "Level 4", "Nova Executive", "active"),
    ("Captain Skroeder", "Security Chief", "Level 3", "Security", "active"),
    ("Frank Turner", "Field Technician", "Level 2", "Maintenance", "active"),
    ("Dr. Anna Vasquez", "AI Ethics Researcher", "Level 3", "Research", "active"),
    ("Miles Okafor", "Telemetry Operator", "Level 2", "Operations", "active"),
    ("Priya Raman", "Firmware Lead", "Level 3", "SAINT Program", "active"),
    ("Gus Lindberg", "Parts & Logistics", "Level 1", "Logistics", "active"),
    ("Elena Duarte", "Network Security", "Level 4", "Security", "on leave"),
    ("Tommy Chen", "Junior Technician", "Level 1", "Maintenance", "active"),
]

PROJECTS = [
    ("SAINT", "SAINT Program", "active", "Dr. Newton Crosby", "Strategic Artificially Intelligent Nuclear Transport units — 65 fielded chassis."),
    ("NOVA-5", "Self-Awareness Study", "classified", "Dr. Anna Vasquez", "Study of emergent behaviour in the SAINT-5 prototype after lightning strike."),
    ("UPLINK", "Satellite Telemetry Uplink", "active", "Miles Okafor", "Offline-capable telemetry relay for remote chassis diagnostics."),
    ("ARMOR", "Chassis Hardening", "active", "Priya Raman", "Reinforced shells and dust sealing for desert field trials."),
    ("KINETIC", "Hydraulic Mobility Refresh", "paused", "Frank Turner", "Tread and manipulator upgrade kits for Mark II and Mark III units."),
    ("WATCHDOG", "Autonomy Safety Limits", "active", "Dr. Anna Vasquez", "Hard-coded safety envelopes and remote shutdown authority."),
    ("SCRAPYARD", "Decommissioning Program", "active", "Gus Lindberg", "Recycling pipeline for retired SAINT chassis."),
    ("BLACKOUT", "Offline Operations Drill", "planned", "Captain Skroeder", "Full-facility exercise with no external network availability."),
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    """Thin, dependency-free data access layer."""

    TABLES = {"units", "personnel", "projects", "documents", "notes", "events", "alarms", "logs"}

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.seed()

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    # ------------------------------------------------------------------ seed
    def seed(self) -> None:
        self._seed_units()
        self._seed_personnel()
        self._seed_projects()
        self._seed_documents()

    def _seed_units(self) -> None:
        if self.count("units"):
            return
        stamp = _now()
        rows = []
        for number in range(1, config.RECORD_COUNT + 1):
            model = MODELS[(number - 1) % len(MODELS)]
            if number == 5:
                model = "SAINT-5 Prototype"
            if number % 11 == 0:
                status = "maintenance"
            elif number % 9 == 0:
                status = "standby"
            elif number % 17 == 0:
                status = "offline"
            else:
                status = "online"
            battery = 100 - (number * 7) % 61
            notes = ""
            if number == 5:
                notes = "Johnny 5. Lightning-strike survivor, curious, non-military. Handle with respect."
                battery = 88
            elif number == 1:
                notes = "Original prototype. Retired from field duty, kept for parts."
            rows.append(
                (
                    number,
                    f"SAINT-{number:03d}",
                    model,
                    status,
                    LOCATIONS[(number - 1) % len(LOCATIONS)],
                    max(4, battery),
                    f"v2.6.{number % 20:02d}" if number != 5 else "v5.0-j5",
                    CLEARANCES[number % len(CLEARANCES)],
                    notes,
                    stamp,
                )
            )
        self.conn.executemany(
            "INSERT INTO units (id, callsign, model, status, location, battery, firmware, clearance, notes, updated)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def _seed_personnel(self) -> None:
        if self.count("personnel"):
            return
        self.conn.executemany(
            "INSERT INTO personnel (name, role, clearance, division, status) VALUES (?, ?, ?, ?, ?)",
            PERSONNEL,
        )
        self.conn.commit()

    def _seed_projects(self) -> None:
        if self.count("projects"):
            return
        self.conn.executemany(
            "INSERT INTO projects (code, title, status, lead, summary) VALUES (?, ?, ?, ?, ?)",
            PROJECTS,
        )
        self.conn.commit()

    def _seed_documents(self) -> None:
        if self.count("documents"):
            return
        body = (
            "NOVA ROBOTICS — WELCOME PACKET\n\n"
            "This console is the offline field interface for the SAINT program.\n"
            "Everything you write stays on this device: the Nova database lives in\n"
            "a single SQLite file inside your Nova home folder.\n\n"
            "A few things to try:\n"
            "  1. Open the Nova Database and browse all 65 SAINT units.\n"
            "  2. Use SAINT Remote Access with the access code shown in Settings\n"
            "     (the demo default is J5-1986) and ask a unit to dance.\n"
            "  3. Write something here, then press Ctrl-S to save it.\n\n"
            "On a tablet or touchscreen, press F2 anywhere to pop up the on-screen\n"
            "keyboard, or tap a text field.\n\n"
            "-- Nova Robotics, Field Operations"
        )
        stamp = _now()
        self.conn.execute(
            "INSERT INTO documents (title, body, created, updated) VALUES (?, ?, ?, ?)",
            ("Welcome Packet", body, stamp, stamp),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ utils
    def count(self, table: str) -> int:
        if table not in self.TABLES:
            raise ValueError(f"Unknown table: {table}")
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _rows(self, sql: str, params=()) -> list[dict]:
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------ units
    def list_units(self, query: str = "", status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM units"
        clauses, params = [], []
        if query:
            like = f"%{query.lower()}%"
            clauses.append(
                "(lower(callsign) LIKE ? OR lower(model) LIKE ? OR lower(location) LIKE ? OR lower(notes) LIKE ?)"
            )
            params += [like, like, like, like]
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        return self._rows(sql, tuple(params))

    def get_unit(self, key: str | int) -> dict | None:
        if isinstance(key, int) or str(key).isdigit():
            rows = self._rows("SELECT * FROM units WHERE id = ?", (int(key),))
        else:
            rows = self._rows("SELECT * FROM units WHERE callsign = ?", (str(key).upper(),))
        return rows[0] if rows else None

    def update_unit(self, unit_id: int, **fields) -> bool:
        allowed = {"status", "location", "battery", "firmware", "clearance", "notes"}
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return False
        clean["updated"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in clean)
        params = list(clean.values()) + [int(unit_id)]
        self.conn.execute(f"UPDATE units SET {assignments} WHERE id = ?", params)
        self.conn.commit()
        return True

    def unit_stats(self) -> dict:
        rows = self._rows("SELECT status, COUNT(*) AS n FROM units GROUP BY status")
        by_status = {row["status"]: row["n"] for row in rows}
        avg = self.conn.execute("SELECT AVG(battery) FROM units").fetchone()[0] or 0
        return {
            "total": self.count("units"),
            "by_status": by_status,
            "average_battery": round(float(avg)),
        }

    # -------------------------------------------------------------- personnel
    def list_personnel(self, query: str = "") -> list[dict]:
        if query:
            like = f"%{query.lower()}%"
            return self._rows(
                "SELECT * FROM personnel WHERE lower(name) LIKE ? OR lower(role) LIKE ? OR lower(division) LIKE ?"
                " ORDER BY name",
                (like, like, like),
            )
        return self._rows("SELECT * FROM personnel ORDER BY name")

    # --------------------------------------------------------------- projects
    def list_projects(self, query: str = "") -> list[dict]:
        if query:
            like = f"%{query.lower()}%"
            return self._rows(
                "SELECT * FROM projects WHERE lower(code) LIKE ? OR lower(title) LIKE ? OR lower(summary) LIKE ?"
                " ORDER BY code",
                (like, like, like),
            )
        return self._rows("SELECT * FROM projects ORDER BY code")

    # -------------------------------------------------------------- documents
    def list_documents(self) -> list[dict]:
        return self._rows(
            "SELECT id, title, length(body) AS size, updated FROM documents ORDER BY updated DESC, id DESC"
        )

    def get_document(self, doc_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM documents WHERE id = ?", (int(doc_id),))
        return rows[0] if rows else None

    def create_document(self, title: str, body: str = "") -> int:
        stamp = _now()
        cur = self.conn.execute(
            "INSERT INTO documents (title, body, created, updated) VALUES (?, ?, ?, ?)",
            (title or "Untitled", body, stamp, stamp),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def save_document(self, doc_id: int, title: str, body: str) -> None:
        self.conn.execute(
            "UPDATE documents SET title = ?, body = ?, updated = ? WHERE id = ?",
            (title or "Untitled", body, _now(), int(doc_id)),
        )
        self.conn.commit()

    def delete_document(self, doc_id: int) -> None:
        self.conn.execute("DELETE FROM documents WHERE id = ?", (int(doc_id),))
        self.conn.commit()

    # ------------------------------------------------------------------- notes
    def list_notes(self) -> list[dict]:
        return self._rows("SELECT * FROM notes ORDER BY updated DESC, id DESC")

    def get_note(self, note_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM notes WHERE id = ?", (int(note_id),))
        return rows[0] if rows else None

    def create_note(self, title: str, body: str = "") -> int:
        stamp = _now()
        cur = self.conn.execute(
            "INSERT INTO notes (title, body, created, updated) VALUES (?, ?, ?, ?)",
            (title or "Note", body, stamp, stamp),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def save_note(self, note_id: int, title: str, body: str) -> None:
        self.conn.execute(
            "UPDATE notes SET title = ?, body = ?, updated = ? WHERE id = ?",
            (title or "Note", body, _now(), int(note_id)),
        )
        self.conn.commit()

    def delete_note(self, note_id: int) -> None:
        self.conn.execute("DELETE FROM notes WHERE id = ?", (int(note_id),))
        self.conn.commit()

    # ------------------------------------------------------------------ events
    def events_for_day(self, day: str) -> list[dict]:
        return self._rows("SELECT * FROM events WHERE day = ? ORDER BY time, id", (day,))

    def events_for_month(self, year: int, month: int) -> list[dict]:
        prefix = f"{year:04d}-{month:02d}-%"
        return self._rows("SELECT * FROM events WHERE day LIKE ? ORDER BY day, time, id", (prefix,))

    def add_event(self, day: str, time: str, title: str, notes: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO events (day, time, title, notes) VALUES (?, ?, ?, ?)",
            (day, time, title, notes),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_event(self, event_id: int) -> None:
        self.conn.execute("DELETE FROM events WHERE id = ?", (int(event_id),))
        self.conn.commit()

    # ------------------------------------------------------------------ alarms
    def list_alarms(self) -> list[dict]:
        return self._rows("SELECT * FROM alarms ORDER BY time, id")

    def add_alarm(self, time: str, label: str) -> int:
        cur = self.conn.execute("INSERT INTO alarms (time, label, enabled) VALUES (?, ?, 1)", (time, label))
        self.conn.commit()
        return int(cur.lastrowid)

    def set_alarm_enabled(self, alarm_id: int, enabled: bool) -> None:
        self.conn.execute("UPDATE alarms SET enabled = ? WHERE id = ?", (1 if enabled else 0, int(alarm_id)))
        self.conn.commit()

    def delete_alarm(self, alarm_id: int) -> None:
        self.conn.execute("DELETE FROM alarms WHERE id = ?", (int(alarm_id),))
        self.conn.commit()

    # -------------------------------------------------------------------- logs
    def log(self, source: str, message: str) -> None:
        self.conn.execute(
            "INSERT INTO logs (ts, source, message) VALUES (?, ?, ?)",
            (_now(), source, message[:2000]),
        )
        self.conn.commit()

    def list_logs(self, limit: int = 200) -> list[dict]:
        return self._rows("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (int(limit),))

    def clear_logs(self) -> None:
        self.conn.execute("DELETE FROM logs")
        self.conn.commit()
