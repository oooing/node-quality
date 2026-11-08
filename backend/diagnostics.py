"""Bounded failure diagnosis using only the check's own proxy, log and adapter."""
import os
import socket
import ssl

import requests

from catalog import PanelError

LABELS = {'local': '本机问题', 'line': '线路问题', 'site': '评分问题',
          'config': '线路配置', 'unknown': '原因未明'}


def diagnosis(category, code, summary, detail='', evidence=(), suggestion=''):
    return {'category': category, 'code': code, 'message': LABELS[category] + '：' + summary,
            'detail': detail, 'evidence': list(evidence), 'suggestion': suggestion}


class DiagnosedError(PanelError):
    def __init__(self, category, code, summary, detail='', evidence=(), suggestion=''):
        self.diagnosis = diagnosis(category, code, summary, detail, evidence, suggestion)
        super().__init__(self.diagnosis['message'])


def log_cause(text):
    # Never persist raw core logs: node names/addresses can contain credentials.
    lines = [line.lower().split('error:', 1)[-1] for line in text.splitlines()
             if 'error:' in line.lower() or 'level=fatal' in line.lower()]
    text = '\n'.join(lines)
    patterns = (
        ('certificate', ('x509:', 'certificate verify failed', 'certificate signed', 'certificate has expired')),
        ('auth', ('authentication failed', 'invalid password', 'unauthorized')),
        ('refused', ('connection refused', 'actively refused', 'connectex: no connection could be made')),
        ('dns', ('no such host', 'dns resolve failed', "couldn't find ip")),
        ('eof', ('eof',)),
        ('reset', ('connection reset', 'forcibly closed')),
        ('timeout', ('i/o timeout', 'context deadline exceeded', 'connect timeout')),
    )
    return next((code for code, markers in patterns if any(s in text for s in markers)), None)


def transport_probe(config, interface, interface_index=None):
    """One TCP/TLS handshake; never authenticate or use the OS proxy/TUN route."""
    result = {'tcp': 'not_tested', 'tls': 'not_tested'}
    if os.name != 'nt':
        return dict(result, skipped='当前系统未提供隔离网卡探测')
    try:
        index = interface_index or socket.if_nametoindex(interface)
    except (OSError, ValueError, TypeError):
        return dict(result, skipped='无法确定检测网卡，未使用默认网络补测')
    if not index:
        return dict(result, skipped='检测网卡不可用')
    try:
        # Only the first IPv4 endpoint is used; socket operations have short timeouts.
        address = socket.getaddrinfo(config['server'], config['port'], socket.AF_INET, socket.SOCK_STREAM)[0][4]
    except (OSError, KeyError, IndexError):
        return dict(result, tcp='dns_error')
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
            raw.settimeout(3)
            try:
                raw.setsockopt(socket.IPPROTO_IP, 31, socket.htonl(index))  # IP_UNICAST_IF
            except OSError:
                return dict(result, skipped='无法绑定检测网卡，未使用默认网络补测')
            raw.connect(address)
            result['tcp'] = 'ok'
            uses_tls = config.get('type') in ('anytls', 'trojan') or config.get('tls') is True
            if not uses_tls:
                return result
            context = ssl.create_default_context()
            if config.get('alpn'):
                context.set_alpn_protocols(config['alpn'])
            if config.get('skip-cert-verify'):
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            with context.wrap_socket(raw, server_hostname=config.get('sni') or config.get('servername') or config['server']) as secure:
                result.update(tls='ok', tls_version=secure.version())
    except ssl.SSLCertVerificationError:
        result['tls'] = 'certificate'
    except (ssl.SSLEOFError, ConnectionResetError):
        result['tls' if result['tcp'] == 'ok' else 'tcp'] = 'closed'
    except ConnectionRefusedError:
        result['tcp'] = 'refused'
    except (TimeoutError, socket.timeout):
        result['tls' if result['tcp'] == 'ok' else 'tcp'] = 'timeout'
    except ssl.SSLError:
        result['tls'] = 'error'
    except OSError:
        result['tcp' if result['tcp'] != 'ok' else 'tls'] = 'error'
    return result


class FailureDiagnostics:
    def inspect(self, node, proxy_port, error, *, log_path, interface, interface_index=None):
        def read_log():
            try:
                return log_path.read_text(encoding='utf-8', errors='replace')[-32768:]
            except OSError:
                return ''
        cause = log_cause(read_log())
        # Delay API errors are generic. One HTTPS request makes the same core log
        # its actual dial failure; no retry loop or IP-risk query is added here.
        if cause is None:
            with requests.Session() as request:
                request.trust_env = False
                proxy = f'http://127.0.0.1:{proxy_port}'
                try:
                    request.get('https://cp.cloudflare.com/generate_204',
                                proxies={'http': proxy, 'https': proxy}, timeout=(3, 3))
                except requests.RequestException:
                    pass
            cause = log_cause(read_log())
        probe = transport_probe(node['config'], interface, interface_index) if cause in ('eof', 'reset', 'certificate') else {}
        evidence = []
        if cause:
            evidence.append({'eof': '隔离引擎：连接提前结束（EOF）', 'reset': '隔离引擎：连接被重置',
                'certificate': '隔离引擎：线路服务器证书校验失败', 'auth': '隔离引擎明确返回认证失败',
                'refused': '隔离引擎：目标端口拒绝连接', 'dns': '隔离引擎：线路服务器地址解析失败',
                'timeout': '隔离引擎：连接超时'}[cause])
        if probe.get('tcp') == 'ok':
            evidence.append('独立 TCP 探测：服务器端口可连接')
        if probe.get('tls') == 'closed':
            evidence.append('独立 TLS 探测：握手未完成，连接被断开')
            result = diagnosis('line', 'tls_closed', 'TLS 握手被提前断开',
                '服务器端口能连接，但加密握手未完成。尚未取得 IP 和评分。', evidence,
                '可稍后重试或联系线路提供方；仅凭此结果无法区分服务端和中间网络。')
        elif probe.get('tls') == 'ok' and cause in ('eof', 'reset'):
            evidence.append('独立 TLS 探测：加密握手通过')
            result = diagnosis('line', 'session_closed', '代理会话被提前断开',
                '独立加密握手通过，但代理会话未建立成功；不能据此断定密码错误。', evidence,
                '更新线路后重试；持续失败时联系线路提供方。')
        elif cause:
            summary = {'eof': '代理连接提前结束（EOF）', 'reset': '代理连接被重置',
                'certificate': '服务器证书校验失败', 'auth': '服务器拒绝认证',
                'refused': '服务器端口拒绝连接', 'dns': '服务器地址解析失败',
                'timeout': '连接超时'}[cause]
            result = diagnosis('line', cause, summary,
                '这条线路本次未建立可用连接，尚未取得 IP 和评分。', evidence,
                '可更新线路后重试；持续失败时联系线路提供方。')
        else:
            result = diagnosis('unknown', 'connectivity_failed', '连接测试未通过',
                '两个测试网站均未连接成功，引擎没有提供更具体的原因。不能据此判断线路永久不可用。',
                ['两个隔离连通性测试均失败'], '稍后重试，或更新线路后再检测。')
        if probe:
            result['transport'] = probe
        return result
