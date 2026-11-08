import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from recommendations import rank_nodes, assess_node, normalize_options
from service import Service, is_due, DEFAULTS
from detector import Detector
from catalog import PanelError

NOW = datetime.now(timezone.utc)


def success(hours=1, score=10, ip='203.0.113.1'):
    return {'status': 'ok', 'checked_at': (NOW-timedelta(hours=hours)).isoformat(),
            'route_verified': True, 'score': score, 'ip': ip, 'fingerprint': 'original'}


def node(key='a', record=None, attempt=None):
    record = record or success()
    return {'id': key, 'name': '美国 '+key, 'latest': record,
            'last_attempt': attempt or record, 'unsupported': None}


def failure(connection='ok', observed=None):
    return {'status': 'error', 'checked_at': NOW.isoformat(), 'error': 'rating unavailable',
            'connectivity': {'status': connection}, 'observed_ip': observed}


class ReviewPolicyTests(unittest.TestCase):
    def test_old_result_remains_visible_without_fresh_recommendation(self):
        result = rank_nodes([node(record=success(1000))], {}, now=NOW)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['state'], 'review')
        self.assertTrue(result['items'][0]['needs_review'])

    def test_recent_confirmed_result_before_old_lower_risk(self):
        result = rank_nodes([node('old', success(200, 1)), node('new', success(1, 20))], {}, now=NOW)
        self.assertEqual([r['id'] for r in result['items']], ['new', 'old'])

    def test_query_failure_keeps_score_and_original_timestamp(self):
        old = success(4)
        result = rank_nodes([node(record=old, attempt=failure())], {}, now=NOW)['items'][0]
        self.assertEqual(result['state'], 'score_pending')
        self.assertTrue(result['needs_review'])
        self.assertEqual(result['checked_at'], old['checked_at'])
        self.assertEqual(result['scores']['ippure'], 10)

    def test_connection_failure_and_unknown_connection_not_recommended(self):
        for status in ('timeout', 'error', None):
            with self.subTest(status=status):
                self.assertFalse(rank_nodes([node(attempt=failure(status))], {}, now=NOW)['items'])

    def test_changed_ip_does_not_inherit_old_score(self):
        n = node(attempt=failure(observed='203.0.113.2'))
        self.assertEqual(assess_node(n, NOW)['state'], 'ip_changed')
        self.assertFalse(rank_nodes([n], {}, now=NOW)['items'])
        n['last_attempt'] = failure()
        n['observed_ip'] = '203.0.113.2'
        self.assertFalse(rank_nodes([n], {}, now=NOW)['items'])

    def test_unrated_and_changed_config_not_recommended(self):
        n = node(attempt=failure())
        n['latest'] = None
        self.assertFalse(rank_nodes([n], {}, now=NOW)['items'])
        n = node()
        n['config_changed'] = True
        self.assertFalse(rank_nodes([n], {}, now=NOW)['items'])

    def test_expansion_returns_all_eligible_and_keeps_filters(self):
        nodes = [node(str(i), success(score=i)) for i in range(12)]
        self.assertEqual(len(rank_nodes(nodes, {}, now=NOW)['items']), 12)
        self.assertEqual(len(rank_nodes(nodes, {}, now=NOW, options={'max_risk': 5})['items']), 6)
        self.assertFalse(rank_nodes(nodes, {}, now=NOW, options={'regions': ['JP']})['items'])

    def test_legacy_options_retired_and_settings_preserved_on_restart(self):
        old = {'paused': True, 'update_hours': 6, 'candidate_hours': 6, 'other_hours': 48,
               'recommendation': {'fresh_hours': 168, 'limit': 3, 'max_risk': 20, 'regions': ['US']}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path/'settings.json').write_text(json.dumps(old), encoding='utf-8')
            service = Service(path, Path('unused.exe'), roots=[], start=False)
            expected = {'paused': True, 'recommendation': {'max_risk': 20, 'regions': ['US']}}
            self.assertEqual(service.settings, expected)
            service.save_settings({'recommendation': {'max_risk': 20, 'regions': ['US']}})
            self.assertEqual(json.loads((path/'settings.json').read_text()), expected)

    def test_daily_schedule_and_configuration_change(self):
        n = {'id': 'a', 'fingerprint': 'original'}
        for candidates in (set(), {'a'}):
            self.assertFalse(is_due(n, success(12), NOW.timestamp(), candidates, DEFAULTS))
            self.assertTrue(is_due(n, success(24), NOW.timestamp(), candidates, DEFAULTS))
        self.assertTrue(is_due(dict(n, fingerprint='new'), success(), NOW.timestamp(), set(), DEFAULTS))

    def test_response_ip_survives_missing_rating(self):
        with tempfile.TemporaryDirectory() as tmp:
            detector = Detector(Path('unused.exe'), Path(tmp))
            dns = MagicMock()
            dns.ok = True
            dns.json.return_value = {'Answer': [{'type': 1, 'data': '203.0.113.4'}]}
            with patch('detector.requests.Session') as session, patch('detector.subprocess.run') as run:
                session.return_value.__enter__.return_value.get.return_value = dns
                run.return_value = SimpleNamespace(returncode=0, stdout=b'{"ip":"203.0.113.2"}\n200')
                with self.assertRaisesRegex(PanelError, '没有返回风险值'):
                    detector._request(12345, Path(tmp))
                self.assertEqual(detector.progress['observed_ip'], '203.0.113.2')


if __name__ == '__main__':
    unittest.main()
