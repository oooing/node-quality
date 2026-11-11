"""Pacing and DNS reuse must never reuse scores or change detection routes."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from detector import Detector
from catalog import QueryBlocked, PanelError


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.detector = Detector('unused.exe', self.temp.name)
        self.detector.interface, self.detector.interface_index = 'Ethernet', 7

    def tearDown(self):
        self.temp.cleanup()

    def dns(self, address='203.0.113.1', ttl=60):
        return SimpleNamespace(ok=True, json=lambda: {'Answer': [
            {'type': 5, 'TTL': 30}, {'type': 1, 'TTL': ttl, 'data': address}]})

    def score(self, ip='198.51.100.1'):
        return SimpleNamespace(returncode=0, stdout=(json.dumps({'ip': ip, 'fraudScore': 12})+'\n200').encode())

    def test_cache_respects_cname_ttl_and_physical_adapter(self):
        d = self.detector
        with patch('detector.requests.Session') as session, patch('detector.time.monotonic', return_value=100) as clock:
            get = session.return_value.__enter__.return_value.get
            get.return_value = self.dns()
            self.assertEqual(d._resolve_address(111)[1], False)
            clock.return_value = 129
            self.assertEqual(d._resolve_address(222)[1], True)
            get.assert_called_once()
            clock.return_value = 130
            self.assertFalse(d._resolve_address(222)[1])
            d.interface_index = 8
            self.assertFalse(d._resolve_address(222)[1])
            self.assertEqual(get.call_count, 3)

    def test_cached_dns_still_queries_each_lines_exit_and_new_score(self):
        d = self.detector
        with patch('detector.requests.Session') as session, patch.object(d, '_fetch_score') as fetch:
            get = session.return_value.__enter__.return_value.get
            get.return_value = self.dns()
            fetch.side_effect = [self.score(), self.score('198.51.100.2')]
            a, b = d._request(111, None), d._request(222, None)
            self.assertNotEqual(a['ip'], b['ip'])
            self.assertEqual([c.args[0] for c in fetch.call_args_list], [111, 222])
            self.assertEqual(get.call_count, 1)

    def test_cached_connection_failure_refreshes_address_once(self):
        d = self.detector
        with patch.object(d, '_resolve_address', side_effect=[('203.0.113.1', True), ('203.0.113.2', False)]) as resolve, \
                patch.object(d, '_fetch_score', side_effect=[SimpleNamespace(returncode=28), self.score()]) as fetch:
            result = d._request(123, None)
            self.assertEqual(result['destination_ipv4'], '203.0.113.2')
            resolve.assert_called_with(123, force=True)
            self.assertEqual(fetch.call_count, 2)

    def test_same_refreshed_address_does_not_repeat_slow_request(self):
        d = self.detector
        with patch.object(d, '_resolve_address', side_effect=[('203.0.113.1', True), ('203.0.113.1', False)]), \
                patch.object(d, '_fetch_score', return_value=SimpleNamespace(returncode=28)) as fetch:
            with self.assertRaises(PanelError):
                d._request(123, None)
            fetch.assert_called_once()

    def test_rate_limit_does_not_retry_or_bypass_challenge(self):
        d = self.detector
        with patch.object(d, '_resolve_address', return_value=('203.0.113.1', True)) as resolve, \
                patch.object(d, '_fetch_score', return_value=SimpleNamespace(returncode=0, stdout=b'{}\n429')) as fetch:
            with self.assertRaises(QueryBlocked):
                d._request(123, None)
            resolve.assert_called_once()
            fetch.assert_called_once()

    def test_pacing_counts_preparation_time_and_keeps_isolated_proxy(self):
        d = self.detector
        now = [100.]
        def sleep(seconds):
            now[0] += seconds
        with patch('detector.time.monotonic', side_effect=lambda: now[0]), \
                patch('detector.time.sleep', side_effect=sleep) as wait, \
                patch('detector.subprocess.run', return_value=self.score()) as run:
            d._fetch_score(123, '203.0.113.1')
            wait.assert_not_called()
            now[0] += 2
            d._fetch_score(456, '203.0.113.1')
            wait.assert_called_once_with(1)
            self.assertIn('socks5://127.0.0.1:456', run.call_args.args[0])
            now[0] += 10
            d._fetch_score(789, '203.0.113.1')
            self.assertEqual(wait.call_count, 1)


if __name__ == '__main__':
    unittest.main()
