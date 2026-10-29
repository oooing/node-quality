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
        raise PanelError('本次返回 IPv6，IPPure 不提供 IPv6 风险值。')
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
        self.diagnostics = diagnostics
        self.progress = None
        self.interface = None

    def check(self, node, manual=False):
        # Keep the former manual argument compatible; checks now use IPPure only.
        started = time.monotonic()
        record = {'checked_at': datetime.now(SHANGHAI).isoformat(timespec='milliseconds'), 'status': 'error'}
        self.progress = {'node_id': node.get('id'), 'stage': 'starting'}
        try:
            if node['unsupported']:
                raise PanelError(node['unsupported'])
            if not self.core.is_file():
                raise PanelError('检测引擎缺失，请重新安装节点优选。')
            record.update(self._run(node))
            record['status'] = 'ok'
        except QueryBlocked as error:
            record.update(error=str(error), service_blocked=True, block_kind=error.kind or 'denied')
        except PanelError as error:
            record['error'] = str(error)
        except requests.Timeout:
            record['error'] = '节点连接超时，请检查节点是否可用后重试。'
        except requests.RequestException:
            record['error'] = '无法通过这个节点连接检测服务，请稍后重试。'
        except (ValueError, KeyError):
            record['error'] = '检测服务返回了不完整的数据，请稍后重试。'
        except (OSError, subprocess.SubprocessError):
            record['error'] = '检测进程无法完成请求，请稍后重试。'
        if self.progress and self.progress.get('connectivity'):
            record['connectivity'] = self.progress['connectivity']
            if record['status'] != 'ok' and record['connectivity']['status'] == 'ok':
                record['error'] = '连通测试通过；' + record.get('error', '风险查询失败')
        self.progress = None
        record['elapsed_seconds'] = round(time.monotonic() - started, 3)
        return record

    def _run(self, node, manual=False):
        proxy_port, api_port = free_ports()
        token = secrets.token_urlsafe(24)
        with tempfile.TemporaryDirectory(prefix='check-', dir=self.runtime) as temporary:
            directory = Path(temporary).resolve()
            # Cleanup is restricted to the check directory owned by this application.
            if directory.parent != self.runtime:
                raise PanelError('临时检测目录不正确。')
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
                raise PanelError('未找到可用的物理网卡，已停止检测。')
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
                            raise PanelError('这个节点的配置无法启动检测，请检查节点配置。')
                        try:
                            response = control.get(f'http://127.0.0.1:{api_port}/version', timeout=.4)
                            if response.ok:
                                ready = True
                                break
                        except requests.RequestException:
                            pass
                        time.sleep(.15)
                    if not ready:
                        raise PanelError('检测内核启动超时，请稍后重试。')
                    try:
                        self.progress = {'node_id': node['id'], 'stage': 'connectivity'}
                        connection = check_connectivity(control, api_port, node['name'])
                        self.progress = {'node_id': node['id'], 'stage': 'risk', 'connectivity': connection}
                        if connection['status'] != 'ok':
                            raise PanelError('两个测试地址均连接超时，本次未查询出口 IP。' if connection['status'] == 'timeout'
                                             else '两个测试地址均未通过连通测试，本次未查询出口 IP。')
                        result = self._request(proxy_port, directory)
                    except QueryBlocked:
                        raise
                    except (requests.RequestException, PanelError) as error:
                        if self.diagnostics is None:
                            raise
                        try:
                            self.progress = dict(self.progress, stage='diagnosis')
                            diagnosis = self.diagnostics.inspect(node, proxy_port, error)
                        except Exception:
                            # Optional diagnosis must not discard the original failed check.
                            raise error from None
                        raise PanelError(diagnosis.get('message', str(error))) from None
                finally:
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
                raise PanelError('未能确认检测请求的节点路径，本次结果未作为成功记录。')
            result.pop('destination_ipv4')
            return result

    def _request(self, proxy_port, directory, node=None, manual=False):
        with requests.Session() as session:
            session.trust_env = False
            proxy = f'http://127.0.0.1:{proxy_port}'
            try:
                dns = session.get('https://dns.google/resolve', params={'name': 'my.ippure.com', 'type': 'A'},
                                  proxies={'http': proxy, 'https': proxy}, timeout=(8, 15))
                if not dns.ok:
                    raise PanelError(f'检测服务的地址解析失败：DNS 服务返回 HTTP {dns.status_code}。')
                answers = [r['data'] for r in dns.json().get('Answer', []) if r.get('type') == 1]
            except requests.Timeout:
                raise PanelError('查询 IPPure 的 IPv4 地址超时（Google DNS），尚未发起风险查询。') from None
            except requests.exceptions.SSLError:
                raise PanelError('查询 IPPure 地址时与 Google DNS 的 TLS 连接失败，尚未发起风险查询。') from None
            except requests.RequestException:
                raise PanelError('节点未能连接 Google DNS 获取 IPPure 地址，尚未发起风险查询。') from None
        address = next((a for a in answers if ipaddress.ip_address(a).version == 4), None)
        if not address:
            raise PanelError('无法取得检测服务的 IPv4 地址，请稍后重试。')
        env = {k: v for k, v in os.environ.items()
               if k.lower() not in ['http_proxy', 'https_proxy', 'all_proxy', 'no_proxy']}
        curl = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'curl.exe'
        response = subprocess.run([
            str(curl), '--disable', '--silent', '--show-error', '--ipv4',
            '--proxy', f'socks5://127.0.0.1:{proxy_port}', '--noproxy', '',
            '--resolve', f'my.ippure.com:443:{address}', '--connect-timeout', '8', '--max-time', '25',
            '--user-agent', 'Clash-IP-Panel/0.1', '--write-out', '\n%{http_code}', ENDPOINT,
        ], capture_output=True, timeout=30, env=env, creationflags=NO_WINDOW)
        if response.returncode == 28:
            raise PanelError('节点连接超时，请检查节点是否可用后重试。')
        if response.returncode == 60:
            raise PanelError('IPPure 的 HTTPS 证书验证失败，本次未取得风险值。')
        if response.returncode in (35, 56):
            raise PanelError('连接 IPPure 时 TLS 握手失败或连接被中断，本次未取得风险值。')
        if response.returncode:
            raise PanelError('节点无法完成 HTTPS 检测，请稍后重试。')
        body, status = response.stdout.rsplit(b'\n', 1)
        status = int(status)
        if status == 429:
            raise QueryBlocked('IPPure 暂时限制了查询频率，请稍后再试。', kind='rate_limit')
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
        result = parse_result(json.loads(body))
        # Ping0 is now a separate user-opened website, never a check dependency.
        result['destination_ipv4'] = address
        return result
