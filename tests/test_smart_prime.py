import importlib.util
import tempfile
import time
import unittest
from pathlib import Path


SERVER_PATH = Path(__file__).resolve().parents[1] / "app" / "server.py"
SPEC = importlib.util.spec_from_file_location("codex_switcher_server", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class SmartPrimeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / "launcher.sqlite3"
        server.ensure_defaults()
        with server.conn() as c:
            c.execute("DELETE FROM launchers")
            c.execute("DELETE FROM accounts")
            now = int(time.time())
            for index, launcher_id in enumerate("ABC", 1):
                account = c.execute(
                    "INSERT INTO accounts(name,weekly_remaining,five_hour_remaining,bound_account_id,"
                    "auto_prime_enabled,created_at,updated_at) VALUES(?,100,100,?,1,?,?)",
                    (f"account-{index}", f"real-{index}", now, now),
                )
                c.execute(
                    "INSERT INTO launchers(id,theme_color,account_id,enabled,created_at,updated_at) "
                    "VALUES(?,?,?,1,?,?)",
                    (launcher_id, "#000000", account.lastrowid, now, now),
                )
            server.state_set(c, "labs_smart_prime_enabled", "1")
            server.state_set(c, "labs_smart_prime_work_start_minute", 9 * 60)
            server.state_set(c, "labs_smart_prime_account_minutes", 60)

    def tearDown(self):
        server.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    @staticmethod
    def today_at(hour, minute):
        local = time.localtime()
        return int(time.mktime((
            local.tm_year, local.tm_mon, local.tm_mday,
            hour, minute, 0, -1, -1, -1,
        )))

    def test_three_one_hour_accounts_prime_at_seven_for_noon_reset(self):
        plan = server.smart_prime_plan(self.today_at(6, 0))
        self.assertEqual(plan["account_count"], 3)
        self.assertEqual(plan["round_minutes"], 180)
        self.assertEqual(plan["lead_minutes"], 120)
        self.assertEqual(time.strftime("%H:%M", time.localtime(plan["prime_at"])), "07:00")
        self.assertEqual(time.strftime("%H:%M", time.localtime(plan["target_reset_at"])), "12:00")

    def test_plan_runs_once_inside_grace_and_is_not_caught_up_late(self):
        calls = []
        original = server._prime_launcher_account
        server._prime_launcher_account = lambda launcher_id, **kwargs: (
            calls.append((launcher_id, kwargs)) or {"ok": True, "launcher_id": launcher_id}
        )
        try:
            result = server.run_daily_smart_prime(self.today_at(7, 5))
            self.assertEqual(result["status"], "completed")
            self.assertEqual([call[0] for call in calls], ["A", "B", "C"])
            self.assertIsNone(server.run_daily_smart_prime(self.today_at(7, 6)))

            with server.conn() as c:
                server.state_set(c, "labs_smart_prime_last_plan_date", "")
                server.state_set(c, "labs_smart_prime_last_status", "")
            late = server.run_daily_smart_prime(self.today_at(7, 11))
            self.assertEqual(late["status"], "missed")
            self.assertEqual(len(calls), 3)
        finally:
            server._prime_launcher_account = original

    def test_round_of_five_hours_does_not_prime_early(self):
        with server.conn() as c:
            server.state_set(c, "labs_smart_prime_account_minutes", 100)
        plan = server.smart_prime_plan(self.today_at(6, 0))
        self.assertEqual(plan["status"], "not_needed")
        self.assertIsNone(server.run_daily_smart_prime(self.today_at(9, 0)))


if __name__ == "__main__":
    unittest.main()
