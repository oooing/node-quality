"""Browser Ping0 supplements stay separate from IPPure attempts and ranking."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from recommendations import rank_nodes
from store import Store


IP = '192.0.2.1'
NEXT_IP = '192.0.2.2'
BASED_ON = '2026-10-29T11:00:00+08:00'
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone(timedelta(hours=8)))


def ippure(ip=IP, when=BASED_ON, score=20):
    return {'status': 'ok', 'ip': ip, 'score': score, 'checked_at': when,
            'route_verified': True, 'country': 'US', 'elapsed_seconds': 1.25}


def ping0(ip=IP, score=0, when='2026-10-29T11:05:00+08:00'):
    return {'ip': ip, 'score': score, 'label': '极度纯净', 'checked_at': when,
            'source': 'browser_page', 'source_url': f'https://ping0.cc/ip/{ip}'}


class Ping0StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name) / 'history.sqlite3')
        self.node = {'id': 'profile-one-node', 'name': 'Test node', 'unsupported': None}
        self.store.add(self.node, ippure())

    def tearDown(self):
        self.temporary.cleanup()

    def add(self, result=None, job='job-1', based_on=BASED_ON):
        result = ping0() if result is None else result
        return self.store.add_ping0(self.node['id'], result['ip'], based_on, result, job)

    def recommendations(self):
        latest, attempts, counts = self.store.snapshot()
        node = dict(self.node, latest=latest[self.node['id']],
                    last_attempt=attempts[self.node['id']], history_count=counts[self.node['id']])
        return rank_nodes([node], self.store.histories([self.node['id']]), now=NOW)

    def test_zero_score_and_source_are_saved_without_changing_ippure_or_recommendations(self):
        before = self.store.snapshot()
        history = self.store.history(self.node['id'])
        recommendations = self.recommendations()
        result = ping0()
        original = deepcopy(result)
        saved = self.add(result)
        after = self.store.snapshot()
        self.assertTrue(saved['applied_to_current'])
        self.assertEqual(saved['record']['score'], 0)
        self.assertEqual(saved['record']['source'], 'browser_page')
        self.assertEqual(saved['record']['source_url'], 'https://ping0.cc/ip/192.0.2.1')
        self.assertEqual(saved['record']['based_on_checked_at'], BASED_ON)
        self.assertEqual(saved['record']['checked_at'], result['checked_at'])
        latest = after[0][self.node['id']]
        expected = dict(before[0][self.node['id']], ping0_latest=saved['record'])
        self.assertEqual(latest, expected)
        self.assertEqual(after[1:], before[1:])
        self.assertEqual(self.store.history(self.node['id']), history)
        self.assertEqual(self.recommendations(), recommendations)
        self.assertEqual(result, original)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT checked_at FROM latest WHERE node_id=?',
                                        (self.node['id'],)).fetchone()[0], BASED_ON)

    def test_supplement_cannot_hide_a_newer_failed_ippure_attempt(self):
        self.store.add(self.node, {'status': 'error', 'checked_at': '2026-10-29T11:02:00+08:00',
                                   'error': 'timeout'})
        attempts = self.store.snapshot()[1]
        self.add()
        self.assertEqual(self.store.snapshot()[1], attempts)
        self.assertEqual(self.recommendations()['items'], [])
        self.assertEqual(self.recommendations()['counts']['failed'], 1)

    def test_old_ip_supplement_is_history_only_after_current_ip_changes(self):
        self.store.add(self.node, ippure(NEXT_IP, '2026-10-29T11:03:00+08:00', 15))
        current = self.add(ping0(NEXT_IP, 12), job='new-ip', based_on='2026-10-29T11:03:00+08:00')
        before = self.store.snapshot()
        old = self.add(ping0(IP, 0, '2026-10-29T11:06:00+08:00'), job='old-ip')
        self.assertFalse(old['applied_to_current'])
        self.assertEqual(self.store.snapshot(), before)
        self.assertEqual(self.store.snapshot()[0][self.node['id']]['ping0_latest'], current['record'])
        self.assertEqual([row['ip'] for row in self.store.ping0_history(self.node['id'])], [IP, NEXT_IP])

    def test_same_ip_newer_ippure_attempt_keeps_its_time_and_accepts_supplement(self):
        newer = '2026-10-29T11:03:00+08:00'
        self.store.add(self.node, ippure(when=newer, score=10))
        saved = self.add()
        self.assertTrue(saved['applied_to_current'])
        latest = self.store.snapshot()[0][self.node['id']]
        self.assertEqual(latest['checked_at'], newer)
        self.assertEqual(latest['score'], 10)
        self.assertEqual(latest['ping0_latest']['based_on_checked_at'], BASED_ON)

    def test_older_ping0_capture_does_not_replace_newer_current_value(self):
        newer = self.add(ping0(score=20, when='2026-10-29T11:06:00+08:00'), job='new')
        older = self.add(ping0(score=0), job='old')
        self.assertFalse(older['applied_to_current'])
        self.assertEqual(self.store.snapshot()[0][self.node['id']]['ping0_latest'], newer['record'])
        self.assertEqual([row['job_id'] for row in self.store.ping0_history(self.node['id'])], ['new', 'old'])

    def test_same_job_repeated_notification_returns_original_once(self):
        first = self.add()
        repeated = self.add(ping0(score=99, when='2026-10-29T11:09:00+08:00'))
        self.assertEqual(repeated, first)
        self.assertEqual(self.store.ping0_history(self.node['id']), [first['record']])
        self.assertEqual(self.store.snapshot()[0][self.node['id']]['ping0_latest'], first['record'])

    def test_independent_ten_record_retention_and_other_nodes_survive_reopen(self):
        other = {'id': 'profile-two-node', 'name': 'Other node'}
        self.store.add(other, ippure())
        self.store.add_ping0(other['id'], IP, BASED_ON, ping0(score=7), 'other-job')
        for index in range(13):
            self.add(ping0(score=index, when=f'2026-10-29T11:05:{index:02d}+08:00'), job=f'job-{index}')
        reopened = Store(self.store.path)
        self.assertEqual([row['score'] for row in reopened.ping0_history(self.node['id'])], list(range(12, 2, -1)))
        self.assertEqual(len(reopened.history(self.node['id'])), 1)
        self.assertEqual(len(reopened.ping0_history(other['id'])), 1)
        self.assertEqual(reopened.snapshot()[0][self.node['id']]['ping0_latest']['score'], 12)
        original = reopened.ping0_history(self.node['id'])[0]
        repeated = reopened.add_ping0(self.node['id'], IP, BASED_ON, ping0(score=99), 'job-12')
        self.assertEqual(repeated, {'record': original, 'applied_to_current': True})
        self.assertEqual(len(reopened.ping0_history(self.node['id'])), 10)

    def test_new_ippure_check_preserves_supplement_without_refreshing_its_time(self):
        saved = self.add()
        self.store.add(self.node, ippure(when='2026-10-29T11:10:00+08:00', score=11))
        latest = self.store.snapshot()[0][self.node['id']]
        self.assertEqual(latest['ping0_latest'], saved['record'])
        self.assertEqual(latest['checked_at'], '2026-10-29T11:10:00+08:00')
        self.assertEqual(latest['score'], 11)
        self.assertEqual(len(self.store.history(self.node['id'])), 2)

    def test_missing_current_result_saves_only_supplement_history(self):
        saved = self.store.add_ping0('removed-node', IP, BASED_ON, ping0(), 'missing-node-job')
        self.assertFalse(saved['applied_to_current'])
        self.assertNotIn('removed-node', self.store.snapshot()[0])
        self.assertEqual(self.store.history('removed-node'), [])
        self.assertEqual(self.store.ping0_history('removed-node'), [saved['record']])

    def test_wrong_target_ip_cannot_be_saved_under_requested_ip(self):
        with self.assertRaises(ValueError):
            self.store.add_ping0(self.node['id'], NEXT_IP, BASED_ON, ping0(), 'wrong-target')
        self.assertEqual(self.store.ping0_history(self.node['id']), [])
        self.assertIsNone(self.store.snapshot()[0][self.node['id']]['ping0_latest'])


if __name__ == '__main__':
    unittest.main()
