"""Read one explicit Ping0 IPv4 page using normal networking or a node proxy."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import ipaddress
import re
from urllib.parse import urlsplit

import requests

from catalog import PanelError, QueryBlocked


SHANGHAI = timezone(timedelta(hours=8))
USER_AGENT = 'Clash-IP-Panel/0.2'
VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}


def _ipv4(value):
    if not isinstance(value, str):
        raise PanelError('Ping0 检测需要有效的 IPv4 地址。')
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError:
        raise PanelError('Ping0 检测需要有效的 IPv4 地址。') from None


class _RiskParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.current = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        classes = set((dict(attrs).get('class') or '').split())
        record = self.stack[-1][1] if self.stack else None
        if {'riskitem', 'riskcurrent'} <= classes:
            record = {'values': [], 'labels': []}
            self.current.append(record)
        captures = []
        if record is not None:
            for class_name, key in [('value', 'values'), ('lab', 'labels')]:
                if class_name in classes:
                    text = []
                    record[key].append(text)
                    captures.append(text)
        if tag not in VOID_TAGS:
            self.stack.append((tag, record, captures))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data):
        for tag, _, captures in self.stack:
            for text in captures:
                text.append(data)
            if tag == 'script':
                self.scripts.append(data)


def is_challenge_page(html):
    """Recognize an actual challenge, not Cloudflare's passive JSD script."""
    lower = html.lower()
    widget_classes = {'cf-turnstile', 'g-recaptcha', 'h-captcha'}
    has_widget = any(widget_classes.intersection(value.split()) for _, value in
                     re.findall(r'\bclass\s*=\s*([\"\x27])(.*?)\1', lower, re.DOTALL))
    return bool(
        re.search(r'<title\b[^>]*>[^<]*(?:captcha|just a moment|人机验证)', lower)
        or has_widget
        or re.search(r'\bwindow\s*\.\s*_cf_chl_opt\s*=', lower)
        or re.search(r'/cdn-cgi/challenge-platform/[^\"\x27\s<>]*/orchestrate/chl_page/', lower))


def _parse_risk(html, expected_ip):
    parser = _RiskParser()
    parser.feed(html)
    parser.close()
    assigned_ips = re.findall(r'\bwindow\s*\.\s*ip\s*=\s*([\"\x27])([^\"\x27]+)\1',
                              '\n'.join(parser.scripts))
    if len(assigned_ips) != 1:
        raise PanelError('Ping0 页面缺少明确的查询 IP，本次结果未保存为成功。')
    if assigned_ips[0][1] != expected_ip:
        raise PanelError('Ping0 返回的 IP 与本次线路出口不一致，本次结果未保存为成功。')
    if not parser.current:
        raise PanelError('Ping0 没有显示风险评分，请稍后重试。')
    if len(parser.current) != 1:
        raise PanelError('网页显示了多个评分，无法确认结果，暂未保存。')
    risk = parser.current[0]
    if len(risk['values']) != 1 or len(risk['labels']) != 1:
        raise PanelError('Ping0 页面风险数据不完整，无法确认本次结果。')
    raw_score = ''.join(risk['values'][0]).strip()
    label = ' '.join(''.join(risk['labels'][0]).split())
    number = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*%', raw_score)
    if number is None:
        raise PanelError('Ping0 页面风险值格式无效，本次结果未保存为成功。')
    score = float(number[1])
    if not 0 <= score <= 100:
        raise PanelError('Ping0 页面风险值超出 0–100 范围，本次结果未保存为成功。')
    if not label:
        raise PanelError('Ping0 页面风险说明缺失，本次结果未保存为成功。')
    return {'ip': expected_ip, 'score': int(score) if score.is_integer() else score,
            'label': label}


def parse_ping0(html, expected_ip):
    """Prefer a complete risk result; only then classify missing-data challenges."""
    expected_ip = _ipv4(expected_ip)
    try:
        return _parse_risk(html, expected_ip)
    except PanelError:
        if is_challenge_page(html):
            raise QueryBlocked('Ping0 要求人机验证，请到网站手动查看；本次未获取风险值。',
                               kind='challenge') from None
        raise


def query_ping0(ip, proxy_url):
    """One HTTPS request; provider failure stays separate from IPPure."""
    return _query_ping0(ip, proxy_url)


def query_ping0_auto(ip):
    """One normal request for a known IP; preserve system/environment routing."""
    return _query_ping0(ip, auto=True)


def _query_ping0(ip, proxy_url=None, *, auto=False):
    record = {'status': 'error', 'ip': str(ip),
              'checked_at': datetime.now(SHANGHAI).isoformat(timespec='milliseconds')}
    try:
        ip = _ipv4(ip)
        record['ip'] = ip
        options = {'timeout': (8, 15), 'allow_redirects': False}
        if not auto:
            try:
                proxy = urlsplit(proxy_url)
                valid_proxy = (proxy.scheme == 'http' and proxy.hostname in ('127.0.0.1', 'localhost', '::1')
                               and proxy.port is not None)
            except (TypeError, ValueError):
                valid_proxy = False
            if not valid_proxy:
                raise PanelError('Ping0 检测代理地址无效，未发起查询。')
            options.update(proxies={'http': proxy_url, 'https': proxy_url},
                           headers={'User-Agent': USER_AGENT})
        with requests.Session() as session:
            session.trust_env = auto
            response = session.get(f'https://ping0.cc/ip/{ip}', **options)
            if response.status_code == 429:
                raise QueryBlocked('Ping0 暂时限制了查询频率（HTTP 429），请稍后手动重试。',
                                   kind='rate_limit')
            if response.status_code == 403 and is_challenge_page(response.text):
                raise QueryBlocked('Ping0 需要验证（HTTP 403），本次未取得评分。',
                                   kind='challenge')
            if response.status_code in (401, 403):
                raise QueryBlocked(f'Ping0 拒绝了本次网页查询（HTTP {response.status_code}），请到网站手动查看。',
                                   kind='denied')
            if response.status_code != 200:
                raise PanelError(f'Ping0 网页查询失败（HTTP {response.status_code}）。')
            record.update(parse_ping0(response.text, ip))
            record['status'] = 'ok'
    except QueryBlocked as error:
        record.update(error=str(error), service_blocked=True, block_kind=error.kind)
    except PanelError as error:
        record['error'] = str(error)
    except requests.Timeout:
        record['error'] = ('连接 Ping0 超时，请稍后手动重试。' if auto
                           else '通过所选线路连接 Ping0 超时，请稍后手动重试。')
    except requests.RequestException:
        record['error'] = ('无法连接 Ping0，请稍后手动重试。' if auto
                           else '无法通过所选线路连接 Ping0，请稍后手动重试。')
    return record
