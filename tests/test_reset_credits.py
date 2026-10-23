import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location('reset_credits_server', Path(__file__).resolve().parents[1] / 'app/server.py')
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class ResetCreditTests(unittest.TestCase):
    def test_only_available_codex_credits_are_sorted_with_duplicates(self):
        def credit(expiry, status='available', kind='codex_rate_limits'):
            return {'status': status, 'reset_type': kind, 'expires_at': expiry}
        result = server.parse_reset_credit_expirations({'credits': [
            credit(300), credit(200), credit(200), credit(None), credit(100),
            credit(400, 'redeemed'), credit(500, kind='other'),
            credit('1970-01-01T00:04:10Z'),
        ]}, now=100)
        self.assertEqual(result, [200, 200, 250, 300, None])

    def test_malformed_details_are_not_treated_as_empty(self):
        for payload in ({}, {'credits': None}, {'credits': [
            {'status': 'available', 'reset_type': 'codex_rate_limits', 'expires_at': 'bad'}
        ]}):
            with self.assertRaises(ValueError):
                server.parse_reset_credit_expirations(payload)

    def test_zero_count_clears_old_details_without_request(self):
        fields, values = [], []
        with mock.patch.object(server, 'fetch_wham_usage') as fetch:
            server.append_reset_credit_details(fields, values, {}, {'reset_count': 0})
        fetch.assert_not_called()
        self.assertIn('reset_credit_expirations=?', fields)
        self.assertEqual(values[0], '[]')

    def test_sync_persists_details_and_failure_preserves_quota_sync(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(server, 'DB_PATH', Path(temp) / 'test.sqlite3'):
            server.ensure_defaults()
            with server.conn() as c:
                aid = c.execute('SELECT account_id FROM launchers WHERE id="A"').fetchone()[0]
                c.execute('UPDATE accounts SET bound_account_id="acct" WHERE id=?', (aid,))
            oauth = {'access_token': 'test', 'account_id': 'acct'}
            usage = {'rate_limit': {'primary_window': {'used_percent': 20, 'reset_at': 2_000_000_000}},
                     'rate_limit_reset_credits': {'available_count': 2}}
            details = {'credits': [{'status': 'available', 'reset_type': 'codex_rate_limits', 'expires_at': 2_000_000_000}]}
            with mock.patch.object(server, 'read_launcher_oauth', return_value=oauth), mock.patch.object(
                server, 'fetch_wham_usage', side_effect=[usage, details, usage, ValueError('HTTP 429')]
            ):
                first = next(a for a in server.sync_real_account('A')['accounts'] if a['id'] == aid)
                second = next(a for a in server.sync_real_account('A')['accounts'] if a['id'] == aid)
            self.assertEqual(first['reset_credit_expirations'], [2_000_000_000])
            self.assertIsNone(first['reset_credits_error'])
            self.assertEqual(second['five_hour_remaining'], 80)
            self.assertEqual(second['reset_count'], 2)
            self.assertEqual(second['reset_credit_expirations'], first['reset_credit_expirations'])
            self.assertIsNotNone(second['reset_credits_error'])
            self.assertIsNone(second['sync_error'])
            server.ensure_defaults()  # Migration remains safe on repeated startup.


if __name__ == '__main__':
    unittest.main()
