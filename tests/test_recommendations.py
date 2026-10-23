import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("recommendation_server", Path(__file__).resolve().parents[1] / "app/server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
NOW = 1800000000


class RecommendationTests(unittest.TestCase):
    def test_recovery_window_and_each_quota(self):
        for quota in ("weekly", "five_hour"):
            for remaining in (0, 4):
                for delay, expected in ((None, False), (-1, False), (0, False), (1, True), (1800, True), (1801, False), (18000, False)):
                    with self.subTest(quota=quota, remaining=remaining, delay=delay):
                        a = {"weekly_remaining": 100, "five_hour_remaining": 100,
                             f"{quota}_remaining": remaining,
                             f"{quota}_reset_at": NOW + delay if delay is not None else None}
                        self.assertEqual(server.recommendation_eligible(a, NOW), expected)
        self.assertFalse(server.recommendation_eligible(None, NOW))
        self.assertTrue(server.recommendation_eligible({"weekly_remaining": 5, "five_hour_remaining": 5}, NOW))
        self.assertFalse(server.recommendation_eligible({"weekly_remaining": 0, "weekly_reset_at": NOW + 1801,
                                                        "five_hour_remaining": 0, "five_hour_reset_at": NOW + 60}, NOW))

    def test_same_bound_account_is_never_suggested(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(server, "DB_PATH", Path(temp) / "test.sqlite3"), patch.object(server, "epoch", return_value=NOW):
            server.ensure_defaults()
            with server.conn() as c:
                c.execute("DELETE FROM launchers")
                c.execute("DELETE FROM accounts")
                ids = {}
                for lid, bound_id in (("A", "same-real-account"), ("B", "same-real-account"), ("C", "different-real-account")):
                    ids[lid] = c.execute("INSERT INTO accounts(name,bound_account_id,weekly_remaining,five_hour_remaining,created_at,updated_at) VALUES(?,?,100,100,?,?)", (lid, bound_id, NOW, NOW)).lastrowid
                    c.execute("INSERT INTO launchers(id,codex_home,desktop_data_dir,account_id,enabled,created_at,updated_at) VALUES(?,'','',?,1,?,?)", (lid, ids[lid], NOW, NOW))
                server.state_set(c, "active_launcher", "A")
            state = server.get_state()
            self.assertEqual(state["suggested_launchers"], ["C"])
            self.assertEqual(state["next_launcher"], "C")
            # Same mnemonic and distinct mnemonics bound to the same account
            # must both leave an empty recommendation, including fallback mode.
            for shared_mnemonic in (False, True):
                with self.subTest(shared_mnemonic=shared_mnemonic):
                    with server.conn() as c:
                        c.execute("UPDATE launchers SET enabled=0 WHERE id='C'")
                        c.execute("UPDATE launchers SET account_id=? WHERE id='B'", (ids["A"] if shared_mnemonic else ids["B"],))
                        c.execute("UPDATE accounts SET five_hour_remaining=0,five_hour_reset_at=?", (NOW + 60,))
                    state = server.get_state()
                    self.assertEqual(state["suggested_launchers"], [])
                    self.assertIsNone(state["next_launcher"])
                    self.assertEqual(state["recommendation"]["mode"], "none")
                    self.assertIsNone(state["recommendation"]["warning"])
                    self.assertEqual(len(state["launchers"]), 3)

    def test_state_limits_suggestions_and_preserves_excluded_launchers(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(server, "DB_PATH", Path(temp) / "test.sqlite3"), patch.object(server, "epoch", return_value=NOW):
            server.ensure_defaults()
            with server.conn() as c:
                c.execute("DELETE FROM launchers")
                c.execute("DELETE FROM accounts")
                for lid in "ABCDEF":
                    aid = c.execute("INSERT INTO accounts(name,weekly_remaining,five_hour_remaining,created_at,updated_at) VALUES(?,100,100,?,?)", (lid, NOW, NOW)).lastrowid
                    c.execute("INSERT INTO launchers(id,codex_home,desktop_data_dir,account_id,enabled,created_at,updated_at) VALUES(?,'','',?,1,?,?)", (lid, aid, NOW, NOW))
                server.state_set(c, "active_launcher", "A")
            self.assertEqual(server.get_state()["suggested_launchers"], ["B", "C", "D"])
            with server.conn() as c:
                c.execute("UPDATE accounts SET weekly_remaining=0,weekly_reset_at=? WHERE name='B'", (NOW + 86400,))
                c.execute("UPDATE accounts SET five_hour_remaining=0,five_hour_reset_at=? WHERE name='C'", (NOW + 18000,))
                c.execute("UPDATE accounts SET five_hour_remaining=0,five_hour_reset_at=? WHERE name='D'", (NOW + 1800,))
            state = server.get_state()
            self.assertEqual(state["suggested_launchers"], ["E", "F", "D"])
            self.assertEqual(state["next_launcher"], "E")
            self.assertEqual(len(state["launchers"]), 6)
            with server.conn() as c:
                c.execute("UPDATE accounts SET weekly_remaining=0,weekly_reset_at=NULL WHERE name!='A'")
            state = server.get_state()
            self.assertEqual(state["suggested_launchers"], [])
            self.assertIsNone(state["next_launcher"])


if __name__ == "__main__":
    unittest.main()
