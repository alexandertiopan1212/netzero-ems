import sqlite3
from datetime import datetime

DB_PATH = "satu_energy.db"

def init_db(path: str = DB_PATH):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS device_meta (
            device_sn TEXT PRIMARY KEY,
            device_type TEXT,
            last_state INTEGER,
            last_update DATETIME
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS device_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_sn TEXT,
            timestamp DATETIME,
            key TEXT,
            value REAL,
            unit TEXT,
            FOREIGN KEY(device_sn) REFERENCES device_meta(device_sn)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_device_ts ON device_data(device_sn, timestamp)")
    conn.commit()
    conn.close()

def upsert_device_meta(device_sn: str, device_type: str, state: int, update_time: datetime):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO device_meta(device_sn, device_type, last_state, last_update)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(device_sn) DO UPDATE SET
          device_type=excluded.device_type,
          last_state=excluded.last_state,
          last_update=excluded.last_update
        """,
        (device_sn, device_type, state, update_time)
    )
    conn.commit()
    conn.close()

def insert_device_data(records: list):
    """Records: list of tuples (device_sn, timestamp, key, value, unit)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executemany(
        "INSERT INTO device_data(device_sn, timestamp, key, value, unit) VALUES (?, ?, ?, ?, ?)",
        records
    )
    conn.commit()
    conn.close()

def get_device_meta():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT device_sn, device_type, last_state, last_update FROM device_meta").fetchall()
    conn.close()
    return rows

def get_device_data(sn: str, key: str, limit: int = 100):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute(
        "SELECT timestamp, value FROM device_data WHERE device_sn=? AND key=? ORDER BY timestamp DESC LIMIT ?",
        (sn, key, limit)
    ).fetchall()
    conn.close()
    return rows