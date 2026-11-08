"""Control the running official core through its existing local controller."""
import copy
from collections import Counter
import ctypes
import http.client
import io
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote, urlsplit

import requests
import yaml

from catalog import PanelError, digest
from subscriptions import discover
from official_selection import OfficialSelection


PIPE_ROOT = '\\\\.\\pipe\\'
CONTROL_TIMEOUT = 5


def _effective_config(directory):
    try:
        config = yaml.safe_load((Path(directory) / 'clash-verge.yaml').read_text(encoding='utf-8'))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise PanelError('无法读取 Clash 当前生效配置。') from None
    if not isinstance(config, dict):
        raise PanelError('Clash 当前生效配置格式不正确。')
    return config


def _select_pipe(configured, names):
    """The service and sidecar use different pipe prefixes for the same owner."""
    if not isinstance(configured, str) or not configured.startswith(PIPE_ROOT):
        return None
    name = configured[len(PIPE_ROOT):]
    match = re.fullmatch(r'verge-mihomo-(?:sidecar-(?:release|dev)|production|development)-([a-f0-9]{64})', name)
    candidates = [name]
    if match:
        flavor = 'development' if 'sidecar-dev-' in name or 'development-' in name else 'production'
        candidates.insert(0, f'verge-mihomo-{flavor}-{match[1]}')
    return next((PIPE_ROOT + candidate for candidate in candidates if candidate in names), None)


class _PipeReader(io.RawIOBase):
    """Read available pipe bytes with a bounded controller response timeout."""
    def __init__(self, stream):
        import msvcrt
        from ctypes import wintypes
        self.stream = stream
        self.handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
        self.deadline = time.monotonic() + CONTROL_TIMEOUT
        self.available = wintypes.DWORD()
        self.peek = ctypes.WinDLL('kernel32', use_last_error=True).PeekNamedPipe
        self.peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.peek.restype = wintypes.BOOL

    def readable(self):
        return True

    def readinto(self, buffer):
        while time.monotonic() < self.deadline:
            if not self.peek(self.handle, None, 0, None, ctypes.byref(self.available), None):
                error = ctypes.get_last_error()
                if error in (109, 233):  # The controller closed this HTTP connection.
                    return 0
                raise ctypes.WinError(error)
            if self.available.value:
                data = self.stream.read(min(len(buffer), self.available.value))
                buffer[:len(data)] = data
                return len(data)
            time.sleep(.01)
        raise TimeoutError('controller response timed out')


class _PipeSocket:
    def __init__(self, stream):
        self.stream = stream

    def makefile(self, *_args, **_kwargs):
        return io.BufferedReader(_PipeReader(self.stream))


class LocalController:
    def __init__(self, config):
        self.pipe = None
        self.base_url = None
        self.secret = ''
        configured_pipe = config.get('external-controller-pipe')
        if os.name == 'nt' and configured_pipe:
            try:
                self.pipe = _select_pipe(configured_pipe, os.listdir(PIPE_ROOT))
            except OSError:
                pass
        if self.pipe:
            return
        address = config.get('external-controller')
        if isinstance(address, str) and address:
            try:
                parsed = urlsplit('http://' + address)
                if parsed.hostname in ('127.0.0.1', 'localhost', '::1') and parsed.port:
                    self.base_url = 'http://' + address
                    self.secret = config.get('secret') or ''
            except ValueError:
                pass
        if not self.base_url:
            raise PanelError('暂时连不上 Clash，请确认它已打开。')

    def request(self, method, path, payload=None):
        try:
            if self.pipe:
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else b''
                headers = [f'{method} {path} HTTP/1.1', 'Host: localhost', 'Connection: close',
                           'Content-Type: application/json', f'Content-Length: {len(body)}', '', '']
                with open(self.pipe, 'r+b', buffering=0) as stream:
                    stream.write('\r\n'.join(headers).encode('ascii') + body)
                    response = http.client.HTTPResponse(_PipeSocket(stream))
                    response.begin()
                    status = response.status
                    content = response.read()
                    response.close()
            else:
                with requests.Session() as session:
                    session.trust_env = False
                    headers = {'Authorization': f'Bearer {self.secret}'} if self.secret else {}
                    response = session.request(method, self.base_url + path, json=payload,
                                               headers=headers, timeout=CONTROL_TIMEOUT, allow_redirects=False)
                    status, content = response.status_code, response.content
            if status in (401, 403):
                raise PanelError('Clash 控制接口拒绝访问，请在 Clash 中检查控制设置。')
            if not 200 <= status < 300:
                raise PanelError(f'Clash 控制接口未完成操作（HTTP {status}），请刷新后重试。')
            return json.loads(content) if content else None
        except PanelError:
            raise
        except (OSError, TimeoutError, requests.RequestException, http.client.HTTPException,
                ValueError, UnicodeError):
            raise PanelError('无法读取 Clash 控制接口的响应，请确认 Clash 正在运行后重试。') from None


class ClashControl:
    """Read-only discovery; only select() can change one explicit Selector."""
    def __init__(self, subscriptions, controller_factory=LocalController, selection_runner=None):
        self.subscriptions = subscriptions
        self.controller_factory = controller_factory
        self.selection_runner = selection_runner or OfficialSelection()
        self.selection_lock = threading.Lock()

    def _snapshot(self, profile_id):
        state = {'available': False, 'profile_id': profile_id, 'current_profile': None,
                 'mode': None, 'groups': [], 'can_switch': False, 'switchable_ids': []}
        controller, nodes = None, []
        try:
            with self.subscriptions.lock:
                profile = copy.deepcopy(self.subscriptions.items.get(profile_id) or {})
            if not profile.get('source_root') or not profile.get('source_uid'):
                raise PanelError('这个列表未关联 Clash，可以检测，但不能直接换用。')
            current = next((p for p in discover([profile['source_root']]) if p['current']), None)
            if current is None:
                raise PanelError('无法确认 Clash 当前列表，请先在 Clash 启用列表。')
            state['current_profile'] = {k: current[k] for k in ('id', 'name')}
            if current['id'] != profile_id:
                raise PanelError('请先在 Clash 启用这个列表，再点击“刷新分组”。')
            config = _effective_config(profile['source_root'])
            controller = self.controller_factory(config)
            general = controller.request('GET', '/configs')
            result = controller.request('GET', '/proxies')
            proxies = result.get('proxies') if isinstance(result, dict) else None
            mode = general.get('mode') if isinstance(general, dict) else None
            if mode not in ('rule', 'global', 'direct') or not isinstance(proxies, dict):
                raise PanelError('Clash 返回的模式或代理组数据不完整。')
            state.update(available=True, mode=mode)
            nodes = profile.get('nodes', [])
            # A downloaded subscription may be newer than the running Clash config.
            # Do not switch by name alone or apply a risk result to a different route.
            configured = [n for n in config.get('proxies', []) if isinstance(n, dict)]
            counts = Counter(n.get('name') for n in configured)
            owned_counts = Counter(n['name'] for n in nodes)
            by_name = {n.get('name'): n for n in configured}
            matched = [n for n in nodes if counts[n['name']] == 1 and owned_counts[n['name']] == 1
                       and digest(by_name[n['name']]) == n['fingerprint']
                       and isinstance(proxies.get(n['name']), dict)
                       and proxies[n['name']].get('type', '').lower() ==
                       {'ss': 'shadowsocks', 'ssr': 'shadowsocksr'}.get(n['type'].lower(), n['type'].lower())]
            state['switchable_ids'] = [n['id'] for n in matched]
            names = {n['name'] for n in matched}
            order = [g.get('name') for g in config.get('proxy-groups', []) if isinstance(g, dict)]
            order += [name for name in proxies if name not in order]
            order = ['GLOBAL'] if mode == 'global' else [] if mode == 'direct' else [n for n in order if n != 'GLOBAL']
            for name in dict.fromkeys(order):
                group = proxies.get(name)
                if not isinstance(group, dict) or group.get('type') != 'Selector':
                    continue
                members = group.get('all')
                if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
                    continue
                if names.intersection(members) and isinstance(group.get('now'), str):
                    state['groups'].append({'name': name, 'selected': group['now'], 'members': members})
            state['can_switch'] = bool(state['groups'])
            if mode == 'direct':
                state['reason'] = 'Clash 正在直连，请先在 Clash 开启代理。'
            elif not matched:
                state['reason'] = '线路配置与 Clash 当前运行配置不一致，请更新 Clash 列表后再刷新。'
            elif not state['groups']:
                state['reason'] = 'Clash 中没有可直接选择这些线路的分组。'
        except PanelError as error:
            state['reason'] = str(error)
        return state, controller, nodes

    def status(self, profile_id):
        return self._snapshot(profile_id)[0]

    def select(self, profile_id, node_id, group_name):
        if not self.selection_lock.acquire(blocking=False):
            raise PanelError('正在换用并保存，请稍候。')
        try:
            return self._select(profile_id, node_id, group_name)
        finally:
            self.selection_lock.release()

    def _select(self, profile_id, node_id, group_name):
        if not all(isinstance(v, str) and v for v in (profile_id, node_id, group_name)):
            raise PanelError('请指定列表、线路和代理组。')
        state, controller, nodes = self._snapshot(profile_id)
        if not state['can_switch']:
            raise PanelError(state.get('reason') or 'Clash 当前不能切换这个线路。')
        node = next((n for n in nodes if n['id'] == node_id), None)
        if node is None or node_id not in state['switchable_ids']:
            raise PanelError('线路信息与 Clash 不一致，请先在 Clash 中更新。')
        group = next((g for g in state['groups'] if g['name'] == group_name), None)
        if group is None or node['name'] not in group['members']:
            raise PanelError('这个线路不是所选手动代理组的直接成员。')
        with self.subscriptions.lock:
            profile = copy.deepcopy(self.subscriptions.items[profile_id])
        result = self.selection_runner(profile, group_name, node['name'], controller)
        if not result.get('persisted'):
            raise PanelError('未确认线路已保存，请在 Clash 中查看。')
        path = '/proxies/' + quote(group_name, safe='')
        confirmed = controller.request('GET', path)
        if not isinstance(confirmed, dict) or confirmed.get('type') != 'Selector' or confirmed.get('now') != node['name']:
            raise PanelError('已发送切换请求，但未确认成功，请到 Clash 查看。')
        return {'verified': True, 'persisted': True, 'group': group_name, 'selected': node['name'],
                'previous': group['selected'], 'mode': state['mode']}
