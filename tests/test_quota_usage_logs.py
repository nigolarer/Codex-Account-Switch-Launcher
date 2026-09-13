import importlib.util
import tempfile
import time
import unittest
from pathlib import Path


SERVER_PATH = Path(__file__).resolve().parents[1] / "app" / "server.py"
SPEC = importlib.util.spec_from_file_location("codex_switcher_quota_server", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class QuotaUsageLogTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / "launcher.sqlite3"
        server.ensure_defaults()
        with server.conn() as c:
            account = c.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()
            self.account_id = int(account["id"])
            server.state_set(c, "active_launcher", "A")

    def tearDown(self):
        server.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_records_consumption_between_official_snapshots(self):
        now = int(time.time())
        with server.conn() as c:
            server.record_quota_usage(c, self.account_id, "A", now, 90, 80)
            server.record_quota_usage(c, self.account_id, "A", now + 300, 70, 75)

        logs = server.get_state()["quota_usage_logs"]
        self.assertEqual(len(logs), 2)
        latest = logs[0]
        self.assertEqual(latest["previous_observed_at"], now)
        self.assertEqual(latest["five_hour_consumed"], 20)
        self.assertEqual(latest["weekly_consumed"], 5)
        self.assertEqual(latest["five_hour_reset"], 0)
        self.assertEqual(latest["weekly_reset"], 0)

    def test_quota_increase_is_marked_as_reset_not_negative_usage(self):
        now = int(time.time())
        with server.conn() as c:
            server.record_quota_usage(c, self.account_id, "A", now, 10, 5)
            server.record_quota_usage(c, self.account_id, "A", now + 300, 100, 100)

        latest = server.get_state()["quota_usage_logs"][0]
        self.assertEqual(latest["five_hour_consumed"], 0)
        self.assertEqual(latest["weekly_consumed"], 0)
        self.assertEqual(latest["five_hour_reset"], 1)
        self.assertEqual(latest["weekly_reset"], 1)

    def test_state_only_returns_logs_for_active_account(self):
        now = int(time.time())
        with server.conn() as c:
            other = c.execute(
                "INSERT INTO accounts(name,created_at,updated_at) VALUES('other',?,?)",
                (now, now),
            ).lastrowid
            server.record_quota_usage(c, self.account_id, "A", now, 90, 90)
            server.record_quota_usage(c, other, "B", now, 50, 50)

        logs = server.get_state()["quota_usage_logs"]
        self.assertEqual([row["account_id"] for row in logs], [self.account_id])


if __name__ == "__main__":
    unittest.main()
