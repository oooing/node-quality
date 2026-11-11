"""One IPPure check, using a temporary isolated copy of the installed Mihomo core."""
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone

import requests
import yaml

from catalog import PanelError, QueryBlocked
from connectivity import check_connectivity
from diagnostics import DiagnosedError, FailureDiagnostics, diagnosis

ENDPOINT = 'https://my.ippure.com/v1/info'
SHANGHAI = timezone(timedelta(hours=8))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def parse_result(data):
    if not isinstance(data, dict):
        raise PanelError('IPPure 返回了无法识别的数据，请稍后重试。')
    try:
        address = ipaddress.ip_address(data.get('ip', ''))
    except ValueError:
        raise PanelError('IPPure 没有返回有效的出口 IP。') from None
    if address.version != 4:
        raise PanelError('本次获得 IPv6 地址，IPPure 不提供此类地址的评分。')
    score = data.get('fraudScore')
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
        raise PanelError('IPPure 本次没有返回风险值，请稍后重试。')
    return {'ip': str(address), 'score': score, 'country': data.get('country'),
            'city': data.get('city'), 'asn': data.get('asn'),
            'is_residential': data.get('isResidential'), 'is_broadcast': data.get('isBroadcast')}


def free_ports():
    with socket.socket() as first, socket.socket() as second:
        first.bind(('127.0.0.1', 0))
        second.bind(('127.0.0.1', 0))
        return first.getsockname()[1], second.getsockname()[1]


class Detector:
    def __init__(self, core, runtime, verification=None, diagnostics=None):
        self.core = Path(core)
        self.runtime = Path(runtime).resolve()
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.verification = verification
        self.diagnostics = diagnostics if diagnostics is not None else FailureDiagnostics()
        self.progress = None
        self.interface = None
        self.interface_index = None
        self._dns_cache = None
        self._last_risk_started = None
        self._phase = None
        self._phase_started = None
        self._timings = {}

    def stage(self, name, **details):
        now = time.monotonic()
        if self._phase_started is not None:
            self._timings[self._phase] = self._timings.get(self._phase, 0) + now - self._phase_started
        self._phase, self._phase_started = name, now
        self.progress = dict(self.progress or {}, stage=name, **details)

    def check(self, node, manual=False, latency_only=False):
        # Keep the former manual argument compatible; checks now use IPPure only.
        started = time.monotonic()
        self._timings = {}
        self._phase, self._phase_started = 'starting', started
        record = {'checked_at': datetime.now(SHANGHAI).isoformat(timespec='milliseconds'), 'status': 'error'}
        self.progress = {'node_id': node.get('id'), 'stage': 'starting'}
        try:
            if node['unsupported']:
                raise DiagnosedError('config', 'unsupported', node['unsupported'])
            if not self.core.is_file():
                raise DiagnosedError('local', 'engine_missing', '检测引擎缺失',
                                     '尚未连接线路。', suggestion='请重新安装云鉴。')
            record.update(self._run(node, latency_only=latency_only))
            record['status'] = 'ok'
        except QueryBlocked as error:
            record.update(error=str(error), service_blocked=True, block_kind=error.kind or 'denied')
            record['diagnosis'] = diagnosis('site', error.kind or 'denied', str(error),
                '评分网站未允许本次查询，不能据此判断线路不可用。', suggestion='稍后重试；需要验证时按网站提示操作。')
        except DiagnosedError as error:
            record.update(error=str(error), diagnosis=error.diagnosis)
        except PanelError as error:
            record['error'] = str(error)
        except requests.Timeout:
            record['error'] = '连接这条线路超时，请稍后重试。'
        except requests.RequestException:
            record['error'] = '这条线路暂时连不上检测网站，请稍后重试。'
        except (ValueError, KeyError):
            record['error'] = '检测服务返回了不完整的数据，请稍后重试。'
        except (OSError, subprocess.SubprocessError):
            detail = diagnosis('local', 'process_failed', '检测程序无法完成本次操作',
                '本机文件、权限或进程调用发生错误，不能据此判断线路不可用。',
                suggestion='重试检测；持续出现时重新安装云鉴。')
            record.update(error=detail['message'], diagnosis=detail)
        if record['status'] != 'ok' and 'diagnosis' not in record:
            connection = (self.progress or {}).get('connectivity', {})
            category = 'site' if connection.get('status') == 'ok' else 'local'
            record['diagnosis'] = diagnosis(category, 'request_failed' if category == 'site' else 'check_failed',
                record['error'], '线路连通测试通过，评分步骤未完成。' if category == 'site'
                else '检测程序未能完成本次操作，不能据此判断线路不可用。')
            record['error'] = record['diagnosis']['message']
        if self.progress and self.progress.get('observed_ip'):
            record['observed_ip'] = self.progress['observed_ip']
        if self.progress and self.progress.get('connectivity'):
            record['connectivity'] = self.progress['connectivity']
            if record['status'] != 'ok' and record['connectivity']['status'] == 'ok' and not record.get('diagnosis'):
                record['error'] = '连接测试通过；' + record.get('error', '未取得风险评分')
        self.stage('done')
        record['timings'] = {k: round(v, 3) for k, v in self._timings.items()}
        record['dns_cache_hit'] = bool((self.progress or {}).get('dns_cache_hit'))
        self.progress = None
        self._phase_started = None
        record['elapsed_seconds'] = round(time.monotonic() - started, 3)
        return record

    def _run(self, node, manual=False, latency_only=False):
        proxy_port, api_port = free_ports()
        token = secrets.token_urlsafe(24)
        with tempfile.TemporaryDirectory(prefix='check-', dir=self.runtime) as temporary:
            directory = Path(temporary).resolve()
            # Windows AppData redirection may give the same parent two path spellings.
            # Compare directory identity while keeping checks inside our own runtime.
            if not directory.parent.samefile(self.runtime):
                raise DiagnosedError('local', 'runtime_directory', '检测目录校验失败', '尚未连接线路。')
            configuration = {
                'mode': 'rule', 'log-level': 'info', 'allow-lan': False, 'ipv6': False,
                'external-controller': f'127.0.0.1:{api_port}', 'secret': token,
                'tun': {'enable': False}, 'dns': {'enable': False},
                'profile': {'store-selected': False, 'store-fake-ip': False},
                'proxies': [node['config']],
                'listeners': [{'name': 'ip-panel-check', 'type': 'mixed', 'listen': '127.0.0.1',
                               'port': proxy_port, 'proxy': node['name']}],
                'rules': ['MATCH,REJECT'],
            }
            if not self.interface:
                raise DiagnosedError('local', 'no_interface', '未找到可用的物理网卡', '尚未连接线路。')
            configuration['interface-name'] = self.interface
            # Subscription options cannot redirect the isolated engine into another tunnel.
            configuration['proxies'] = [dict(node['config'], **{'interface-name': self.interface})]
            configuration['proxies'][0].pop('routing-mark', None)
            config_path = directory / 'config.yaml'
            config_path.write_text(yaml.safe_dump(configuration, allow_unicode=True), encoding='utf-8')
            process = None
            result = None
            log_path = directory / 'core.log'
            with log_path.open('w', encoding='utf-8') as log, requests.Session() as control:
                control.trust_env = False
                control.headers['Authorization'] = f'Bearer {token}'
                try:
                    process = subprocess.Popen([str(self.core), '-d', str(directory), '-f', str(config_path)],
                                               cwd=directory, stdout=log, stderr=subprocess.STDOUT,
                                               creationflags=NO_WINDOW)
                    ready = False
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise DiagnosedError('local', 'engine_start', '检测引擎启动失败',
                                '引擎在就绪前退出，尚未测试线路。', suggestion='可更新线路或重新安装云鉴后重试。')
                        try:
                            response = control.get(f'http://127.0.0.1:{api_port}/version', timeout=.4)
                            if response.ok:
                                ready = True
                                break
                        except requests.RequestException:
                            pass
                        time.sleep(.15)
                    if not ready:
                        raise DiagnosedError('local', 'engine_timeout', '检测引擎启动超时', '尚未测试线路。')
                    connection = {}
                    try:
                        connection = check_connectivity(control, api_port, node['name'],
                            on_attempt=lambda index: self.stage('connectivity' if index == 1 else 'connectivity_retry'))
                        self.stage('connectivity', connectivity=connection)
                        if connection['status'] != 'ok':
                            raise PanelError('两个测试网站都连接超时，本次未查询 IP。' if connection['status'] == 'timeout'
                                             else '两个测试网站都未连接成功，本次未查询 IP。')
                        if latency_only:
                            return {'connectivity': connection}
                        result = self._request(proxy_port, directory)
                    except QueryBlocked:
                        raise
                    except (requests.RequestException, PanelError) as error:
                        if connection.get('status') == 'ok':
                            raise DiagnosedError('site', 'score_request', str(error),
                                '线路连通测试通过，连接评分服务或读取评分时失败。',
                                ['线路连通测试通过'], '可稍后重试；本次失败不等于线路不可用。') from None
                        try:
                            self.stage('diagnosis')
                            detail = self.diagnostics.inspect(node, proxy_port, error,
                                log_path=log_path, interface=self.interface, interface_index=self.interface_index)
                        except Exception:
                            # Optional diagnosis must not discard the original failed check.
                            detail = diagnosis('unknown', 'diagnosis_incomplete', '连接失败，补充诊断未完成',
                                str(error), suggestion='稍后重试；本次未确认具体原因。')
                        failure = DiagnosedError('unknown', 'connectivity_failed', '连接失败')
                        failure.diagnosis = detail
                        failure.args = (detail['message'],)
                        raise failure from None
                finally:
                    self.stage('cleanup')
                    if process and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
            log_text = log_path.read_text(encoding='utf-8', errors='replace')
            result['route_verified'] = any(
                '[TCP]' in line and f"{result['destination_ipv4']}:443" in line and node['name'] in line
                for line in log_text.splitlines())
            if not result['route_verified']:
                raise DiagnosedError('unknown', 'route_unconfirmed', '未确认检测结果来源',
                                     '未计为检测成功，也不能据此判断线路不可用。')
            result.pop('destination_ipv4')
            return result

    def _resolve_address(self, proxy_port, force=False):
        key = (self.interface, self.interface_index)
        if not force and self._dns_cache and self._dns_cache['key'] == key and time.monotonic() < self._dns_cache['expires']:
            self.stage('dns', dns_cache_hit=True)
            return self._dns_cache['address'], True
        self.stage('dns', dns_cache_hit=False)
        self._dns_cache = None
        with requests.Session() as session:
            session.trust_env = False
            proxy = f'http://127.0.0.1:{proxy_port}'
            try:
                dns = session.get('https://dns.google/resolve', params={'name': 'my.ippure.com', 'type': 'A'},
                                  proxies={'http': proxy, 'https': proxy}, timeout=(8, 15))
                if not dns.ok:
                    raise PanelError(f'检测服务的地址解析失败：DNS 服务返回 HTTP {dns.status_code}。')
                records = dns.json().get('Answer', [])
                answers = [r['data'] for r in records if r.get('type') == 1]
            except requests.Timeout:
                raise PanelError('查询 IPPure 地址超时，尚未查询风险评分。') from None
            except requests.exceptions.SSLError:
                raise PanelError('查询 IPPure 地址时安全连接失败，尚未查询风险评分。') from None
            except requests.RequestException:
                raise PanelError('无法通过这条线路查找 IPPure 地址，尚未查询风险评分。') from None
        address = next((a for a in answers if ipaddress.ip_address(a).version == 4), None)
        if not address:
            raise PanelError('无法取得检测服务的 IPv4 地址，请稍后重试。')
        # Cache only the service address, never an exit IP or risk result.
        # Include CNAME lifetimes and cap reuse to five minutes.
        ttl = min([300] + [max(0, r.get('TTL', 0)) for r in records if r.get('type') in (1, 5)])
        if ttl > 0:
            self._dns_cache = {'key': key, 'address': address, 'expires': time.monotonic() + ttl}
        return address, False

    def _request(self, proxy_port, directory, node=None, manual=False):
        address, cached = self._resolve_address(proxy_port)
        response = self._fetch_score(proxy_port, address)
        if cached and response.returncode in (6, 7, 28, 35, 56):
            # A stale edge address must not strand another line. One fresh DNS
            # lookup; retry only if it actually gives a different address.
            fresh, _ = self._resolve_address(proxy_port, force=True)
            if fresh != address:
                address = fresh
                response = self._fetch_score(proxy_port, address)
        return self._parse_response(response, address)

    def _fetch_score(self, proxy_port, address):
        if self._last_risk_started is not None:
            wait = max(0, self._last_risk_started + 3 - time.monotonic())
            if wait:
                self.stage('risk_wait')
                time.sleep(wait)
        self._last_risk_started = time.monotonic()
        env = {k: v for k, v in os.environ.items()
               if k.lower() not in ['http_proxy', 'https_proxy', 'all_proxy', 'no_proxy']}
        curl = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'curl.exe'
        self.stage('risk')
        response = subprocess.run([
            str(curl), '--disable', '--silent', '--show-error', '--ipv4',
            '--proxy', f'socks5://127.0.0.1:{proxy_port}', '--noproxy', '',
            '--resolve', f'my.ippure.com:443:{address}', '--connect-timeout', '8', '--max-time', '25',
            '--user-agent', 'Clash-IP-Panel/0.1', '--write-out', '\n%{http_code}', ENDPOINT,
        ], capture_output=True, timeout=30, env=env, creationflags=NO_WINDOW)
        return response

    def _parse_response(self, response, address):
        if response.returncode == 28:
            raise PanelError('连接这条线路超时，请稍后重试。')
        if response.returncode == 60:
            raise PanelError('无法确认 IPPure 网站身份，本次未取得风险评分。')
        if response.returncode in (35, 56):
            raise PanelError('与 IPPure 的安全连接失败或中断，本次未取得风险评分。')
        if response.returncode:
            raise PanelError('线路无法完成 HTTPS 检测，请稍后重试。')
        body, status = response.stdout.rsplit(b'\n', 1)
        status = int(status)
        if status == 429:
            raise QueryBlocked('查询过于频繁，IPPure 暂时限制了检测。', kind='rate_limit')
        if status in (401, 403):
            raise QueryBlocked('IPPure 拒绝了这次查询，请稍后再试。', kind='denied')
        if status != 200:
            raise PanelError(f'IPPure 暂时无法完成查询（HTTP {status}）。')
        page = body.decode('utf-8', errors='replace').lower()
        if (any(marker in page for marker in ('cf-chl-', '/cdn-cgi/challenge-platform/',
                                             'cf-turnstile', 'g-recaptcha', 'h-captcha'))
                or re.search(r'<title[^>]*>[^<]*(?:captcha|just a moment|人机验证)', page)):
            raise QueryBlocked('IPPure 要求人机验证，请到网站手动查看；本次未获取风险值。',
                               kind='unsupported_challenge')
        data = json.loads(body)
        try:
            observed = ipaddress.IPv4Address(data.get('ip', ''))
        except (ValueError, AttributeError):
            pass
        else:
            self.progress = dict(self.progress or {}, observed_ip=str(observed))
        result = parse_result(data)
        # Ping0 is now a separate user-opened website, never a check dependency.
        result['destination_ipv4'] = address
        return result
