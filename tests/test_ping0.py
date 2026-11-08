from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from catalog import PanelError, QueryBlocked
from ping0 import is_challenge_page, parse_ping0, query_ping0


IP = '192.0.2.1'
PROXY = 'http://127.0.0.1:12345'


def page(score='42%', label='轻微风险', ip=IP, before='', after=''):
    return (f'<script>window.ip = "{ip}"; window.tar = "{ip}";</script>'
            + before + '<div class="line line-risk"><div class="riskbar">'
            + '<div class="riskitem" title="0-15 极度纯净"></div>'
            + f'<div class="riskitem riskcurrent"><span class="value">{score}</span>'
            + f'<span class="lab"> {label}</span></div>'
            + '<div class="riskitem" title="70-100 极度风险"></div></div></div>' + after)


class Ping0ParserTests(unittest.TestCase):
    def test_reads_current_risk_and_accepts_real_zero(self):
        for score in ['0%', '42%', '100%', '42.5%']:
            with self.subTest(score=score):
                result = parse_ping0(page(score), IP)
                self.assertEqual(result['score'], float(score[:-1]))
                self.assertEqual(result['ip'], IP)
                self.assertEqual(result['label'], '轻微风险')

    def test_ignores_inactive_scale_values_and_other_value_elements(self):
        inactive = '<div class="riskitem"><span class="value">99%</span><span class="lab">极度风险</span></div>'
        result = parse_ping0(page(before=inactive + '<span class="value">100%</span>',
                                  after=inactive), IP)
        self.assertEqual(result['score'], 42)

    def test_nested_markup_and_whitespace_are_read_as_text(self):
        self.assertEqual(parse_ping0(page(' <b>42</b>% ', ' 轻微<br>风险 '), IP)['score'], 42)

    def test_rejects_other_ip_or_missing_query_ip(self):
        for html in [page(ip='192.0.2.2'), page().replace('window.ip', 'window.other'),
                     page() + '<script>window.ip="192.0.2.2"</script>']:
            with self.subTest(html=html), self.assertRaises(PanelError):
                parse_ping0(html, IP)

    def test_rejects_multiple_current_results_or_duplicate_values(self):
        extra = '<div class="riskcurrent riskitem"><span class="value">1%</span><span class="lab">纯净</span></div>'
        for html in [page(after=extra), page().replace('42%', '42%</span><span class="value">43%')]:
            with self.subTest(html=html), self.assertRaises(PanelError):
                parse_ping0(html, IP)

    def test_rejects_missing_or_invalid_numbers_instead_of_using_zero(self):
        for score in ['', '-', 'NaN%', 'Infinity%', '-1%', '101%', '100.01%', '42', '1e2%', '1,2%']:
            with self.subTest(score=score), self.assertRaises(PanelError):
                parse_ping0(page(score), IP)
        for html in [page().replace('riskcurrent', 'inactive'), page(label=''),
                     page().replace('class="value"', 'class="other"')]:
            with self.subTest(html=html), self.assertRaises(PanelError):
                parse_ping0(html, IP)

    def test_complete_valid_risk_wins_over_embedded_scripts_and_widgets(self):
        for extra in ['<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>',
                      '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>',
                      '<div class="cf-turnstile"></div>', '<title>CAPTCHA</title>']:
            with self.subTest(extra=extra):
                self.assertEqual(parse_ping0(page('0%', after=extra), IP)['score'], 0)

    def test_passive_scripts_and_ordinary_html_are_not_challenges(self):
        for html in ['<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>',
                     '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>',
                     '<div class="my-cf-turnstile-style">Loading...</div>',
                     '<title>Ping0</title><p>暂无数据</p>']:
            with self.subTest(html=html):
                self.assertFalse(is_challenge_page(html))
                with self.assertRaises(PanelError) as caught:
                    parse_ping0(html, IP)
                self.assertNotIsInstance(caught.exception, QueryBlocked)

    def test_rejects_ipv6_and_explicit_challenge_pages(self):
        with self.assertRaisesRegex(PanelError, 'IPv4'):
            parse_ping0(page(), '2001:db8::1')
        for html in ['<title>Just a moment...</title>', '<div class="cf-turnstile"></div>',
                     '<div class="captcha g-recaptcha"></div>', '<div class="h-captcha"></div>',
                     '<script>window._cf_chl_opt = {}</script>',
                     '<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>']:
            with self.subTest(html=html):
                with self.assertRaisesRegex(QueryBlocked, '人机验证') as caught:
                    parse_ping0(html, IP)
                self.assertEqual(caught.exception.kind, 'challenge')

    def test_query_blocked_keeps_existing_exception_calls_compatible(self):
        error = QueryBlocked('provider blocked')
        self.assertEqual(str(error), 'provider blocked')
        self.assertIsNone(error.kind)


class Ping0RequestTests(unittest.TestCase):
    def session(self, status=200, html=None):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value = Mock(status_code=status, text=page() if html is None else html)
        return session

    def test_uses_only_explicit_node_proxy_and_one_verified_https_get(self):
        session = self.session()
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://wrong.invalid:9000',
                                     'NO_PROXY': 'ping0.cc'}), patch('ping0.requests.Session', return_value=session):
            result = query_ping0(IP, PROXY)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['score'], 42)
        self.assertEqual(datetime.fromisoformat(result['checked_at']).utcoffset(), timedelta(hours=8))
        self.assertFalse(session.trust_env)
        session.get.assert_called_once_with(
            'https://ping0.cc/ip/192.0.2.1', proxies={'http': PROXY, 'https': PROXY},
            headers={'User-Agent': 'Clash-IP-Panel/0.2'}, timeout=(8, 15), allow_redirects=False)
        self.assertNotIn('verify', session.get.call_args.kwargs)

    def test_http_errors_are_isolated_and_classified_without_retry(self):
        for status, expected, kind in [(401, '拒绝', 'denied'), (403, '拒绝', 'denied'),
                                       (429, '限制', 'rate_limit'), (503, 'HTTP 503', None),
                                       (302, 'HTTP 302', None)]:
            session = self.session(status)
            with self.subTest(status=status), patch('ping0.requests.Session', return_value=session):
                result = query_ping0(IP, PROXY)
                self.assertEqual(result['status'], 'error')
                self.assertIn(expected, result['error'])
                self.assertNotIn('score', result)
                self.assertEqual(result.get('block_kind'), kind)
                self.assertEqual(result.get('service_blocked', False), kind is not None)
                session.get.assert_called_once()

    def test_403_explicit_challenge_is_distinct_and_429_always_rate_limit(self):
        for status, html, kind in [(403, '<title>Just a moment...</title>', 'challenge'),
                                  (403, '<h1>Access denied</h1>', 'denied'),
                                  (403, '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>', 'denied'),
                                  (429, '<title>人机验证</title>', 'rate_limit'),
                                  (401, '<title>人机验证</title>', 'denied')]:
            session = self.session(status, html)
            with self.subTest(status=status, html=html), patch('ping0.requests.Session', return_value=session):
                result = query_ping0(IP, PROXY)
                self.assertEqual(result['status'], 'error')
                self.assertTrue(result['service_blocked'])
                self.assertEqual(result['block_kind'], kind)
                self.assertNotIn('score', result)
                session.get.assert_called_once()

    def test_challenge_and_missing_data_return_provider_error(self):
        for html, expected in [('<title>人机验证</title>', '人机验证'),
                               ('<script>window.ip="192.0.2.1"</script>', '没有显示风险评分')]:
            session = self.session(html=html)
            with self.subTest(html=html), patch('ping0.requests.Session', return_value=session):
                result = query_ping0(IP, PROXY)
                self.assertEqual(result['status'], 'error')
                self.assertIn(expected, result['error'])
                self.assertEqual(result['ip'], IP)
                self.assertNotIn('score', result)
                if '人机验证' in expected:
                    self.assertTrue(result['service_blocked'])
                    self.assertEqual(result['block_kind'], 'challenge')
                else:
                    self.assertNotIn('service_blocked', result)
                    self.assertNotIn('block_kind', result)

    def test_timeout_and_network_failure_return_provider_error(self):
        for error, expected in [(requests.Timeout(), '超时'), (requests.ConnectionError(), '无法')]:
            session = self.session()
            session.get.side_effect = error
            with self.subTest(error=error), patch('ping0.requests.Session', return_value=session):
                result = query_ping0(IP, PROXY)
                self.assertEqual(result['status'], 'error')
                self.assertIn(expected, result['error'])
                session.get.assert_called_once()

    def test_invalid_ip_or_missing_local_proxy_never_starts_request(self):
        for ip, proxy in [('2001:db8::1', PROXY), ('not-an-ip', PROXY), (IP, ''),
                          (IP, 'http://remote.example:8080'), (IP, 'http://127.0.0.1:bad')]:
            with self.subTest(ip=ip, proxy=proxy), patch('ping0.requests.Session') as session:
                result = query_ping0(ip, proxy)
                self.assertEqual(result['status'], 'error')
                self.assertNotIn('score', result)
                session.assert_not_called()


if __name__ == '__main__':
    unittest.main()
