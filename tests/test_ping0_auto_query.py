"""One ordinary Ping0 request, with all HTTP traffic mocked."""
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ping0 import query_ping0_auto


IP = '192.0.2.1'
URL = f'https://ping0.cc/ip/{IP}'


def page(score='0%', ip=IP):
    return (f'<script>window.ip="{ip}";</script>'
            '<div class="riskitem riskcurrent">'
            f'<span class="value">{score}</span><span class="lab">极度纯净</span></div>')


class Ping0AutoQueryTests(unittest.TestCase):
    def session(self, status=200, html=None):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value = Mock(status_code=status, text=page() if html is None else html)
        return session

    def test_one_explicit_ipv4_https_request_keeps_normal_network_settings(self):
        session = self.session()
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://normal.invalid:9000'}), \
                patch('ping0.requests.Session', return_value=session):
            before = dict(os.environ)
            result = query_ping0_auto(IP)
            self.assertEqual(dict(os.environ), before)
        self.assertTrue(session.trust_env)
        session.get.assert_called_once_with(URL, timeout=(8, 15), allow_redirects=False)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['ip'], IP)
        self.assertEqual(result['score'], 0)
        self.assertEqual(result['label'], '极度纯净')
        self.assertEqual(datetime.fromisoformat(result['checked_at']).utcoffset(), timedelta(hours=8))
        self.assertNotIn('service_blocked', result)

    def test_requests_resolves_existing_environment_proxy_without_real_send(self):
        proxy = 'http://normal.invalid:9000'
        response = Mock(status_code=200, text=page())
        with patch.dict(os.environ, {'HTTPS_PROXY': proxy, 'https_proxy': proxy,
                                     'NO_PROXY': '', 'no_proxy': ''}), \
                patch('requests.sessions.Session.send', return_value=response) as send:
            before = dict(os.environ)
            result = query_ping0_auto(IP)
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(result['status'], 'ok')
        send.assert_called_once()
        prepared = send.call_args.args[0]
        self.assertEqual(prepared.url, URL)
        self.assertEqual(send.call_args.kwargs['proxies']['https'], proxy)
        self.assertTrue(send.call_args.kwargs['verify'])
        self.assertEqual(prepared.headers['User-Agent'], requests.utils.default_user_agent())
        self.assertNotIn('Cookie', prepared.headers)

    def test_challenge_rate_limit_and_denied_are_distinct_and_never_retried(self):
        for status, html, kind in [(200, '<title>Just a moment...</title>', 'challenge'),
                                  (403, '<title>人机验证</title>', 'challenge'),
                                  (403, '<h1>Access denied</h1>', 'denied'),
                                  (401, '<title>人机验证</title>', 'denied'),
                                  (429, '<title>人机验证</title>', 'rate_limit')]:
            session = self.session(status, html)
            with self.subTest(status=status, kind=kind), patch('ping0.requests.Session', return_value=session):
                result = query_ping0_auto(IP)
            self.assertEqual(result['status'], 'error')
            self.assertTrue(result['service_blocked'])
            self.assertEqual(result['block_kind'], kind)
            self.assertNotIn('score', result)
            session.get.assert_called_once()

    def test_valid_risk_with_passive_cloudflare_script_is_saved_as_success(self):
        session = self.session(html=page('12%') +
                               '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>')
        with patch('ping0.requests.Session', return_value=session):
            result = query_ping0_auto(IP)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['score'], 12)

    def test_malformed_missing_or_wrong_ip_pages_are_errors_not_zero_scores_or_challenges(self):
        for html in [page(''), page('NaN%'), page(ip='192.0.2.2'), '<html>Unavailable</html>',
                     '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>']:
            session = self.session(html=html)
            with self.subTest(html=html), patch('ping0.requests.Session', return_value=session):
                result = query_ping0_auto(IP)
            self.assertEqual(result['status'], 'error')
            self.assertNotIn('score', result)
            self.assertNotIn('service_blocked', result)
            session.get.assert_called_once()

    def test_redirects_and_server_errors_are_not_followed_or_retried(self):
        for status in [302, 503]:
            session = self.session(status)
            with self.subTest(status=status), patch('ping0.requests.Session', return_value=session):
                result = query_ping0_auto(IP)
            self.assertIn(f'HTTP {status}', result['error'])
            self.assertNotIn('service_blocked', result)
            session.get.assert_called_once()

    def test_network_failures_do_not_claim_the_selected_node_was_used(self):
        for error, expected in [(requests.Timeout(), '超时'), (requests.ConnectionError(), '无法')]:
            session = self.session()
            session.get.side_effect = error
            with self.subTest(error=error), patch('ping0.requests.Session', return_value=session):
                result = query_ping0_auto(IP)
            self.assertEqual(result['status'], 'error')
            self.assertIn(expected, result['error'])
            self.assertNotIn('所选线路', result['error'])
            self.assertNotIn('service_blocked', result)
            session.get.assert_called_once()

    def test_invalid_or_non_ipv4_targets_never_open_a_session(self):
        for ip in [None, '2001:db8::1', 'https://other.invalid/', '192.0.2.1/path']:
            with self.subTest(ip=ip), patch('ping0.requests.Session') as session:
                result = query_ping0_auto(ip)
            self.assertEqual(result['status'], 'error')
            self.assertNotIn('score', result)
            session.assert_not_called()


if __name__ == '__main__':
    unittest.main()
