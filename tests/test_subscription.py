import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location('subscription_server', Path(__file__).resolve().parents[1] / 'app/server.py')
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.launcher = {'id': 'B', 'codex_home': str(self.home)}
        self.claims = {
            'chatgpt_account_id': 'acct-test',
            'chatgpt_plan_type': 'plus',
            'chatgpt_subscription_active_until': '2026-11-08T03:24:38+00:00',
            'chatgpt_subscription_last_checked': '2026-10-23T03:48:49.833133Z',
        }
        self.addCleanup(self.temp.cleanup)

    def write_auth(self, claims=None, account_id='acct-test'):
        payload = {'https://api.openai.com/auth': self.claims if claims is None else claims}
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        (self.home / 'auth.json').write_text(json.dumps({'tokens': {
            'account_id': account_id, 'id_token': 'header.' + encoded + '.signature',
        }}))

    def test_reads_only_subscription_metadata(self):
        self.write_auth()
        result = server.read_launcher_subscription(self.launcher, 'acct-test')
        self.assertEqual(result['plan_type'], 'plus')
        self.assertEqual(result['active_until'], int(server.datetime(2026, 11, 8, 3, 24, 38, tzinfo=server.timezone.utc).timestamp()))
        self.assertIsInstance(result['last_checked_at'], int)
        self.assertEqual(set(result), {'plan_type', 'active_until', 'last_checked_at'})

    def test_different_login_and_unbound_accounts_are_hidden(self):
        self.write_auth(account_id='another-account')
        self.assertIsNone(server.read_launcher_subscription(self.launcher, 'acct-test'))
        self.write_auth({**self.claims, 'chatgpt_account_id': 'another-account'})
        self.assertIsNone(server.read_launcher_subscription(self.launcher, 'acct-test'))
        self.write_auth()
        self.assertIsNone(server.read_launcher_subscription(self.launcher, None))

    def test_missing_invalid_and_free_subscription_are_hidden(self):
        self.assertIsNone(server.read_launcher_subscription(self.launcher, 'acct-test'))
        for value in (None, '', 'invalid', '2026-11-08T03:24:38', 123):
            self.write_auth({**self.claims, 'chatgpt_subscription_active_until': value})
            self.assertIsNone(server.read_launcher_subscription(self.launcher, 'acct-test'))
        self.write_auth({**self.claims, 'chatgpt_plan_type': 'free'})
        self.assertIsNone(server.read_launcher_subscription(self.launcher, 'acct-test'))
        for token in ('invalid', 'a.!!!!.c', 'a.W10.c'):
            (self.home / 'auth.json').write_text(json.dumps({'tokens': {'account_id': 'acct-test', 'id_token': token}}))
            self.assertIsNone(server.read_launcher_subscription(self.launcher, 'acct-test'))

    def test_past_snapshot_and_invalid_optional_checked_time(self):
        self.write_auth({**self.claims, 'chatgpt_subscription_active_until': '2020-01-01T00:00:00Z',
                         'chatgpt_subscription_last_checked': 'invalid'})
        result = server.read_launcher_subscription(self.launcher, 'acct-test')
        self.assertIsNotNone(result)  # Keep the recorded date; do not infer live membership status.
        self.assertIsNone(result['last_checked_at'])

    def test_state_uses_active_launchers_actual_login(self):
        self.write_auth()
        with mock.patch.object(server, 'DB_PATH', self.home / 'test.sqlite3'):
            server.ensure_defaults()
            with server.conn() as c:
                aid = c.execute('SELECT account_id FROM launchers WHERE id="A"').fetchone()[0]
                c.execute('UPDATE accounts SET bound_account_id="acct-test" WHERE id=?', (aid,))
            with mock.patch.object(server, 'launcher_auth_home', return_value=self.home):
                self.assertIsNotNone(server.get_state()['current_subscription'])
                self.write_auth(account_id='another-account')
                self.assertIsNone(server.get_state()['current_subscription'])


if __name__ == '__main__':
    unittest.main()
