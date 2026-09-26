import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SERVER_PATH = Path(__file__).resolve().parents[1] / "app" / "server.py"
SPEC = importlib.util.spec_from_file_location("codex_switcher_sync_error_server", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class SyncErrorStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / "launcher.sqlite3"
        server.ensure_defaults()
        with server.conn() as c:
            account = c.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()
            self.account_id = int(account["id"])
            c.execute(
                "UPDATE accounts SET bound_account_id='acct-test',bound_auth_home='/tmp/codex-test' WHERE id=?",
                (self.account_id,),
            )

    def tearDown(self):
        server.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def oauth(self):
        return {"home": Path("/tmp/codex-test"), "access_token": "token", "account_id": "acct-test"}

    def test_expired_login_is_exposed_as_login_required(self):
        error = "Codex login is expired or unauthorized. Re-open this launcher and sign in again, then retry sync."
        with mock.patch.object(server, "read_launcher_oauth", return_value=self.oauth()), mock.patch.object(
            server, "fetch_wham_usage", side_effect=ValueError(error)
        ):
            with self.assertRaisesRegex(ValueError, "expired or unauthorized"):
                server.sync_real_account("A")

        account = next(a for a in server.get_state()["accounts"] if a["id"] == self.account_id)
        self.assertEqual(account["sync_error_code"], "login_required")
        self.assertEqual(account["sync_error"], error)
        self.assertIsNotNone(account["sync_error_at"])

    def test_missing_auth_file_is_exposed_as_login_required(self):
        error = "No Codex auth.json found for launcher A: /tmp/codex-test/auth.json"
        with mock.patch.object(server, "read_launcher_oauth", side_effect=ValueError(error)):
            with self.assertRaisesRegex(ValueError, "No Codex auth.json"):
                server.sync_real_account("A")

        account = next(a for a in server.get_state()["accounts"] if a["id"] == self.account_id)
        self.assertEqual(account["sync_error_code"], "login_required")
        self.assertEqual(account["sync_error"], error)

    def test_existing_missing_auth_error_is_backfilled_on_startup(self):
        with server.conn() as c:
            c.execute(
                "UPDATE accounts SET sync_error='No Codex auth.json found for launcher A: /tmp/auth.json',"
                "sync_error_code=NULL WHERE id=?",
                (self.account_id,),
            )

        server.ensure_defaults()

        account = next(a for a in server.get_state()["accounts"] if a["id"] == self.account_id)
        self.assertEqual(account["sync_error_code"], "login_required")

    def test_successful_sync_clears_previous_error(self):
        with server.conn() as c:
            c.execute(
                "UPDATE accounts SET sync_error='old error',sync_error_code='login_required',sync_error_at=1 WHERE id=?",
                (self.account_id,),
            )
        usage = {
            "plan_type": "plus",
            "rate_limit": {
                "primary_window": {"limit_window_seconds": 18000, "used_percent": 20, "reset_at": 2_000_000_000},
                "secondary_window": {"limit_window_seconds": 604800, "used_percent": 30, "reset_at": 2_000_100_000},
            },
        }
        with mock.patch.object(server, "read_launcher_oauth", return_value=self.oauth()), mock.patch.object(
            server, "fetch_wham_usage", return_value=usage
        ):
            state = server.sync_real_account("A")

        account = next(a for a in state["accounts"] if a["id"] == self.account_id)
        self.assertIsNone(account["sync_error"])
        self.assertIsNone(account["sync_error_code"])
        self.assertIsNone(account["sync_error_at"])


if __name__ == "__main__":
    unittest.main()
