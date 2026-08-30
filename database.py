import sqlite3
import time
from pathlib import Path


DEFAULT_MACHINES = [
    ("free", "FREE MINER", 0, 20.0),
    ("m50", "TURBO MINER", 50, 10.0),
    ("m100", "HYPER MINER", 100, 5.0),
    ("m200", "ULTRA MINER", 200, 1.25),
]


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init()

    def init(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            balance REAL DEFAULT 0,
            uncollected REAL DEFAULT 0,
            machine_id TEXT DEFAULT 'free',
            mining_last_ts REAL DEFAULT 0,
            wallet TEXT DEFAULT '',
            channel_verified INTEGER DEFAULT 0,
            referrer INTEGER,
            referrals TEXT DEFAULT '[]',
            valid_referrals TEXT DEFAULT '[]',
            earn_done TEXT DEFAULT '[]',
            withdrawal_id TEXT
        );

        CREATE TABLE IF NOT EXISTS required_channels (
            chat_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS earn_tasks (
            id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            reward REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS machines (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            stars INTEGER NOT NULL,
            hours_per_ton REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS withdrawals (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            wallet TEXT NOT NULL,
            status TEXT NOT NULL,
            created REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            amount REAL NOT NULL,
            meta TEXT DEFAULT '',
            created REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS stars_payments (
            charge_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            machine_id TEXT NOT NULL,
            stars INTEGER NOT NULL,
            created REAL NOT NULL
        );
        """)
        self.conn.commit()

        defaults = {
            "required_referrals": "5",
            "minimum_withdrawal": "5",
            "machine_required": "1",
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        for m in DEFAULT_MACHINES:
            c.execute(
                "INSERT OR IGNORE INTO machines(id,name,stars,hours_per_ton) VALUES(?,?,?,?)",
                m
            )
        self.conn.commit()

    def setting(self, key):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        v = row["value"]
        if key == "required_referrals":
            return int(v)
        if key in ("minimum_withdrawal",):
            return float(v)
        if key == "machine_required":
            return v == "1"
        return v

    def set_setting(self, key, value):
        if isinstance(value, bool):
            value = "1" if value else "0"
        self.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value))
        )
        self.conn.commit()

    @staticmethod
    def _json(s):
        import json
        try:
            return json.loads(s)
        except Exception:
            return []

    @staticmethod
    def _dump(v):
        import json
        return json.dumps(v)

    def user(self, uid, username=None, first_name=None):
        row = self.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            now = time.time()
            self.conn.execute(
                "INSERT INTO users(id,username,first_name,machine_id,mining_last_ts) VALUES(?,?,?,?,?)",
                (uid, username or "", first_name or "", "free", now)
            )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        else:
            if username is not None or first_name is not None:
                self.conn.execute(
                    "UPDATE users SET username=?, first_name=? WHERE id=?",
                    (username if username is not None else row["username"],
                     first_name if first_name is not None else row["first_name"], uid)
                )
                self.conn.commit()
                row = self.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

        d = dict(row)
        for k in ("referrals", "valid_referrals", "earn_done"):
            d[k] = self._json(d[k])
        return d

    def save_user(self, u):
        self.conn.execute("""
        UPDATE users SET username=?, first_name=?, balance=?, uncollected=?,
        machine_id=?, mining_last_ts=?, wallet=?, channel_verified=?,
        referrer=?, referrals=?, valid_referrals=?, earn_done=?, withdrawal_id=?
        WHERE id=?
        """, (
            u["username"], u["first_name"], u["balance"], u["uncollected"],
            u["machine_id"], u["mining_last_ts"], u["wallet"],
            int(bool(u["channel_verified"])), u["referrer"],
            self._dump(u["referrals"]), self._dump(u["valid_referrals"]),
            self._dump(u["earn_done"]), u["withdrawal_id"], u["id"]
        ))
        self.conn.commit()

    def add_balance(self, uid, amount):
        self.conn.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))
        self.conn.commit()

    def subtract_balance(self, uid, amount):
        self.conn.execute(
            "UPDATE users SET balance=MAX(0,balance-?) WHERE id=?",
            (amount, uid)
        )
        self.conn.commit()

    def add_uncollected(self, uid, amount):
        self.conn.execute("UPDATE users SET uncollected=uncollected+? WHERE id=?", (amount, uid))
        self.conn.commit()

    def set_uncollected(self, uid, amount):
        self.conn.execute("UPDATE users SET uncollected=? WHERE id=?", (amount, uid))
        self.conn.commit()

    def set_mining_last(self, uid, ts):
        self.conn.execute("UPDATE users SET mining_last_ts=? WHERE id=?", (ts, uid))
        self.conn.commit()

    def activate_machine(self, uid, mid):
        now = time.time()
        self.conn.execute(
            "UPDATE users SET machine_id=?, mining_last_ts=?, uncollected=0 WHERE id=?",
            (mid, now, uid)
        )
        self.conn.commit()

    def machine(self, mid):
        r = self.conn.execute("SELECT * FROM machines WHERE id=?", (mid,)).fetchone()
        return dict(r) if r else None

    def machines(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM machines ORDER BY stars ASC"
        ).fetchall()]

    def add_machine(self, mid, name, stars, hours):
        self.conn.execute(
            "INSERT INTO machines VALUES(?,?,?,?)", (mid, name, stars, hours)
        )
        self.conn.commit()

    def delete_machine(self, mid):
        self.conn.execute("DELETE FROM machines WHERE id=? AND id!='free'", (mid,))
        self.conn.commit()

    def required_channels(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM required_channels ORDER BY rowid"
        ).fetchall()]

    def add_required_channel(self, chat_id, name, url):
        self.conn.execute(
            "INSERT OR REPLACE INTO required_channels VALUES(?,?,?)",
            (str(chat_id), name, url)
        )
        self.conn.commit()

    def delete_required_channel(self, target):
        self.conn.execute("DELETE FROM required_channels WHERE chat_id=?", (str(target),))
        self.conn.commit()

    def earn_tasks(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM earn_tasks ORDER BY rowid"
        ).fetchall()]

    def earn_task(self, tid):
        r = self.conn.execute("SELECT * FROM earn_tasks WHERE id=?", (tid,)).fetchone()
        return dict(r) if r else None

    def add_earn_task(self, tid, chat_id, name, url, reward):
        self.conn.execute(
            "INSERT INTO earn_tasks VALUES(?,?,?,?,?)",
            (tid, str(chat_id), name, url, reward)
        )
        self.conn.commit()

    def delete_earn_task(self, tid):
        self.conn.execute("DELETE FROM earn_tasks WHERE id=?", (tid,))
        self.conn.commit()

    def mark_earn_done(self, uid, tid):
        u = self.user(uid)
        if tid not in u["earn_done"]:
            u["earn_done"].append(tid)
            self.save_user(u)

    def log_tx(self, uid, kind, amount, meta):
        import uuid
        self.conn.execute(
            "INSERT INTO transactions VALUES(?,?,?,?,?,?)",
            (uuid.uuid4().hex[:12], uid, kind, amount, meta, time.time())
        )
        self.conn.commit()

    def transactions(self, uid, limit=12):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM transactions WHERE user_id=? ORDER BY created DESC LIMIT ?",
            (uid, limit)
        ).fetchall()]

    def create_withdrawal(self, wid, uid, amount, wallet):
        self.conn.execute(
            "INSERT INTO withdrawals VALUES(?,?,?,?,?,?)",
            (wid, uid, amount, wallet, "pending", time.time())
        )
        self.conn.commit()

    def withdrawal(self, wid):
        r = self.conn.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        return dict(r) if r else None

    def set_withdrawal_id(self, uid, wid):
        self.conn.execute("UPDATE users SET withdrawal_id=? WHERE id=?", (wid, uid))
        self.conn.commit()

    def set_withdrawal_status(self, wid, status):
        self.conn.execute("UPDATE withdrawals SET status=? WHERE id=?", (status, wid))
        self.conn.commit()

    def active_withdrawals(self, limit=10):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM withdrawals WHERE status IN ('pending','approved') "
            "ORDER BY created DESC LIMIT ?",
            (limit,)
        ).fetchall()]

    def count_active_withdrawals(self):
        r = self.conn.execute(
            "SELECT COUNT(*) AS n FROM withdrawals WHERE status IN ('pending','approved')"
        ).fetchone()
        return r["n"]

    def count_users(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def user_ids(self):
        return [r["id"] for r in self.conn.execute("SELECT id FROM users").fetchall()]

    def payment_exists(self, charge):
        return self.conn.execute(
            "SELECT 1 FROM stars_payments WHERE charge_id=?", (charge,)
        ).fetchone() is not None

    def save_payment(self, charge, uid, mid, stars):
        self.conn.execute(
            "INSERT INTO stars_payments VALUES(?,?,?,?,?)",
            (charge, uid, mid, stars, time.time())
        )
        self.conn.commit()
