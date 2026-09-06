#!/usr/bin/env python3
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def runtime_root():
    explicit = os.environ.get("CODEX_LAUNCHER_RUNTIME_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if getattr(sys, "frozen", False):
        # PyInstaller release binary lives at runtime/bin/CodexSwitcherServer.
        # Keep static assets beside it at runtime/static.
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[1]

ROOT = runtime_root()
STATIC = ROOT / "static"
DATA_DIR = Path(os.environ.get("CODEX_LAUNCHER_DATA", str(Path.home() / "Library/Application Support/com.nigolarer.codex-switcher"))).expanduser()
DB_PATH = DATA_DIR / "launcher.sqlite3"
LEGACY_DB_PATH = Path.home() / ".local/share/codex-profile-launcher/launcher.sqlite3"
LEGACY_PROJECT_DB = os.environ.get("CODEX_LAUNCHER_LEGACY_PROJECT_DB", "").strip()
HOST = os.environ.get("CODEX_LAUNCHER_HOST", "127.0.0.1")
DEFAULT_PORT = 17831
PORT_ENV = os.environ.get("CODEX_LAUNCHER_PORT")
CHATGPT_APP = os.environ.get("CHATGPT_APP", "/Applications/ChatGPT.app")
APP_VERSION = "1.0.9"

DATA_DIR.mkdir(parents=True, exist_ok=True)


def migrate_previous_app_support_once():
    """Copy data from the pre-rename Application Support location if the new app has no database yet."""
    if DB_PATH.exists():
        return
    old_dir = Path.home() / "Library/Application Support/com.ping.codex-account-switch-launcher"
    old_db = old_dir / "launcher.sqlite3"
    if not old_db.exists():
        return
    try:
        shutil.copy2(old_db, DB_PATH)
        old_backups = old_dir / "backups"
        new_backups = DATA_DIR / "backups"
        if old_backups.is_dir() and not new_backups.exists():
            shutil.copytree(old_backups, new_backups)
    except OSError:
        pass


migrate_previous_app_support_once()


def backup_existing_db_once_per_version():
    """Back up the user database before schema/default initialization for this app version."""
    if not DB_PATH.exists():
        return
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    marker = backup_dir / f".backed-up-{APP_VERSION}"
    if marker.exists():
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"launcher-{APP_VERSION}-{stamp}.sqlite3"
    try:
        shutil.copy2(DB_PATH, target)
        marker.write_text(str(target), encoding="utf-8")
    except OSError:
        pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  user_type TEXT NOT NULL DEFAULT 'Plus',
  weekly_remaining INTEGER NOT NULL DEFAULT 100 CHECK(weekly_remaining BETWEEN 0 AND 100),
  five_hour_remaining INTEGER NOT NULL DEFAULT 100 CHECK(five_hour_remaining BETWEEN 0 AND 100),
  five_hour_reset_at INTEGER,
  weekly_reset_at INTEGER,
  reset_count INTEGER NOT NULL DEFAULT 0 CHECK(reset_count >= 0),
  bound_account_id TEXT,
  bound_plan_type TEXT,
  bound_auth_home TEXT,
  bound_at INTEGER,
  last_sync_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS launchers (
  id TEXT PRIMARY KEY,
  codex_home TEXT NOT NULL DEFAULT '',
  desktop_data_dir TEXT NOT NULL DEFAULT '',
  theme_color TEXT NOT NULL DEFAULT '#4F7CFF',
  account_id INTEGER,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_launcher TEXT,
  to_launcher TEXT NOT NULL,
  switched_at INTEGER NOT NULL,
  reason TEXT NOT NULL DEFAULT 'launch'
);
"""

DEFAULT_COLORS = {
    "A": "#76D5CF",
    "B": "#D0DF5D",
    "C": "#A9669C",
    "D": "#F0A35A",
    "E": "#5E9FE6",
    "F": "#E66E73",
}
LAUNCHER_IDS = tuple(DEFAULT_COLORS)
MAX_LAUNCHERS = len(LAUNCHER_IDS)
MAX_ACCOUNTS = 20
DEFAULT_FIVE_HOUR_DANGER_THRESHOLD = 15
DEFAULT_PLUS_WEEKLY_DANGER_THRESHOLD = 10
DEFAULT_OFFICIAL_SYNC_INTERVAL_MINUTES = 30
DEFAULT_GLOBAL_SYNC_INTERVAL_HOURS = 6
ALLOWED_OFFICIAL_SYNC_INTERVAL_MINUTES = (5, 30, 60, 180)
USER_TYPES = ("Plus", "Pro X10", "Pro X20", "Ultra")


def epoch():
    return int(time.time())


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(SCHEMA)
    return c


def migrate_legacy_db_once():
    if DB_PATH.exists():
        return
    candidates = []
    if LEGACY_PROJECT_DB:
        candidates.append(Path(LEGACY_PROJECT_DB).expanduser())
    candidates.append(LEGACY_DB_PATH)
    for source in candidates:
        if not source.exists() or not source.is_file():
            continue
        try:
            shutil.copy2(source, DB_PATH)
            return
        except OSError:
            continue


def table_exists(c, name):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def state_get(c, key, default=None):
    row = c.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def state_set(c, key, value):
    c.execute("INSERT OR REPLACE INTO state(key,value) VALUES(?,?)", (key, str(value)))


def migrate_profiles_to_v4(c):
    """One-time migration from v0.3 profiles into separate accounts + launchers."""
    if state_get(c, "schema_v4_migrated") == "1":
        return

    old_profiles = []
    if table_exists(c, "profiles"):
        try:
            old_profiles = [dict(r) for r in c.execute("SELECT * FROM profiles ORDER BY id").fetchall()]
        except sqlite3.DatabaseError:
            old_profiles = []

    existing_launchers = c.execute("SELECT COUNT(*) n FROM launchers").fetchone()["n"]
    if existing_launchers == 0 and old_profiles:
        memo_to_account = {}
        for p in old_profiles:
            pid = str(p.get("id", "")).upper()
            if pid not in LAUNCHER_IDS:
                continue
            memo = (p.get("memo") or f"账号 {pid}").strip()
            quota = int(p.get("remaining_quota", 100) or 100)
            # Reuse identical old mnemonic as one account; launcher bindings themselves remain non-unique.
            if memo not in memo_to_account:
                t = epoch()
                cur = c.execute(
                    "INSERT INTO accounts(name,weekly_remaining,five_hour_reset_at,reset_count,created_at,updated_at) VALUES(?,?,NULL,0,?,?)",
                    (memo, max(0, min(100, quota)), t, t),
                )
                memo_to_account[memo] = cur.lastrowid
            account_id = memo_to_account[memo]
            ch = "" if pid == "A" else (p.get("codex_home") or f"~/.codex-profile-{pid.lower()}")
            dd = "" if pid == "A" else (p.get("desktop_data_dir") or f"~/Library/Application Support/ChatGPT-Profiles/{pid}")
            t = epoch()
            c.execute(
                "INSERT OR IGNORE INTO launchers(id,codex_home,desktop_data_dir,theme_color,account_id,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (pid, ch, dd, DEFAULT_COLORS[pid], account_id, 1, t, t),
            )

    # Convert ISO history timestamps from older versions into epoch seconds when necessary.
    if table_exists(c, "history"):
        cols = {r[1] for r in c.execute("PRAGMA table_info(history)").fetchall()}
        if "from_profile" in cols and "to_profile" in cols and "switched_at" in cols:
            # We keep the existing history table schema if legacy columns exist; importing into a new table
            # is safer than ALTER gymnastics. Rename once, recreate, import.
            legacy = c.execute("SELECT COUNT(*) n FROM history").fetchone()["n"]
            if legacy >= 0 and "from_launcher" not in cols:
                c.execute("ALTER TABLE history RENAME TO history_v3")
                c.execute("""
                    CREATE TABLE history (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      from_launcher TEXT,
                      to_launcher TEXT NOT NULL,
                      switched_at INTEGER NOT NULL,
                      reason TEXT NOT NULL DEFAULT 'launch'
                    )
                """)
                rows = c.execute("SELECT * FROM history_v3 ORDER BY id").fetchall()
                for r in rows:
                    raw = r["switched_at"]
                    ts = epoch()
                    if isinstance(raw, (int, float)):
                        ts = int(raw)
                    elif raw:
                        try:
                            from datetime import datetime
                            ts = int(datetime.fromisoformat(str(raw)).timestamp())
                        except Exception:
                            pass
                    reason = r["reason"] if "reason" in r.keys() else "launch"
                    c.execute(
                        "INSERT INTO history(from_launcher,to_launcher,switched_at,reason) VALUES(?,?,?,?)",
                        (r["from_profile"], r["to_profile"], ts, reason or "launch"),
                    )

    state_set(c, "schema_v4_migrated", "1")


def migrate_schema_v8(c):
    cols = {r["name"] for r in c.execute("PRAGMA table_info(accounts)").fetchall()}
    if "weekly_reset_at" not in cols:
        c.execute("ALTER TABLE accounts ADD COLUMN weekly_reset_at INTEGER")
    if "user_type" not in cols:
        c.execute("ALTER TABLE accounts ADD COLUMN user_type TEXT NOT NULL DEFAULT 'Plus'")
    if "five_hour_remaining" not in cols:
        c.execute("ALTER TABLE accounts ADD COLUMN five_hour_remaining INTEGER NOT NULL DEFAULT 100")
    # v0.22.4: persist real Codex/ChatGPT account binding in the stable user DB.
    # These fields intentionally store identifiers/metadata only, never OAuth tokens.
    for name, decl in (
        ("bound_account_id", "TEXT"),
        ("bound_plan_type", "TEXT"),
        ("bound_auth_home", "TEXT"),
        ("bound_at", "INTEGER"),
        ("last_sync_at", "INTEGER"),
    ):
        if name not in cols:
            c.execute(f"ALTER TABLE accounts ADD COLUMN {name} {decl}")


def ensure_defaults():
    with conn() as c:
        migrate_profiles_to_v4(c)
        migrate_schema_v8(c)
        # At least one human account mnemonic must exist.
        if c.execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"] == 0:
            t = epoch()
            cur = c.execute(
                "INSERT INTO accounts(name,weekly_remaining,five_hour_reset_at,reset_count,created_at,updated_at) VALUES('主账号',100,NULL,0,?,?)",
                (t, t),
            )
            default_account = cur.lastrowid
        else:
            default_account = c.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()["id"]

        t = epoch()
        if not c.execute("SELECT 1 FROM launchers WHERE id='A'").fetchone():
            c.execute(
                "INSERT INTO launchers(id,codex_home,desktop_data_dir,theme_color,account_id,enabled,created_at,updated_at) VALUES('A','','',?,?,1,?,?)",
                (DEFAULT_COLORS["A"], default_account, t, t),
            )
        # A is always the untouched official launch path.
        c.execute("UPDATE launchers SET codex_home='',desktop_data_dir='',enabled=1 WHERE id='A'")

        if c.execute("SELECT COUNT(*) n FROM launchers").fetchone()["n"] == 1:
            c.execute(
                "INSERT INTO launchers(id,codex_home,desktop_data_dir,theme_color,account_id,enabled,created_at,updated_at) VALUES('B','~/.codex-profile-b','~/Library/Application Support/ChatGPT-Profiles/B',?,?,1,?,?)",
                (DEFAULT_COLORS["B"], default_account, t, t),
            )

        if not state_get(c, "active_launcher"):
            # Compatibility with old active_profile state.
            state_set(c, "active_launcher", state_get(c, "active_profile", "A"))
        if not state_get(c, "last_switch_at"):
            state_set(c, "last_switch_at", epoch())
        if not state_get(c, "language"):
            state_set(c, "language", "en")
        if not state_get(c, "appearance"):
            state_set(c, "appearance", "dark")
        if state_get(c, "welcome_seen") is None:
            state_set(c, "welcome_seen", "0")
        if not state_get(c, "port"):
            state_set(c, "port", DEFAULT_PORT)
        if state_get(c, "handoff_prompt") is None:
            state_set(c, "handoff_prompt", "")
        if state_get(c, "handoff_reply") is None:
            state_set(c, "handoff_reply", "")
        if state_get(c, "five_hour_danger_threshold") is None:
            state_set(c, "five_hour_danger_threshold", DEFAULT_FIVE_HOUR_DANGER_THRESHOLD)
        if state_get(c, "plus_weekly_danger_threshold") is None:
            state_set(c, "plus_weekly_danger_threshold", DEFAULT_PLUS_WEEKLY_DANGER_THRESHOLD)
        if state_get(c, "official_sync_interval_minutes") is None:
            state_set(c, "official_sync_interval_minutes", DEFAULT_OFFICIAL_SYNC_INTERVAL_MINUTES)
        if state_get(c, "global_sync_interval_hours") is None:
            state_set(c, "global_sync_interval_hours", DEFAULT_GLOBAL_SYNC_INTERVAL_HOURS)
        if state_get(c, "last_global_sync_at") is None:
            state_set(c, "last_global_sync_at", epoch())

        # Cap persisted switch history, including records created by older versions.
        if table_exists(c, "history"):
            c.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 6)")


def rows_to_dict(rows):
    return [dict(r) for r in rows]


def clamp_percent(value, default):
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def account_risk(a, five_threshold, plus_weekly_threshold):
    if not a:
        return {"five_hour_low": True, "weekly_low": False, "dangerous": True}
    five_low = int(a.get("five_hour_remaining", 100) or 0) < five_threshold
    weekly_low = (a.get("user_type") == "Plus" and int(a.get("weekly_remaining", 100) or 0) < plus_weekly_threshold)
    return {"five_hour_low": five_low, "weekly_low": weekly_low, "dangerous": five_low or weekly_low}


def get_state():
    now = epoch()
    with conn() as c:
        # A completed 5-hour window restores that short-window quota to 100%.
        c.execute(
            "UPDATE accounts SET five_hour_remaining=100,five_hour_reset_at=NULL,updated_at=? "
            "WHERE five_hour_reset_at IS NOT NULL AND five_hour_reset_at<=?",
            (now, now),
        )
        # For bound accounts, 100% means there is no active 5-hour usage window yet.
        # The official API can still expose a moving reset_at while the quota is untouched;
        # suppress that timestamp until the first request consumes quota (<100%).
        c.execute(
            "UPDATE accounts SET five_hour_reset_at=NULL,updated_at=? "
            "WHERE bound_account_id IS NOT NULL AND five_hour_remaining>=100 AND five_hour_reset_at IS NOT NULL",
            (now,),
        )
        accounts = rows_to_dict(c.execute("SELECT * FROM accounts ORDER BY id").fetchall())
        launchers = rows_to_dict(c.execute("SELECT * FROM launchers ORDER BY id").fetchall())
        st = {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM state")}
        history = rows_to_dict(c.execute("SELECT * FROM history ORDER BY id DESC LIMIT 6").fetchall())

    five_threshold = clamp_percent(st.get("five_hour_danger_threshold"), DEFAULT_FIVE_HOUR_DANGER_THRESHOLD)
    plus_weekly_threshold = clamp_percent(st.get("plus_weekly_danger_threshold"), DEFAULT_PLUS_WEEKLY_DANGER_THRESHOLD)
    st["five_hour_danger_threshold"] = str(five_threshold)
    st["plus_weekly_danger_threshold"] = str(plus_weekly_threshold)
    try:
        sync_minutes = int(st.get("official_sync_interval_minutes", DEFAULT_OFFICIAL_SYNC_INTERVAL_MINUTES))
    except (TypeError, ValueError):
        sync_minutes = DEFAULT_OFFICIAL_SYNC_INTERVAL_MINUTES
    if sync_minutes not in ALLOWED_OFFICIAL_SYNC_INTERVAL_MINUTES:
        sync_minutes = DEFAULT_OFFICIAL_SYNC_INTERVAL_MINUTES
    try:
        global_hours = int(st.get("global_sync_interval_hours", DEFAULT_GLOBAL_SYNC_INTERVAL_HOURS))
    except (TypeError, ValueError):
        global_hours = DEFAULT_GLOBAL_SYNC_INTERVAL_HOURS
    global_hours = max(1, min(168, global_hours))
    st["official_sync_interval_minutes"] = str(sync_minutes)
    st["global_sync_interval_hours"] = str(global_hours)

    account_map = {a["id"]: a for a in accounts}
    active = st.get("active_launcher", "A")
    active_launcher = next((l for l in launchers if l["id"] == active), None)
    active_account_id = active_launcher.get("account_id") if active_launcher else None
    enabled = [l for l in launchers if l["enabled"]]

    next_launcher = None
    recommendation = {
        "mode": "none",
        "warning": None,
        "five_hour_threshold": five_threshold,
        "plus_weekly_threshold": plus_weekly_threshold,
    }
    if enabled:
        ids = [l["id"] for l in enabled]
        start = ids.index(active) if active in ids else -1
        rotated = [enabled[(start + i) % len(enabled)] for i in range(1, len(enabled) + 1)]
        candidates = [l for l in rotated if l["id"] != active and account_map.get(l.get("account_id"))]
        distinct = [l for l in candidates if l.get("account_id") != active_account_id]
        pool = distinct or candidates

        safe = [l for l in pool if not account_risk(account_map.get(l.get("account_id")), five_threshold, plus_weekly_threshold)["dangerous"]]
        if safe:
            # Preserve the familiar launcher rotation among accounts that are safe for another session.
            next_launcher = safe[0]["id"]
            recommendation["mode"] = "safe"
        elif pool:
            # No safe account remains. Recommend the account whose 5-hour window will recover first.
            # Missing reset timestamps sort last because there is no known near-term recovery time.
            def fallback_key(l):
                a = account_map.get(l.get("account_id")) or {}
                reset_at = a.get("five_hour_reset_at")
                reset_rank = int(reset_at) if reset_at and int(reset_at) > now else 2**62
                return (reset_rank, -int(a.get("five_hour_remaining", 0) or 0), -int(a.get("weekly_remaining", 0) or 0), l["id"])

            choice = sorted(pool, key=fallback_key)[0]
            next_launcher = choice["id"]
            recommendation["mode"] = "unsafe_fallback"
            risks = [account_risk(account_map.get(l.get("account_id")), five_threshold, plus_weekly_threshold) for l in pool]
            if risks and all(r["five_hour_low"] for r in risks):
                recommendation["warning"] = "all_five_hour_low"
            elif account_risk(account_map.get(choice.get("account_id")), five_threshold, plus_weekly_threshold)["weekly_low"]:
                recommendation["warning"] = "plus_weekly_low"
            else:
                recommendation["warning"] = "low_quota"

    return {
        "launchers": launchers,
        "accounts": accounts,
        "state": st,
        "history": history,
        "next_launcher": next_launcher,
        "recommendation": recommendation,
        "db_path": str(DB_PATH),
        "max_launchers": MAX_LAUNCHERS,
        "max_accounts": MAX_ACCOUNTS,
        "labs": {"desktop_ui_backups": desktop_settings_backup_status()},
        "server_time": now,
        "version": APP_VERSION,
        "port": int(st.get("port", DEFAULT_PORT)),
    }


def expand(p):
    return os.path.expanduser(p)


def quit_chatgpt():
    subprocess.run(["osascript", "-e", 'tell application "ChatGPT" to quit'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if subprocess.run(["pgrep", "-x", "ChatGPT"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            return
        time.sleep(0.2)
    subprocess.run(["pkill", "-x", "ChatGPT"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)


def set_active_launcher(pid, reason="manual"):
    with conn() as c:
        if not c.execute("SELECT 1 FROM launchers WHERE id=? AND enabled=1", (pid,)).fetchone():
            raise ValueError("Unknown or disabled launcher")
        old = state_get(c, "active_launcher")
        state_set(c, "active_launcher", pid)
        state_set(c, "last_switch_at", epoch())
        if old != pid:
            c.execute(
                "INSERT INTO history(from_launcher,to_launcher,switched_at,reason) VALUES(?,?,?,?)",
                (old, pid, epoch(), reason),
            )
            # Keep only the six most recent switch records.
            c.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 6)")


def launch_profile(pid):
    with conn() as c:
        p = c.execute("SELECT * FROM launchers WHERE id=? AND enabled=1", (pid,)).fetchone()
        if not p:
            raise ValueError("Unknown or disabled launcher")
    if not Path(CHATGPT_APP).exists():
        raise RuntimeError(f"ChatGPT app not found at {CHATGPT_APP}")
    quit_chatgpt()
    if pid == "A":
        cmd = ["open", "-a", CHATGPT_APP]
    else:
        ch, dd = expand(p["codex_home"]), expand(p["desktop_data_dir"])
        if not ch or not dd:
            raise ValueError("Isolated launchers require CODEX_HOME and Desktop data directory")
        Path(ch).mkdir(parents=True, exist_ok=True)
        Path(dd).mkdir(parents=True, exist_ok=True)
        cmd = ["open", "-n", "--env", f"CODEX_HOME={ch}", "-a", CHATGPT_APP, "--args", f"--user-data-dir={dd}"]
    subprocess.run(cmd, check=True)
    set_active_launcher(pid, "launch")



def close_current_launcher(pid):
    pid = str(pid or "").strip().upper()
    with conn() as c:
        active = state_get(c, "active_launcher", "")
        if not active or active != pid:
            raise ValueError("Only the currently marked launcher can be closed")
        if not c.execute("SELECT 1 FROM launchers WHERE id=?", (pid,)).fetchone():
            raise ValueError("Unknown launcher")
    quit_chatgpt()
    with conn() as c:
        state_set(c, "active_launcher", "")
        state_set(c, "last_switch_at", epoch())
        state_set(c, "last_closed_launcher", pid)
        state_set(c, "last_closed_at", epoch())



def launcher_auth_home(launcher_row):
    """Return the CODEX_HOME whose auth.json represents this launcher's signed-in Codex account."""
    if not launcher_row:
        raise ValueError("Unknown launcher")
    if launcher_row["id"] == "A":
        return Path.home() / ".codex"
    raw = str(launcher_row["codex_home"] or "").strip()
    if not raw:
        raise ValueError("Launcher has no CODEX_HOME configured")
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def read_launcher_oauth(launcher_row):
    """Read only the minimum OAuth routing data needed for binding/sync; raw tokens are never persisted."""
    home = launcher_auth_home(launcher_row)
    auth_path = home / "auth.json"
    if not auth_path.is_file():
        raise ValueError(f"No Codex auth.json found for launcher {launcher_row['id']}: {auth_path}")
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Cannot read Codex auth.json for launcher {launcher_row['id']}: {e}")
    tokens = data.get("tokens") if isinstance(data, dict) else None
    tokens = tokens if isinstance(tokens, dict) else {}
    access_token = str(tokens.get("access_token") or "").strip()
    account_id = str(tokens.get("account_id") or "").strip()
    if not access_token or not account_id:
        raise ValueError("This launcher does not have a ChatGPT OAuth account available for quota sync")
    return {"home": home, "auth_path": auth_path, "access_token": access_token, "account_id": account_id}


def _percent_remaining_from_window(window):
    if not isinstance(window, dict):
        return None
    if window.get("percent_left") is not None:
        try:
            return clamp_percent(round(float(window["percent_left"])), 100)
        except (TypeError, ValueError):
            pass
    if window.get("used_percent") is not None:
        try:
            return clamp_percent(round(100.0 - float(window["used_percent"])), 100)
        except (TypeError, ValueError):
            pass
    return None


def _reset_at_from_window(window):
    if not isinstance(window, dict):
        return None
    for key in ("reset_at", "reset_time", "reset_time_s"):
        value = window.get(key)
        if value is not None:
            try:
                return int(float(value))
            except (TypeError, ValueError):
                pass
    value = window.get("reset_time_ms")
    if value is not None:
        try:
            return int(float(value) / 1000.0)
        except (TypeError, ValueError):
            pass
    return None


def parse_wham_usage(payload):
    """Normalize current and legacy WHAM rate-limit shapes into 5h/week remaining + reset timestamps."""
    if not isinstance(payload, dict):
        raise ValueError("Unexpected quota response")
    rate = payload.get("rate_limit") or payload.get("rate_limits") or {}
    windows = []
    if isinstance(rate, dict):
        # Current shape: primary/secondary_window with limit_window_seconds.
        for key, value in rate.items():
            if isinstance(value, dict):
                windows.append((key, value))
        # Legacy aliases sometimes nest five_hour/week explicitly.
        for key in ("five_hour", "5h", "weekly", "week", "seven_day"):
            value = rate.get(key)
            if isinstance(value, dict) and (key, value) not in windows:
                windows.append((key, value))

    five = weekly = None
    for key, window in windows:
        seconds = window.get("limit_window_seconds") if isinstance(window, dict) else None
        try:
            seconds = int(seconds) if seconds is not None else None
        except (TypeError, ValueError):
            seconds = None
        lk = str(key).lower()
        target = None
        if seconds is not None:
            if 4 * 3600 <= seconds <= 6 * 3600:
                target = "five"
            elif 6 * 24 * 3600 <= seconds <= 8 * 24 * 3600:
                target = "weekly"
        if target is None:
            if "five" in lk or lk == "5h" or "primary" in lk:
                target = "five"
            elif "week" in lk or "seven" in lk or "secondary" in lk:
                target = "weekly"
        normalized = {"remaining": _percent_remaining_from_window(window), "reset_at": _reset_at_from_window(window)}
        if target == "five" and five is None:
            five = normalized
        elif target == "weekly" and weekly is None:
            weekly = normalized

    if five is None and weekly is None:
        raise ValueError("Quota response did not contain recognizable 5-hour/week rate-limit windows")
    return {
        "plan_type": str(payload.get("plan_type") or "").strip() or None,
        "five": five or {},
        "weekly": weekly or {},
    }


def fetch_wham_usage(access_token, account_id):
    req = Request(
        "https://chatgpt.com/backend-api/wham/usage",
        headers={
            "Authorization": f"Bearer {access_token}",
            "ChatGPT-Account-Id": account_id,
            "OpenAI-Beta": "codex-1",
            "originator": "codex_cli_rs",
            "Accept": "application/json",
            "User-Agent": f"Codex-Switcher/{APP_VERSION}",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=12) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        if e.code in (401, 403):
            raise ValueError("Codex login is expired or unauthorized. Re-open this launcher and sign in again, then retry sync.")
        raise ValueError(f"Quota service returned HTTP {e.code}")
    except URLError as e:
        raise ValueError(f"Cannot reach quota service: {getattr(e, 'reason', e)}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("Quota service returned invalid JSON")


def bind_real_account(launcher_id):
    launcher_id = str(launcher_id or "").strip().upper()
    with conn() as c:
        launcher_row = c.execute("SELECT * FROM launchers WHERE id=?", (launcher_id,)).fetchone()
        if not launcher_row:
            raise ValueError("Unknown launcher")
        active = state_get(c, "active_launcher", "A")
        if launcher_id != active:
            raise ValueError("Only the currently active launcher can bind its signed-in account")
        account_id = launcher_row["account_id"]
        if not account_id:
            raise ValueError("Bind an account mnemonic to this launcher first")
        oauth = read_launcher_oauth(launcher_row)
        now = epoch()
        c.execute(
            "UPDATE accounts SET bound_account_id=?,bound_auth_home=?,bound_at=?,updated_at=? WHERE id=?",
            (oauth["account_id"], str(oauth["home"]), now, now, account_id),
        )
    return sync_real_account(launcher_id)


def sync_real_account(launcher_id):
    launcher_id = str(launcher_id or "").strip().upper()
    with conn() as c:
        launcher_row = c.execute("SELECT * FROM launchers WHERE id=?", (launcher_id,)).fetchone()
        if not launcher_row:
            raise ValueError("Unknown launcher")
        account_id = launcher_row["account_id"]
        if not account_id:
            raise ValueError("This launcher has no account mnemonic")
        account_row = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not account_row:
            raise ValueError("Unknown account mnemonic")
        if not account_row["bound_account_id"]:
            raise ValueError("This account mnemonic has not been bound to a real Codex account")
        oauth = read_launcher_oauth(launcher_row)
        if oauth["account_id"] != account_row["bound_account_id"]:
            # The user may have signed out/in to another already-bound Codex account
            # inside this launcher without updating Codex Switcher first. Try to repair
            # the local launcher→mnemonic mapping automatically before treating it as
            # an error. This keeps the real-account binding authoritative while making
            # manual in-app account switches self-healing on the next Sync now.
            matched_account = c.execute(
                "SELECT * FROM accounts WHERE bound_account_id=? ORDER BY id LIMIT 1",
                (oauth["account_id"],),
            ).fetchone()
            if not matched_account:
                raise ValueError("The launcher is signed in to a different Codex account and no matching local bound account was found")
            account_id = int(matched_account["id"])
            account_row = matched_account
            c.execute(
                "UPDATE launchers SET account_id=?,updated_at=? WHERE id=?",
                (account_id, epoch(), launcher_id),
            )

    usage = parse_wham_usage(fetch_wham_usage(oauth["access_token"], oauth["account_id"]))
    five = usage.get("five") or {}
    weekly = usage.get("weekly") or {}
    now = epoch()
    fields = ["last_sync_at=?", "bound_plan_type=?", "updated_at=?"]
    values = [now, usage.get("plan_type"), now]
    if five.get("remaining") is not None:
        five_remaining = max(0, min(100, int(five["remaining"])))
        fields.append("five_hour_remaining=?")
        values.append(five_remaining)
        # 100% means no active 5-hour window has started. The API may report a
        # provisional/moving reset time in this state, so always clear it.
        fields.append("five_hour_reset_at=?")
        if five_remaining >= 100:
            values.append(None)
        else:
            values.append(int(five["reset_at"]) if five.get("reset_at") is not None else None)
    elif five.get("reset_at") is not None:
        # Only accept a reset timestamp when we also know the quota is below 100%.
        # Without a remaining value, preserve the existing window state instead of
        # starting a countdown from an ambiguous API timestamp.
        pass
    if weekly.get("remaining") is not None:
        fields.append("weekly_remaining=?")
        values.append(int(weekly["remaining"]))
    if weekly.get("reset_at") is not None:
        fields.append("weekly_reset_at=?")
        values.append(int(weekly["reset_at"]))
    values.append(account_id)
    with conn() as c:
        c.execute(f"UPDATE accounts SET {','.join(fields)} WHERE id=?", values)
    return get_state()

def sync_all_bound_accounts():
    """Refresh each distinct bound account once, using one configured launcher for its auth home."""
    with conn() as c:
        rows = c.execute(
            "SELECT l.id launcher_id,a.id account_id FROM launchers l "
            "JOIN accounts a ON a.id=l.account_id "
            "WHERE l.enabled=1 AND a.bound_account_id IS NOT NULL ORDER BY l.id"
        ).fetchall()
    seen = set()
    results = []
    for row in rows:
        aid = int(row["account_id"])
        if aid in seen:
            continue
        seen.add(aid)
        lid = row["launcher_id"]
        try:
            sync_real_account(lid)
            results.append({"launcher_id": lid, "account_id": aid, "ok": True})
        except Exception as e:
            results.append({"launcher_id": lid, "account_id": aid, "ok": False, "error": str(e)})
    with conn() as c:
        state_set(c, "last_global_sync_at", epoch())
    return {"results": results, "state": get_state()}

def set_custom_five_hour_reset(aid, target_ts):
    aid = int(aid)
    target_ts = int(target_ts)
    now = epoch()
    # Keep the persisted state clean: custom correction must be future and no more than 5 hours away.
    if target_ts <= now:
        raise ValueError("Custom reset time must be later than now")
    if target_ts - now > 5 * 60 * 60:
        raise ValueError("Custom reset time cannot be more than 5 hours from now")
    with conn() as c:
        row = c.execute("SELECT bound_account_id FROM accounts WHERE id=?", (aid,)).fetchone()
        if not row:
            raise ValueError("Unknown account mnemonic")
        if row["bound_account_id"]:
            raise ValueError("Bound account reset times are read-only; use Sync now")
        c.execute("UPDATE accounts SET five_hour_reset_at=?,updated_at=? WHERE id=?", (target_ts, now, aid))



def launcher_codex_home(pid):
    """Resolve the CODEX_HOME used by a launcher without mutating any Codex state."""
    pid = str(pid or "").strip().upper()
    with conn() as c:
        row = c.execute("SELECT * FROM launchers WHERE id=?", (pid,)).fetchone()
        if not row:
            raise ValueError("Unknown launcher")
        if pid == "A":
            return str(Path.home() / ".codex")
        raw = str(row["codex_home"] or "").strip()
        if not raw:
            raise ValueError("Launcher has no CODEX_HOME configured")
        return expand(raw)


def desktop_settings_backup_dir(pid):
    pid = str(pid).strip().upper()
    return DATA_DIR / "backups" / "desktop-settings" / pid


def latest_desktop_settings_backup(pid):
    backup_dir = desktop_settings_backup_dir(pid)
    if not backup_dir.is_dir():
        return None
    backups = sorted(backup_dir.glob("config-*.toml"), reverse=True)
    return backups[0] if backups else None


def desktop_settings_backup_status():
    result = {}
    try:
        with conn() as c:
            launcher_ids = [r["id"] for r in c.execute("SELECT id FROM launchers WHERE enabled=1 ORDER BY id").fetchall()]
    except Exception:
        launcher_ids = list(LAUNCHER_IDS)
    for pid in launcher_ids:
        path = latest_desktop_settings_backup(pid)
        result[pid] = {
            "available": bool(path),
            "path": str(path) if path else "",
            "modified_at": int(path.stat().st_mtime) if path and path.exists() else None,
        }
    return result


def reset_launcher_desktop_settings(pid):
    """Back up config.toml, then remove only [desktop] and [desktop.*] tables."""
    pid = str(pid).strip().upper()
    with conn() as c:
        active = state_get(c, "active_launcher", "")
    if active == pid:
        quit_chatgpt()
    home = Path(launcher_codex_home(pid))
    config = home / "config.toml"
    if not config.is_file():
        raise ValueError(f"config.toml was not found for launcher {pid}: {config}")

    backup_dir = desktop_settings_backup_dir(pid)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"config-{stamp}.toml"
    shutil.copy2(config, backup)

    text = config.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    output = []
    skipping = False
    removed_sections = []
    section_re = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$")

    for line in lines:
        match = section_re.match(line.rstrip("\\r\\n"))
        if match:
            section = match.group(1).strip()
            is_desktop = section == "desktop" or section.startswith("desktop.")
            if is_desktop:
                skipping = True
                removed_sections.append(section)
                continue
            skipping = False
        if not skipping:
            output.append(line)

    if not removed_sections:
        return {
            "launcher_id": pid,
            "changed": False,
            "backup": str(backup),
            "config": str(config),
            "removed_sections": [],
        }

    tmp = config.with_name(config.name + ".codex-switcher-tmp")
    tmp.write_text("".join(output), encoding="utf-8")
    os.replace(tmp, config)
    return {
        "launcher_id": pid,
        "changed": True,
        "backup": str(backup),
        "config": str(config),
        "removed_sections": removed_sections,
    }


def restore_launcher_desktop_settings(pid):
    """Restore the most recent config.toml backup created by the Labs repair tool."""
    pid = str(pid).strip().upper()
    backup = latest_desktop_settings_backup(pid)
    if not backup:
        raise ValueError(f"No Desktop UI backup is available for launcher {pid}")
    with conn() as c:
        active = state_get(c, "active_launcher", "")
    if active == pid:
        quit_chatgpt()
    home = Path(launcher_codex_home(pid))
    config = home / "config.toml"
    home.mkdir(parents=True, exist_ok=True)

    # Preserve the current post-repair config before restoration as an emergency rollback copy.
    rollback_dir = desktop_settings_backup_dir(pid)
    if config.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        rollback = rollback_dir / f"pre-restore-{stamp}.toml"
        shutil.copy2(config, rollback)
    shutil.copy2(backup, config)
    return {
        "launcher_id": pid,
        "restored_from": str(backup),
        "config": str(config),
    }


def read_launcher_workspaces(pid):
    """Read local-projects from one launcher's Codex global state. Read-only by design."""
    home = Path(launcher_codex_home(pid))
    candidates = [home / ".codex-global-state.json", home / ".codex-global-state.json.bak"]
    source = next((x for x in candidates if x.is_file()), None)
    if source is None:
        return {
            "launcher_id": str(pid).upper(),
            "codex_home": str(home),
            "source": str(candidates[0]),
            "projects": [],
            "exists": False,
            "read_only": True,
        }
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Unable to read Codex workspace state: {e}")

    raw_projects = payload.get("local-projects") or {}
    projects = []
    if isinstance(raw_projects, dict):
        for key, item in raw_projects.items():
            if not isinstance(item, dict):
                continue
            roots = item.get("rootPaths") or []
            if not isinstance(roots, list):
                roots = []
            roots = [str(x) for x in roots if isinstance(x, str) and x.strip()]
            projects.append({
                "id": str(item.get("id") or key),
                "name": str(item.get("name") or "Unnamed workspace"),
                "rootPaths": roots,
                "createdAt": item.get("createdAt"),
                "updatedAt": item.get("updatedAt"),
            })
    projects.sort(key=lambda x: (-(int(x.get("updatedAt") or 0)), x.get("name", "").lower()))
    return {
        "launcher_id": str(pid).upper(),
        "codex_home": str(home),
        "source": str(source),
        "projects": projects,
        "exists": True,
        "read_only": True,
    }


def read_launcher_skills(pid):
    """List user-installed skills from one launcher's CODEX_HOME. Read-only."""
    home = Path(launcher_codex_home(pid))
    skills_dir = home / "skills"
    skills = []
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir(), key=lambda x: x.name.lower()):
            if child.name == ".system" or not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue
            file_count = 0
            try:
                for entry in child.rglob("*"):
                    if entry.is_file() and not entry.is_symlink():
                        file_count += 1
            except OSError:
                pass
            skills.append({
                "name": child.name,
                "path": str(child),
                "file_count": file_count,
            })
    return {
        "launcher_id": str(pid).upper(),
        "codex_home": str(home),
        "source": str(skills_dir),
        "skills": skills,
        "exists": skills_dir.is_dir(),
        "read_only": True,
    }


def copy_missing_skills(source_id, target_id):
    """Copy only missing user skills between launchers; never touch .system or overwrite."""
    source_id = str(source_id or "").strip().upper()
    target_id = str(target_id or "").strip().upper()
    if source_id == target_id:
        raise ValueError("Source and target launcher must be different")
    src_home = Path(launcher_codex_home(source_id))
    dst_home = Path(launcher_codex_home(target_id))
    src_dir = src_home / "skills"
    dst_dir = dst_home / "skills"
    if not src_dir.is_dir():
        return {"source_id": source_id, "target_id": target_id, "copied": [], "skipped": [], "source": str(src_dir), "target": str(dst_dir)}
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied, skipped = [], []
    for child in sorted(src_dir.iterdir(), key=lambda x: x.name.lower()):
        if child.name == ".system" or not child.is_dir() or not (child / "SKILL.md").is_file():
            continue
        target = dst_dir / child.name
        if target.exists():
            skipped.append(child.name)
            continue
        # Refuse top-level symlinked skill directories; copy real directories only.
        if child.is_symlink():
            skipped.append(child.name)
            continue
        shutil.copytree(child, target, symlinks=True)
        copied.append(child.name)
    return {
        "source_id": source_id,
        "target_id": target_id,
        "copied": copied,
        "skipped": skipped,
        "source": str(src_dir),
        "target": str(dst_dir),
    }

def open_launcher_skills_dir(pid):
    """Open exactly one launcher's user Skills directory in Finder."""
    skills_dir = Path(launcher_codex_home(pid)) / "skills"
    if not skills_dir.is_dir():
        raise ValueError("Skills directory does not exist")
    subprocess.run(["open", str(skills_dir)], check=False)
    return {"launcher_id": str(pid).upper(), "path": str(skills_dir)}

def valid_color(s):
    s = str(s or "").strip()
    if len(s) == 7 and s[0] == "#" and all(ch in "0123456789abcdefABCDEF" for ch in s[1:]):
        return s.upper()
    raise ValueError("Theme color must be #RRGGBB")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        # Never let SimpleHTTPRequestHandler fall back to os.getcwd().
        # A GUI app can inherit a cwd that is later moved/deleted, which would
        # otherwise make new request handlers crash before routing begins.
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def translate_path(self, path):
        rel = urlparse(path).path.lstrip("/") or "index.html"
        return str(STATIC / rel)

    def send_json(self, obj, status=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def read_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            return self.send_json(get_state())
        if parsed.path == "/api/version":
            return self.send_json({"version": APP_VERSION})
        if parsed.path == "/api/workspaces":
            try:
                from urllib.parse import parse_qs
                pid = (parse_qs(parsed.query).get("id") or [""])[0]
                return self.send_json(read_launcher_workspaces(pid))
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
            except Exception as e:
                return self.send_json({"error": str(e)}, 500)
        if parsed.path == "/api/skills":
            try:
                from urllib.parse import parse_qs
                pid = (parse_qs(parsed.query).get("id") or [""])[0]
                return self.send_json(read_launcher_skills(pid))
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
            except Exception as e:
                return self.send_json({"error": str(e)}, 500)
        return super().do_GET()

    def do_POST(self):
        try:
            d = self.read_json()
            path = self.path

            if path == "/api/launch":
                pid = str(d["id"]).strip().upper()
                try:
                    launch_profile(pid)
                except Exception as launch_error:
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                    return self.send_json({"error": f"Failed to launch profile {pid}: {launch_error}"}, 500)
                return self.send_json({"ok": True, **get_state()})

            if path == "/api/active":
                set_active_launcher(str(d["id"]).strip().upper(), "manual")
                return self.send_json(get_state())

            if path == "/api/close":
                close_current_launcher(str(d["id"]).strip().upper())
                return self.send_json(get_state())

            if path == "/api/skills/copy":
                result = copy_missing_skills(d.get("source_id"), d.get("target_id"))
                return self.send_json({"ok": True, **result})

            if path == "/api/skills/open":
                result = open_launcher_skills_dir(d.get("id"))
                return self.send_json({"ok": True, **result})

            if path == "/api/settings":
                lang = d.get("language")
                appearance = d.get("appearance")
                port = d.get("port")
                welcome_seen = d.get("welcome_seen")
                five_hour_danger_threshold = d.get("five_hour_danger_threshold")
                plus_weekly_danger_threshold = d.get("plus_weekly_danger_threshold")
                official_sync_interval_minutes = d.get("official_sync_interval_minutes")
                global_sync_interval_hours = d.get("global_sync_interval_hours")
                with conn() as c:
                    if lang is not None:
                        if lang not in ("zh-CN", "en"):
                            raise ValueError("Unsupported language")
                        state_set(c, "language", lang)
                    if appearance is not None:
                        if appearance not in ("dark", "light"):
                            raise ValueError("Unsupported appearance")
                        state_set(c, "appearance", appearance)
                    if port is not None:
                        port = int(port)
                        if port < 1024 or port > 65535:
                            raise ValueError("Port must be between 1024 and 65535")
                        state_set(c, "port", port)
                    if welcome_seen is not None:
                        state_set(c, "welcome_seen", "1" if bool(welcome_seen) else "0")
                    if five_hour_danger_threshold is not None:
                        value = int(five_hour_danger_threshold)
                        if value < 0 or value > 100:
                            raise ValueError("5-hour danger threshold must be between 0 and 100")
                        state_set(c, "five_hour_danger_threshold", value)
                    if plus_weekly_danger_threshold is not None:
                        value = int(plus_weekly_danger_threshold)
                        if value < 0 or value > 100:
                            raise ValueError("Plus weekly danger threshold must be between 0 and 100")
                        state_set(c, "plus_weekly_danger_threshold", value)
                    if official_sync_interval_minutes is not None:
                        value = int(official_sync_interval_minutes)
                        if value not in ALLOWED_OFFICIAL_SYNC_INTERVAL_MINUTES:
                            raise ValueError("Official sync interval must be 5, 30, 60, or 180 minutes")
                        state_set(c, "official_sync_interval_minutes", value)
                    if global_sync_interval_hours is not None:
                        value = int(global_sync_interval_hours)
                        if value < 1 or value > 168:
                            raise ValueError("Global sync interval must be between 1 and 168 hours")
                        state_set(c, "global_sync_interval_hours", value)
                return self.send_json(get_state())

            if path == "/api/launcher":
                pid = str(d["id"]).strip().upper()
                if pid not in LAUNCHER_IDS:
                    raise ValueError("Launcher ID must be between A and F")
                color = valid_color(d.get("theme_color") or DEFAULT_COLORS[pid])
                account_id = d.get("account_id")
                account_id = int(account_id) if account_id not in (None, "", 0, "0") else None
                with conn() as c:
                    if account_id and not c.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone():
                        raise ValueError("Unknown account mnemonic")
                    existing = c.execute("SELECT 1 FROM launchers WHERE id=?", (pid,)).fetchone()
                    t = epoch()
                    if pid == "A":
                        if not existing:
                            raise ValueError("System launcher A is missing")
                        c.execute("UPDATE launchers SET codex_home='',desktop_data_dir='',theme_color=?,account_id=?,enabled=1,updated_at=? WHERE id='A'", (color, account_id, t))
                    else:
                        ch = str(d.get("codex_home") or f"~/.codex-profile-{pid.lower()}").strip()
                        dd = str(d.get("desktop_data_dir") or f"~/Library/Application Support/ChatGPT-Profiles/{pid}").strip()
                        if existing:
                            c.execute("UPDATE launchers SET codex_home=?,desktop_data_dir=?,theme_color=?,account_id=?,enabled=1,updated_at=? WHERE id=?", (ch, dd, color, account_id, t, pid))
                        else:
                            if c.execute("SELECT COUNT(*) n FROM launchers").fetchone()["n"] >= MAX_LAUNCHERS:
                                raise ValueError(f"Maximum {MAX_LAUNCHERS} launchers")
                            c.execute("INSERT INTO launchers(id,codex_home,desktop_data_dir,theme_color,account_id,enabled,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)", (pid, ch, dd, color, account_id, t, t))
                return self.send_json(get_state())

            if path == "/api/launcher/delete":
                pid = str(d["id"]).strip().upper()
                if pid == "A":
                    raise ValueError("System launcher A cannot be deleted")
                with conn() as c:
                    c.execute("DELETE FROM launchers WHERE id=?", (pid,))
                    if state_get(c, "active_launcher") == pid:
                        state_set(c, "active_launcher", "A")
                        state_set(c, "last_switch_at", epoch())
                return self.send_json(get_state())

            if path == "/api/account":
                name = str(d.get("name") or "").strip()
                if not name:
                    raise ValueError("Account mnemonic is required")
                user_type = str(d.get("user_type") or "Plus").strip()
                if user_type not in USER_TYPES:
                    raise ValueError("Unsupported user type")
                aid = d.get("id")
                t = epoch()
                with conn() as c:
                    if aid:
                        aid = int(aid)
                        existing = c.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
                        if not existing:
                            raise ValueError("Unknown account mnemonic")
                        if existing["bound_account_id"] and "reset_count" in d and int(d.get("reset_count", existing["reset_count"])) != int(existing["reset_count"] or 0):
                            raise ValueError("Bound account reset count is read-only; use Sync now")
                        reset_count = int(existing["reset_count"] or 0) if existing["bound_account_id"] else max(0, int(d.get("reset_count", existing["reset_count"])))
                        c.execute("UPDATE accounts SET name=?,user_type=?,reset_count=?,updated_at=? WHERE id=?", (name, user_type, reset_count, t, aid))
                    else:
                        if c.execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"] >= MAX_ACCOUNTS:
                            raise ValueError(f"Maximum {MAX_ACCOUNTS} account mnemonics")
                        reset_count = max(0, int(d.get("reset_count", 0)))
                        c.execute("INSERT INTO accounts(name,user_type,weekly_remaining,five_hour_reset_at,weekly_reset_at,reset_count,created_at,updated_at) VALUES(?,?,100,NULL,NULL,?,?,?)", (name, user_type, reset_count, t, t))
                return self.send_json(get_state())

            if path == "/api/account/delete":
                aid = int(d["id"])
                with conn() as c:
                    if not c.execute("SELECT 1 FROM accounts WHERE id=?", (aid,)).fetchone():
                        raise ValueError("Unknown account mnemonic")
                    c.execute("UPDATE launchers SET account_id=NULL,updated_at=? WHERE account_id=?", (epoch(), aid))
                    c.execute("DELETE FROM accounts WHERE id=?", (aid,))
                return self.send_json(get_state())

            if path == "/api/account/bind-real":
                return self.send_json(bind_real_account(d.get("launcher_id")))

            if path == "/api/account/sync-real":
                return self.send_json(sync_real_account(d.get("launcher_id")))

            if path == "/api/account/sync-global":
                result = sync_all_bound_accounts()
                return self.send_json({"ok": True, **result})

            if path == "/api/account/weekly":
                aid, weekly = int(d["id"]), max(0, min(100, int(d["weekly_remaining"])))
                with conn() as c:
                    row = c.execute("SELECT bound_account_id FROM accounts WHERE id=?", (aid,)).fetchone()
                    if not row:
                        raise ValueError("Unknown account mnemonic")
                    if row["bound_account_id"]:
                        raise ValueError("Bound account quota is read-only; use Sync now")
                    c.execute("UPDATE accounts SET weekly_remaining=?,updated_at=? WHERE id=?", (weekly, epoch(), aid))
                return self.send_json(get_state())

            if path == "/api/account/five-hour-remaining":
                aid, remaining = int(d["id"]), max(0, min(100, int(d["five_hour_remaining"])))
                with conn() as c:
                    row = c.execute("SELECT bound_account_id FROM accounts WHERE id=?", (aid,)).fetchone()
                    if not row:
                        raise ValueError("Unknown account mnemonic")
                    if row["bound_account_id"]:
                        raise ValueError("Bound account quota is read-only; use Sync now")
                    c.execute("UPDATE accounts SET five_hour_remaining=?,updated_at=? WHERE id=?", (remaining, epoch(), aid))
                return self.send_json(get_state())

            if path == "/api/account/weekly-reset":
                aid = int(d["id"])
                target = d.get("weekly_reset_at")
                target = int(target) if target not in (None, "") else None
                with conn() as c:
                    row = c.execute("SELECT bound_account_id FROM accounts WHERE id=?", (aid,)).fetchone()
                    if not row:
                        raise ValueError("Unknown account mnemonic")
                    if row["bound_account_id"]:
                        raise ValueError("Bound account reset times are read-only; use Sync now")
                    c.execute("UPDATE accounts SET weekly_reset_at=?,updated_at=? WHERE id=?", (target, epoch(), aid))
                return self.send_json(get_state())

            if path == "/api/account/reset-count":
                aid, count = int(d["id"]), max(0, int(d["reset_count"]))
                with conn() as c:
                    row = c.execute("SELECT bound_account_id FROM accounts WHERE id=?", (aid,)).fetchone()
                    if not row:
                        raise ValueError("Unknown account mnemonic")
                    if row["bound_account_id"]:
                        raise ValueError("Bound account reset count is read-only; use Sync now")
                    c.execute("UPDATE accounts SET reset_count=?,updated_at=? WHERE id=?", (count, epoch(), aid))
                return self.send_json(get_state())

            if path == "/api/account/increment-reset-count":
                aid = int(d["id"])
                with conn() as c:
                    row = c.execute("SELECT bound_account_id FROM accounts WHERE id=?", (aid,)).fetchone()
                    if not row:
                        raise ValueError("Unknown account mnemonic")
                    if row["bound_account_id"]:
                        raise ValueError("Bound account reset count is read-only; use Sync now")
                    c.execute("UPDATE accounts SET reset_count=reset_count+1,updated_at=? WHERE id=?", (epoch(), aid))
                return self.send_json(get_state())

            if path == "/api/handoff":
                prompt = str(d.get("prompt", ""))
                reply = str(d.get("reply", ""))
                if len(prompt) > 12000 or len(reply) > 200000:
                    raise ValueError("Handoff text is too large")
                with conn() as c:
                    state_set(c, "handoff_prompt", prompt)
                    state_set(c, "handoff_reply", reply)
                return self.send_json(get_state())

            if path == "/api/account/start-five-hour":
                aid = int(d["id"])
                reset_at = epoch() + 5 * 60 * 60
                with conn() as c:
                    row = c.execute("SELECT bound_account_id FROM accounts WHERE id=?", (aid,)).fetchone()
                    if not row:
                        raise ValueError("Unknown account mnemonic")
                    if row["bound_account_id"]:
                        raise ValueError("Bound account reset times are read-only; use Sync now")
                    c.execute("UPDATE accounts SET five_hour_reset_at=?,updated_at=? WHERE id=?", (reset_at, epoch(), aid))
                return self.send_json(get_state())

            if path == "/api/account/custom-five-hour":
                set_custom_five_hour_reset(d["id"], d["target_timestamp"])
                return self.send_json(get_state())

            if path == "/api/account/reset-all":
                aid = int(d["id"])
                consume = bool(d.get("consume_reset_count", False))
                with conn() as c:
                    row = c.execute("SELECT reset_count,bound_account_id FROM accounts WHERE id=?", (aid,)).fetchone()
                    if not row:
                        raise ValueError("Unknown account mnemonic")
                    if row["bound_account_id"]:
                        raise ValueError("Bound account quota and reset count are read-only; use Sync now")
                    if consume:
                        if int(row["reset_count"] or 0) <= 0:
                            raise ValueError("No reset count is available to consume")
                        c.execute(
                            "UPDATE accounts SET weekly_remaining=100,five_hour_remaining=100,five_hour_reset_at=NULL,reset_count=reset_count-1,updated_at=? WHERE id=?",
                            (epoch(), aid),
                        )
                    else:
                        c.execute(
                            "UPDATE accounts SET weekly_remaining=100,five_hour_remaining=100,five_hour_reset_at=NULL,updated_at=? WHERE id=?",
                            (epoch(), aid),
                        )
                return self.send_json(get_state())

            if path == "/api/labs/reset-desktop-ui":
                result = reset_launcher_desktop_settings(d.get("id"))
                return self.send_json({"ok": True, "result": result, "state": get_state()})

            if path == "/api/labs/restore-desktop-ui":
                result = restore_launcher_desktop_settings(d.get("id"))
                return self.send_json({"ok": True, "result": result, "state": get_state()})

            if path == "/api/global/quota-reset":
                with conn() as c:
                    now = epoch()
                    c.execute("UPDATE accounts SET weekly_remaining=100,five_hour_remaining=100,five_hour_reset_at=NULL,updated_at=? WHERE bound_account_id IS NULL", (now,))
                return self.send_json(get_state())

            if path == "/api/global/reset-card":
                with conn() as c:
                    now = epoch()
                    c.execute("UPDATE accounts SET reset_count=reset_count+1,updated_at=? WHERE bound_account_id IS NULL", (now,))
                return self.send_json(get_state())

            return self.send_json({"error": "Not found"}, 404)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"error": str(e)}, 500)



def apply_due_weekly_resets(now=None):
    """Reset due account quotas and roll weekly_reset_at forward by whole 7-day periods.

    Timestamps stay absolute Unix seconds; display conversion remains a client-local concern.
    Returns the number of accounts reset in this pass.
    """
    now = int(now or epoch())
    week = 7 * 24 * 60 * 60
    changed = 0
    with conn() as c:
        rows = c.execute(
            "SELECT id, weekly_reset_at FROM accounts WHERE weekly_reset_at IS NOT NULL AND weekly_reset_at<=?",
            (now,),
        ).fetchall()
        for row in rows:
            next_at = int(row["weekly_reset_at"])
            while next_at <= now:
                next_at += week
            c.execute(
                "UPDATE accounts SET weekly_remaining=100,five_hour_reset_at=NULL,weekly_reset_at=?,updated_at=? WHERE id=?",
                (next_at, now, row["id"]),
            )
            changed += 1
    return changed


def weekly_reset_worker(stop_event):
    # Startup is checked synchronously in main; subsequent checks are intentionally infrequent.
    while not stop_event.wait(30 * 60):
        try:
            apply_due_weekly_resets()
        except Exception as e:
            print(f"Weekly reset check failed: {e}", file=sys.stderr)

def configured_port():
    if PORT_ENV:
        try:
            port = int(PORT_ENV)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
    with conn() as c:
        try:
            port = int(state_get(c, "port", DEFAULT_PORT))
        except (TypeError, ValueError):
            port = DEFAULT_PORT
    return port if 1024 <= port <= 65535 else DEFAULT_PORT


def main():
    import threading
    # Keep a stable cwd even if the app was opened from a folder that is later
    # renamed, moved to Trash, or removed. Static serving does not depend on cwd,
    # but third-party/stdlib helpers may still query it.
    try:
        os.chdir(ROOT if ROOT.is_dir() else DATA_DIR)
    except OSError:
        try:
            os.chdir(DATA_DIR)
        except OSError:
            pass
    migrate_legacy_db_once()
    backup_existing_db_once_per_version()
    ensure_defaults()
    if "--print-port" in sys.argv:
        print(configured_port())
        return
    listen_port = configured_port()
    reset_count = apply_due_weekly_resets()
    if reset_count:
        print(f"Applied {reset_count} due weekly quota reset(s).")
    stop_event = threading.Event()
    reset_thread = threading.Thread(target=weekly_reset_worker, args=(stop_event,), daemon=True, name="weekly-reset-checker")
    reset_thread.start()
    if "--open" in sys.argv:
        # Open after the server has had a moment to bind.
        threading.Timer(0.6, lambda: webbrowser.open(f"http://{HOST}:{listen_port}/?v={APP_VERSION}")).start()
    server = ThreadingHTTPServer((HOST, listen_port), Handler)

    def request_shutdown(signum=None, frame=None):
        # BaseServer.shutdown() must be invoked from a different thread than serve_forever().
        threading.Thread(target=server.shutdown, daemon=True, name="server-shutdown").start()

    try:
        signal.signal(signal.SIGTERM, request_shutdown)
        signal.signal(signal.SIGINT, request_shutdown)
    except (ValueError, AttributeError):
        pass

    print(f"Codex Switcher v{APP_VERSION}: http://{HOST}:{listen_port}")
    print(f"Data: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()


if __name__ == "__main__":
    main()
