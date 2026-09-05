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
import threading
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

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
APP_VERSION = "0.22.5"

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
  codex_account_id TEXT,
  detected_plan_type TEXT,
  last_synced_at INTEGER,
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
QUOTA_SYNC_INTERVALS = (5, 10, 30, 60)
BACKGROUND_ACCOUNT_REFRESH_DEFAULT_HOURS = 6
BACKGROUND_ACCOUNT_REFRESH_MIN_HOURS = 1
BACKGROUND_ACCOUNT_REFRESH_MAX_HOURS = 720
BACKGROUND_SWEEP_POLL_SECONDS = 30 * 60
USER_TYPES = ("Plus", "Pro X10", "Pro X20", "Ultra")
LAUNCHER_RUNTIME = {}
CODEX_ACCOUNT_QUERY_LOCK = threading.RLock()


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


def migrate_schema_v9(c):
    """Account identity binding + live Codex quota cache."""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(accounts)").fetchall()}
    if "five_hour_remaining" not in cols:
        c.execute("ALTER TABLE accounts ADD COLUMN five_hour_remaining INTEGER NOT NULL DEFAULT 100")
    if "codex_account_id" not in cols:
        c.execute("ALTER TABLE accounts ADD COLUMN codex_account_id TEXT")
    if "detected_plan_type" not in cols:
        c.execute("ALTER TABLE accounts ADD COLUMN detected_plan_type TEXT")
    if "last_synced_at" not in cols:
        c.execute("ALTER TABLE accounts ADD COLUMN last_synced_at INTEGER")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_codex_account_id ON accounts(codex_account_id) WHERE codex_account_id IS NOT NULL")


def ensure_defaults():
    with conn() as c:
        migrate_profiles_to_v4(c)
        migrate_schema_v8(c)
        migrate_schema_v9(c)
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
        if not state_get(c, "quota_sync_interval_minutes"):
            state_set(c, "quota_sync_interval_minutes", 5)
        if not state_get(c, "background_account_refresh_hours"):
            state_set(c, "background_account_refresh_hours", BACKGROUND_ACCOUNT_REFRESH_DEFAULT_HOURS)
        if state_get(c, "handoff_prompt") is None:
            state_set(c, "handoff_prompt", "")
        if state_get(c, "handoff_reply") is None:
            state_set(c, "handoff_reply", "")

        # Cap persisted switch history, including records created by older versions.
        if table_exists(c, "history"):
            c.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 6)")


def rows_to_dict(rows):
    return [dict(r) for r in rows]


def account_available(a):
    if not a:
        return False
    if int(a.get("weekly_remaining", 0)) <= 0:
        return False
    # Synced Codex accounts always carry a *next* 5-hour reset timestamp, even
    # while they still have quota. Use the real remaining percentage for those.
    if a.get("codex_account_id"):
        return int(a.get("five_hour_remaining", 0)) > 0
    # Legacy/manual accounts use five_hour_reset_at as the local unavailable timer.
    reset_at = a.get("five_hour_reset_at")
    return not reset_at or int(reset_at) <= epoch()


def get_state():
    with conn() as c:
        accounts = rows_to_dict(c.execute("SELECT * FROM accounts ORDER BY id").fetchall())
        launchers = rows_to_dict(c.execute("SELECT * FROM launchers ORDER BY id").fetchall())
        st = {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM state")}
        history = rows_to_dict(c.execute("SELECT * FROM history ORDER BY id DESC LIMIT 6").fetchall())

    account_map = {a["id"]: a for a in accounts}
    active = st.get("active_launcher", "A")
    active_launcher = next((l for l in launchers if l["id"] == active), None)
    active_runtime = LAUNCHER_RUNTIME.get(active) or {}
    active_account_id = active_runtime.get("bound_account_id") or (active_launcher.get("account_id") if active_launcher else None)
    enabled = [l for l in launchers if l["enabled"]]

    next_launcher = None
    next_launcher_unavailable = False
    next_launcher_available_at = None
    if enabled:
        ids = [l["id"] for l in enabled]
        start = ids.index(active) if active in ids else -1
        rotated = [enabled[(start + i) % len(enabled)] for i in range(1, len(enabled) + 1)]
        others = [l for l in rotated if l["id"] != active and account_map.get(l.get("account_id"))]
        # First prefer an actually usable launcher on a distinct account.
        distinct = [l for l in others if l.get("account_id") != active_account_id and account_available(account_map.get(l.get("account_id")))]
        fallback = [l for l in others if account_available(account_map.get(l.get("account_id")))]
        choice = distinct or fallback
        if choice:
            next_launcher = choice[0]["id"]
        elif others:
            # Never leave Suggested Next blank merely because every account is temporarily
            # exhausted. Show the account that is expected to recover first.
            def recovery_key(launcher_row):
                account_row = account_map.get(launcher_row.get("account_id")) or {}
                blockers = []
                if int(account_row.get("weekly_remaining") or 0) <= 0:
                    ts = account_row.get("weekly_reset_at")
                    blockers.append(int(ts) if ts else 2**62)
                five_ts = account_row.get("five_hour_reset_at")
                five_blocked = (int(account_row.get("five_hour_remaining") or 0) <= 0) if account_row.get("codex_account_id") else bool(five_ts and int(five_ts) > epoch())
                if five_blocked and five_ts and int(five_ts) > epoch():
                    blockers.append(int(five_ts))
                recovery = max(blockers) if blockers else epoch()
                distinct_penalty = 0 if launcher_row.get("account_id") != active_account_id else 1
                return (distinct_penalty, recovery, rotated.index(launcher_row))
            candidate = min(others, key=recovery_key)
            next_launcher = candidate["id"]
            next_launcher_unavailable = True
            a = account_map.get(candidate.get("account_id")) or {}
            blockers = []
            if int(a.get("weekly_remaining") or 0) <= 0 and a.get("weekly_reset_at"):
                blockers.append(int(a["weekly_reset_at"]))
            five_ts = a.get("five_hour_reset_at")
            five_blocked = (int(a.get("five_hour_remaining") or 0) <= 0) if a.get("codex_account_id") else bool(five_ts and int(five_ts) > epoch())
            if five_blocked and five_ts and int(five_ts) > epoch():
                blockers.append(int(five_ts))
            if blockers:
                next_launcher_available_at = max(blockers)

    return {
        "launchers": launchers,
        "accounts": accounts,
        "state": st,
        "history": history,
        "next_launcher": next_launcher,
        "next_launcher_unavailable": next_launcher_unavailable,
        "next_launcher_available_at": next_launcher_available_at,
        "db_path": str(DB_PATH),
        "max_launchers": MAX_LAUNCHERS,
        "max_accounts": MAX_ACCOUNTS,
        "labs": {"desktop_ui_backups": desktop_settings_backup_status()},
        "launcher_runtime": {k: dict(v) for k, v in LAUNCHER_RUNTIME.items()},
        "server_time": epoch(),
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


def _chatgpt_process_lines():
    """Return ChatGPT/Codex Desktop process command lines without starting anything."""
    try:
        out = subprocess.check_output(["ps", "-axo", "command="], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    marker = "/ChatGPT.app/Contents/MacOS/ChatGPT"
    return [line for line in out.splitlines() if marker in line]


def is_launcher_running(pid):
    """Best-effort check that the configured launcher is the currently running Desktop profile."""
    pid = str(pid or "").strip().upper()
    with conn() as c:
        row = c.execute("SELECT * FROM launchers WHERE id=?", (pid,)).fetchone()
    if not row:
        return False
    lines = _chatgpt_process_lines()
    if not lines:
        return False
    if pid == "A":
        # The system/default launcher has no explicit user-data-dir. Ignore helper
        # processes belonging to an isolated profile.
        return any("--user-data-dir=" not in line for line in lines)
    data_dir = expand(row["desktop_data_dir"])
    return bool(data_dir) and any((f"--user-data-dir={data_dir}" in line) or (data_dir in line) for line in lines)


def sync_launcher_if_running(pid, reason="scheduled", quiet=False):
    """Sync exactly one launcher, but only while that Desktop launcher is running."""
    pid = str(pid or "").strip().upper()
    if not pid or not is_launcher_running(pid):
        return {"ok": False, "skipped": True, "reason": "launcher-not-running"}
    try:
        info = read_codex_account_info(pid)
        with conn() as c:
            state_set(c, "quota_last_auto_sync_at", epoch())
            state_set(c, "quota_last_auto_sync_reason", reason)
        return {"ok": True, "info": info}
    except Exception as e:
        if not quiet:
            print(f"Quota sync ({reason}) failed for launcher {pid}: {e}", file=sys.stderr)
        return {"ok": False, "error": str(e)}


def _delayed_launcher_sync(pid, reason, delay=1.5):
    """Give Desktop a moment to start before the first quota read."""
    import threading
    def run():
        time.sleep(delay)
        sync_launcher_if_running(pid, reason)
    threading.Thread(target=run, daemon=True, name=f"quota-sync-{pid.lower()}-{reason}").start()


def launch_profile(pid):
    pid = str(pid or "").strip().upper()
    with conn() as c:
        p = c.execute("SELECT * FROM launchers WHERE id=? AND enabled=1", (pid,)).fetchone()
        if not p:
            raise ValueError("Unknown or disabled launcher")
        previous = state_get(c, "active_launcher", "")
    if not Path(CHATGPT_APP).exists():
        raise RuntimeError(f"ChatGPT app not found at {CHATGPT_APP}")

    # A launcher switch is also a close event for the currently running profile.
    # Capture its final live quota before Desktop is terminated. Never wake an
    # inactive profile just to refresh stale data.
    if previous:
        sync_launcher_if_running(previous, "before-switch-close", quiet=True)

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
    _delayed_launcher_sync(pid, "after-launch")



def close_current_launcher(pid):
    pid = str(pid or "").strip().upper()
    with conn() as c:
        active = state_get(c, "active_launcher", "")
        if not active or active != pid:
            raise ValueError("Only the currently marked launcher can be closed")
        if not c.execute("SELECT 1 FROM launchers WHERE id=?", (pid,)).fetchone():
            raise ValueError("Unknown launcher")
    # Final best-effort live snapshot happens before Desktop exits. If Desktop is
    # already gone, this is skipped rather than spawning an app-server for it.
    sync_launcher_if_running(pid, "before-close", quiet=True)
    quit_chatgpt()
    with conn() as c:
        state_set(c, "active_launcher", "")
        state_set(c, "last_switch_at", epoch())
        state_set(c, "last_closed_launcher", pid)
        state_set(c, "last_closed_at", epoch())


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
        if not c.execute("SELECT 1 FROM accounts WHERE id=?", (aid,)).fetchone():
            raise ValueError("Unknown account mnemonic")
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


def codex_executable():
    explicit = os.environ.get("CODEX_CLI", "").strip()
    candidates = [
        explicit,
        str(Path(CHATGPT_APP) / "Contents/Resources/codex"),
        "/Applications/ChatGPT.app/Contents/Resources/codex",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("codex")
    if found:
        return found
    raise ValueError("Codex executable was not found")


def _read_jsonrpc_response(proc, target_id, timeout=15):
    """Read newline-delimited app-server output until the requested JSON-RPC response arrives."""
    import select
    deadline = time.time() + timeout
    stdout_fd = proc.stdout.fileno()
    stderr_fd = proc.stderr.fileno()
    buffer = getattr(proc, "_codex_stdout_buffer", b"")
    while time.time() < deadline:
        # Consume all complete lines already buffered before waiting for more bytes.
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            if not raw.strip():
                continue
            try:
                message = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if message.get("id") == target_id:
                proc._codex_stdout_buffer = buffer
                return message
        if proc.poll() is not None:
            break
        ready, _, _ = select.select([stdout_fd, stderr_fd], [], [], min(0.5, max(0.0, deadline - time.time())))
        for fd in ready:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                continue
            if fd == stdout_fd:
                buffer += chunk
            # stderr is intentionally drained but not treated as protocol data.
    proc._codex_stdout_buffer = buffer
    raise TimeoutError(f"Codex app-server did not respond to request {target_id}")


def _read_codex_account_info_unlocked(pid, update_runtime=True):
    """Ask Codex app-server for the account identity and rate limits for one launcher.

    This intentionally does not read auth.json or any token itself. Codex owns authentication.
    """
    pid = str(pid).upper()
    env = os.environ.copy()
    env["CODEX_HOME"] = launcher_codex_home(pid)
    proc = subprocess.Popen(
        [codex_executable(), "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
        env=env,
    )
    try:
        def send(payload):
            proc.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
            proc.stdin.flush()

        send({"method": "initialize", "id": 1, "params": {"clientInfo": {"name": "codex-switcher", "version": APP_VERSION}}})
        init = _read_jsonrpc_response(proc, 1, timeout=10)
        if "error" in init:
            raise ValueError(f"Codex initialize failed: {init['error']}")

        send({"method": "account/rateLimits/read", "id": 2})
        response = _read_jsonrpc_response(proc, 2, timeout=15)
        if "error" in response:
            raise ValueError(f"Codex rate limit read failed: {response['error']}")
        result = response.get("result") or {}
        limits = result.get("rateLimits") or {}
        account_id = result.get("accountId")
        if not account_id:
            raise ValueError("Codex did not return an accountId; the launcher may not be signed in")

        windows = [limits.get("primary"), limits.get("secondary")]
        five = next((w for w in windows if w and int(w.get("windowDurationMins") or 0) == 300), None)
        weekly = next((w for w in windows if w and int(w.get("windowDurationMins") or 0) == 10080), None)
        reset_credits = result.get("rateLimitResetCredits") or {}
        info = {
            "launcher_id": pid,
            "codex_account_id": str(account_id),
            "plan_type": limits.get("planType"),
            "five_hour_remaining": None if not five else max(0, min(100, 100 - int(five.get("usedPercent") or 0))),
            "five_hour_used": None if not five else int(five.get("usedPercent") or 0),
            "five_hour_reset_at": None if not five else five.get("resetsAt"),
            "weekly_remaining": None if not weekly else max(0, min(100, 100 - int(weekly.get("usedPercent") or 0))),
            "weekly_used": None if not weekly else int(weekly.get("usedPercent") or 0),
            "weekly_reset_at": None if not weekly else weekly.get("resetsAt"),
            "reset_count": int(reset_credits.get("availableCount") or 0),
            "synced_at": epoch(),
        }

        with conn() as c:
            bound = c.execute("SELECT * FROM accounts WHERE codex_account_id=?", (info["codex_account_id"],)).fetchone()
            info["bound_account_id"] = bound["id"] if bound else None
            info["bound_account_name"] = bound["name"] if bound else None
            if bound:
                fields = ["reset_count=?", "detected_plan_type=?", "last_synced_at=?", "updated_at=?"]
                values = [info["reset_count"], info["plan_type"], info["synced_at"], info["synced_at"]]
                if info["five_hour_remaining"] is not None:
                    fields += ["five_hour_remaining=?", "five_hour_reset_at=?"]
                    values += [info["five_hour_remaining"], info["five_hour_reset_at"]]
                if info["weekly_remaining"] is not None:
                    fields += ["weekly_remaining=?", "weekly_reset_at=?"]
                    values += [info["weekly_remaining"], info["weekly_reset_at"]]
                values.append(bound["id"])
                c.execute(f"UPDATE accounts SET {','.join(fields)} WHERE id=?", tuple(values))
        if update_runtime:
            LAUNCHER_RUNTIME[pid] = info
        return info
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def read_codex_account_info(pid, update_runtime=True):
    # Serialize app-server account reads. Besides reducing process churn, this lets
    # a background sweep re-check freshness after an active-launcher sync and avoid
    # querying the same real account twice during the same startup window.
    with CODEX_ACCOUNT_QUERY_LOCK:
        return _read_codex_account_info_unlocked(pid, update_runtime=update_runtime)


def quota_sync_interval_minutes():
    with conn() as c:
        try:
            value = int(state_get(c, "quota_sync_interval_minutes", 5))
        except (TypeError, ValueError):
            value = 5
    return value if value in QUOTA_SYNC_INTERVALS else 5


def background_account_refresh_hours():
    with conn() as c:
        try:
            value = int(state_get(c, "background_account_refresh_hours", BACKGROUND_ACCOUNT_REFRESH_DEFAULT_HOURS))
        except (TypeError, ValueError):
            value = BACKGROUND_ACCOUNT_REFRESH_DEFAULT_HOURS
    if value < BACKGROUND_ACCOUNT_REFRESH_MIN_HOURS:
        return BACKGROUND_ACCOUNT_REFRESH_DEFAULT_HOURS
    return min(value, BACKGROUND_ACCOUNT_REFRESH_MAX_HOURS)


def refresh_stale_bound_accounts(reason="background-sweep"):
    """Refresh each stale bound account at most once, without launching Desktop GUI.

    Accounts are deduplicated by the stable Codex accountId. A launcher is only a
    transport for the query; the returned accountId is verified before the target
    account is considered refreshed. Duplicate launchers for the same mnemonic are
    tried only as fallbacks.
    """
    now = epoch()
    stale_after = background_account_refresh_hours() * 60 * 60
    with conn() as c:
        accounts = rows_to_dict(c.execute(
            "SELECT * FROM accounts WHERE codex_account_id IS NOT NULL AND codex_account_id<>'' ORDER BY id"
        ).fetchall())
        launchers = rows_to_dict(c.execute(
            "SELECT * FROM launchers WHERE enabled=1 ORDER BY id"
        ).fetchall())

    due = []
    for a in accounts:
        last = int(a.get("last_synced_at") or 0)
        if not last or now - last >= stale_after:
            candidates = [l for l in launchers if l.get("account_id") == a.get("id")]
            if candidates:
                due.append((a, candidates))

    refreshed_codex_ids = set()
    attempted_launchers = set()
    results = []
    for account_row, candidates in due:
        expected = str(account_row.get("codex_account_id") or "")
        if not expected or expected in refreshed_codex_ids:
            continue
        matched = False
        for launcher_row in candidates:
            pid = str(launcher_row["id"]).upper()
            if pid in attempted_launchers:
                continue
            attempted_launchers.add(pid)
            try:
                with CODEX_ACCOUNT_QUERY_LOCK:
                    # Another path (usually the active launcher startup/interval sync) may
                    # have refreshed this account while the sweep was waiting. Re-check
                    # inside the same lock so a stale account is never queried twice.
                    with conn() as c:
                        latest = c.execute("SELECT last_synced_at FROM accounts WHERE id=?", (account_row["id"],)).fetchone()
                    latest_at = int(latest["last_synced_at"] or 0) if latest else 0
                    if latest_at and epoch() - latest_at < stale_after:
                        matched = True
                        break
                    info = _read_codex_account_info_unlocked(pid, update_runtime=is_launcher_running(pid))
                actual = str(info.get("codex_account_id") or "")
                if actual:
                    refreshed_codex_ids.add(actual)
                results.append({"launcher_id": pid, "expected_account_id": expected, "actual_account_id": actual, "matched": actual == expected})
                if actual == expected:
                    matched = True
                    break
            except Exception as e:
                results.append({"launcher_id": pid, "expected_account_id": expected, "error": str(e), "matched": False})
        if not matched:
            # Keep the target stale. A mismatching launcher may still have safely refreshed
            # the account it actually contains; it is never written into the expected row.
            pass
    with conn() as c:
        state_set(c, "background_account_last_sweep_at", now)
        state_set(c, "background_account_last_sweep_reason", reason)
    return {"ok": True, "due_accounts": len(due), "results": results}


def sync_active_launcher_account(reason="scheduled"):
    """Refresh only the currently active, actually running Desktop launcher."""
    with conn() as c:
        pid = str(state_get(c, "active_launcher", "") or "").strip().upper()
    if not pid:
        return {"ok": False, "skipped": True, "reason": "no-active-launcher"}
    return sync_launcher_if_running(pid, reason)

def bind_detected_account(pid, mnemonic_id):
    pid = str(pid).upper()
    mnemonic_id = int(mnemonic_id)
    info = LAUNCHER_RUNTIME.get(pid)
    if not info or epoch() - int(info.get("synced_at") or 0) > 120:
        info = read_codex_account_info(pid)
    codex_id = info["codex_account_id"]
    with conn() as c:
        target = c.execute("SELECT * FROM accounts WHERE id=?", (mnemonic_id,)).fetchone()
        if not target:
            raise ValueError("Unknown account mnemonic")
        other = c.execute("SELECT id,name FROM accounts WHERE codex_account_id=? AND id<>?", (codex_id, mnemonic_id)).fetchone()
        if other:
            raise ValueError(f"This Codex account is already bound to mnemonic '{other['name']}'")
        if target["codex_account_id"] and target["codex_account_id"] != codex_id:
            raise ValueError("This mnemonic is already bound to another Codex account. Unbind it first.")
        c.execute("UPDATE accounts SET codex_account_id=?,detected_plan_type=?,last_synced_at=?,updated_at=? WHERE id=?", (codex_id, info.get("plan_type"), epoch(), epoch(), mnemonic_id))
        # Keep the launcher's selected mnemonic aligned with the binding the user just confirmed.
        c.execute("UPDATE launchers SET account_id=?,updated_at=? WHERE id=?", (mnemonic_id, epoch(), pid))
    info["bound_account_id"] = mnemonic_id
    info["bound_account_name"] = target["name"]
    LAUNCHER_RUNTIME[pid] = info
    # Sync live quota values immediately now that the identity has a local account row.
    read_codex_account_info(pid)
    return get_state()


def unbind_account(mnemonic_id):
    mnemonic_id = int(mnemonic_id)
    with conn() as c:
        row = c.execute("SELECT * FROM accounts WHERE id=?", (mnemonic_id,)).fetchone()
        if not row:
            raise ValueError("Unknown account mnemonic")
        c.execute("UPDATE accounts SET codex_account_id=NULL,detected_plan_type=NULL,last_synced_at=NULL,updated_at=? WHERE id=?", (epoch(), mnemonic_id))
    for info in LAUNCHER_RUNTIME.values():
        if info.get("bound_account_id") == mnemonic_id:
            info["bound_account_id"] = None
            info["bound_account_name"] = None
    return get_state()


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
        if parsed.path == "/api/launcher/account-info":
            try:
                from urllib.parse import parse_qs
                query = parse_qs(parsed.query)
                pid = str((query.get("id") or [""])[0]).strip().upper()
                manual = str((query.get("manual") or ["0"])[0]).lower() in ("1", "true", "yes")
                with conn() as c:
                    active = str(state_get(c, "active_launcher", "") or "").strip().upper()
                    launcher_row = c.execute("SELECT * FROM launchers WHERE id=? AND enabled=1", (pid,)).fetchone()
                    account_row = None
                    if launcher_row and launcher_row["account_id"]:
                        account_row = c.execute("SELECT * FROM accounts WHERE id=?", (launcher_row["account_id"],)).fetchone()
                if not launcher_row:
                    raise ValueError("Unknown or disabled launcher")
                running_current = bool(active and pid == active and is_launcher_running(pid))
                if not running_current:
                    if not manual:
                        raise ValueError("Quota sync is available only for the current running launcher")
                    if not account_row or not account_row["codex_account_id"]:
                        raise ValueError("Manual sync requires a bound account mnemonic")
                    last = int(account_row["last_synced_at"] or 0)
                    if last and epoch() - last <= 60:
                        raise ValueError("This account was synced less than 1 minute ago")
                info = read_codex_account_info(pid, update_runtime=running_current)
                if running_current:
                    with conn() as c:
                        state_set(c, "quota_last_auto_sync_at", epoch())
                        state_set(c, "quota_last_auto_sync_reason", "manual")
                return self.send_json({"info": info, "state": get_state()})
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
            except TimeoutError as e:
                return self.send_json({"error": str(e)}, 504)
            except Exception as e:
                return self.send_json({"error": str(e)}, 500)
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
                    sync_interval = d.get("quota_sync_interval_minutes")
                    if sync_interval is not None:
                        sync_interval = int(sync_interval)
                        if sync_interval not in QUOTA_SYNC_INTERVALS:
                            raise ValueError("Quota sync interval must be 5, 10, 30, or 60 minutes")
                        state_set(c, "quota_sync_interval_minutes", sync_interval)
                    background_hours = d.get("background_account_refresh_hours")
                    if background_hours is not None:
                        background_hours = int(background_hours)
                        if background_hours < BACKGROUND_ACCOUNT_REFRESH_MIN_HOURS or background_hours > BACKGROUND_ACCOUNT_REFRESH_MAX_HOURS:
                            raise ValueError("Background account refresh must be between 1 and 720 hours")
                        state_set(c, "background_account_refresh_hours", background_hours)
                    if welcome_seen is not None:
                        state_set(c, "welcome_seen", "1" if bool(welcome_seen) else "0")
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

            if path == "/api/account/bind":
                return self.send_json(bind_detected_account(d.get("launcher_id"), d.get("account_id")))

            if path == "/api/account/unbind":
                return self.send_json(unbind_account(d.get("id")))

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
                        reset_count = max(0, int(d.get("reset_count", existing["reset_count"])))
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

            if path == "/api/account/weekly":
                aid, weekly = int(d["id"]), max(0, min(100, int(d["weekly_remaining"])))
                with conn() as c:
                    c.execute("UPDATE accounts SET weekly_remaining=?,updated_at=? WHERE id=?", (weekly, epoch(), aid))
                    if c.total_changes == 0:
                        raise ValueError("Unknown account mnemonic")
                return self.send_json(get_state())

            if path == "/api/account/weekly-reset":
                aid = int(d["id"])
                target = d.get("weekly_reset_at")
                target = int(target) if target not in (None, "") else None
                with conn() as c:
                    if not c.execute("SELECT 1 FROM accounts WHERE id=?", (aid,)).fetchone():
                        raise ValueError("Unknown account mnemonic")
                    c.execute("UPDATE accounts SET weekly_reset_at=?,updated_at=? WHERE id=?", (target, epoch(), aid))
                return self.send_json(get_state())

            if path == "/api/account/reset-count":
                aid, count = int(d["id"]), max(0, int(d["reset_count"]))
                with conn() as c:
                    c.execute("UPDATE accounts SET reset_count=?,updated_at=? WHERE id=?", (count, epoch(), aid))
                return self.send_json(get_state())

            if path == "/api/account/increment-reset-count":
                aid = int(d["id"])
                with conn() as c:
                    if not c.execute("SELECT 1 FROM accounts WHERE id=?", (aid,)).fetchone():
                        raise ValueError("Unknown account mnemonic")
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
                    if not c.execute("SELECT 1 FROM accounts WHERE id=?", (aid,)).fetchone():
                        raise ValueError("Unknown account mnemonic")
                    c.execute("UPDATE accounts SET five_hour_reset_at=?,updated_at=? WHERE id=?", (reset_at, epoch(), aid))
                return self.send_json(get_state())

            if path == "/api/account/custom-five-hour":
                set_custom_five_hour_reset(d["id"], d["target_timestamp"])
                return self.send_json(get_state())

            if path == "/api/account/reset-all":
                aid = int(d["id"])
                consume = bool(d.get("consume_reset_count", False))
                with conn() as c:
                    row = c.execute("SELECT reset_count FROM accounts WHERE id=?", (aid,)).fetchone()
                    if not row:
                        raise ValueError("Unknown account mnemonic")
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
                    c.execute("UPDATE accounts SET weekly_remaining=100,five_hour_remaining=100,five_hour_reset_at=NULL,updated_at=?", (now,))
                return self.send_json(get_state())

            if path == "/api/global/reset-card":
                with conn() as c:
                    now = epoch()
                    c.execute("UPDATE accounts SET reset_count=reset_count+1,updated_at=?", (now,))
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
                "UPDATE accounts SET weekly_remaining=100,five_hour_remaining=100,five_hour_reset_at=NULL,weekly_reset_at=?,updated_at=? WHERE id=?",
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


def quota_sync_worker(stop_event):
    # Poll the setting frequently enough that changing 60 -> 5 minutes takes effect quickly,
    # while actual Codex syncs only run at the configured cadence.
    while not stop_event.wait(15):
        try:
            with conn() as c:
                try:
                    last = int(state_get(c, "quota_last_auto_sync_at", 0) or 0)
                except (TypeError, ValueError):
                    last = 0
            interval = quota_sync_interval_minutes() * 60
            if epoch() - last >= interval:
                sync_active_launcher_account("scheduled")
        except Exception as e:
            print(f"Scheduled quota sync failed: {e}", file=sys.stderr)


def background_account_refresh_worker(stop_event):
    # A sweep is intentionally cheap: every 30 minutes we only check timestamps.
    # Codex app-server is started only for bound accounts whose successful sync is
    # older than the user-configured account refresh window.
    while not stop_event.wait(BACKGROUND_SWEEP_POLL_SECONDS):
        try:
            refresh_stale_bound_accounts("scheduled-background-sweep")
        except Exception as e:
            print(f"Background account refresh failed: {e}", file=sys.stderr)

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
    quota_thread = threading.Thread(target=quota_sync_worker, args=(stop_event,), daemon=True, name="quota-sync-scheduler")
    quota_thread.start()
    background_thread = threading.Thread(target=background_account_refresh_worker, args=(stop_event,), daemon=True, name="background-account-refresh")
    background_thread.start()
    # Startup has two independent refresh paths:
    # 1) the active running launcher gets an immediate live sync;
    # 2) a low-frequency account sweep checks only bound accounts that are stale
    #    beyond the configured refresh window. The sweep may briefly start Codex
    #    app-server for an inactive profile, but never launches the Desktop GUI.
    # Do not advance quota_last_auto_sync_at before the startup sync actually succeeds.
    # If Desktop is still starting, the scheduler should be free to retry on its next
    # 15-second poll instead of waiting a full configured interval.
    threading.Thread(target=lambda: sync_active_launcher_account("switcher-startup"), daemon=True, name="quota-sync-startup").start()
    threading.Thread(target=lambda: refresh_stale_bound_accounts("switcher-startup-sweep"), daemon=True, name="background-account-startup-sweep").start()
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
        # A final best-effort snapshot is limited to the active running launcher.
        # Inactive launchers are never awakened just because Switcher exits.
        try:
            sync_active_launcher_account("switcher-shutdown")
        except Exception as e:
            print(f"Shutdown quota sync failed: {e}", file=sys.stderr)
        server.server_close()


if __name__ == "__main__":
    main()
