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

    def record_samples(self, samples, step=300):
        start = 1700000000
        with server.conn() as c:
            for i, (five, weekly, launcher) in enumerate(samples):
                server.record_quota_usage(
                    c, self.account_id, launcher, start + i * step, five, weekly,
                )
        return start

    def test_three_zero_intervals_become_fifteen_minutes_without_deleting_samples(self):
        start = self.record_samples([(90, 80, "A")] * 4)
        logs = server.get_state()["quota_usage_logs"]
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["merged_count"], 3)
        self.assertEqual(logs[0]["previous_observed_at"], start)
        self.assertEqual(logs[0]["observed_at"], start + 900)
        self.assertIsNone(logs[1]["previous_observed_at"])
        with server.conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM quota_usage_logs").fetchone()[0], 4)

    def test_either_usage_reset_or_launcher_change_breaks_a_group(self):
        for boundary in ((89, 80, "A"), (90, 79, "A"),
                         (100, 80, "A"), (90, 100, "A"), (90, 80, "B")):
            with self.subTest(boundary=boundary):
                with server.conn() as c:
                    c.execute("DELETE FROM quota_usage_logs")
                self.record_samples([(90, 80, "A")] * 3 + [boundary] * 3)
                logs = server.get_state()["quota_usage_logs"]
                if boundary[2] == "B":
                    self.assertEqual([r["merged_count"] for r in logs], [3, 2, 1])
                else:
                    self.assertEqual([r["merged_count"] for r in logs], [2, 1, 2, 1])

    def test_missing_values_are_not_assumed_to_be_zero_usage(self):
        for missing in ((None, 80, "A"), (90, None, "A")):
            with self.subTest(missing=missing):
                with server.conn() as c:
                    c.execute("DELETE FROM quota_usage_logs")
                self.record_samples([(90, 80, "A")] * 3 + [missing] * 2 + [(90, 80, "A")] * 3)
                logs = server.get_state()["quota_usage_logs"]
                self.assertEqual([r["merged_count"] for r in logs], [2, 1, 1, 1, 2, 1])

    def test_groups_include_exactly_48_hours_then_start_a_new_group(self):
        start = self.record_samples([(90, 80, "A")] * 11, step=6 * 3600)
        logs = server.get_state()["quota_usage_logs"]
        self.assertEqual([r["merged_count"] for r in logs], [2, 8, 1])
        self.assertEqual(logs[1]["observed_at"], start + 48 * 3600)
        self.assertEqual(logs[0]["previous_observed_at"], logs[1]["observed_at"])
        for row in logs[:-1]:
            self.assertLessEqual(row["observed_at"] - row["previous_observed_at"], 48 * 3600)

    def test_compacts_before_applying_the_48_display_row_limit(self):
        start = self.record_samples([(90, 80, "A")] * 101)
        logs = server.get_state()["quota_usage_logs"]
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["merged_count"], 100)
        self.assertEqual(logs[0]["previous_observed_at"], start)

    def test_noncontiguous_intervals_are_not_merged(self):
        self.record_samples([(90, 80, "A")] * 5)
        with server.conn() as c:
            c.execute("UPDATE quota_usage_logs SET previous_observed_at=previous_observed_at+1 "
                      "WHERE observed_at=(SELECT MAX(observed_at) FROM quota_usage_logs)")
        logs = server.get_state()["quota_usage_logs"]
        self.assertEqual([r["merged_count"] for r in logs], [1, 3, 1])


if __name__ == "__main__":
    unittest.main()
