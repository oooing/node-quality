"""Read client profiles, own their copies, and refresh without writing to Clash."""
import copy
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

import requests
import yaml

from catalog import PanelError, digest, node_id

MAX_BYTES = 8 * 1024 * 1024


def read_yaml(path):
    try:
        value = yaml.safe_load(Path(path).read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}


def discover(roots=None):
    if roots is None:
        appdata = Path(os.environ.get('APPDATA', str(Path.home())))
        roots = [appdata / 'io.github.clash-verge-rev.clash-verge-rev',
                 appdata / 'io.github.clash-verge.clash-verge']
    found = []
    for root in dict.fromkeys(str(Path(p).resolve()) for p in roots):
        directory = Path(root)
        data = read_yaml(directory / 'profiles.yaml')
        for item in data.get('items', []) or []:
            if not isinstance(item, dict) or item.get('type') not in ('remote', 'local'):
                continue
            uid = item.get('uid')
            if not uid:
                continue
            cache = (directory / 'profiles' / str(item.get('file') or '')).resolve()
            if not cache.is_relative_to((directory / 'profiles').resolve()):
                continue
            url = item.get('url') or ''
            if not valid_url(url):
                url = ''
            found.append({'id': digest([root, uid])[:24], 'name': item.get('name') or '未命名订阅',
                          'url': url, 'cache': str(cache), 'source_root': root, 'source_uid': uid,
                          'current': uid == data.get('current'), 'origin': 'Clash Verge',
                          'mode': 'remote' if url else 'cache'})
    return found


def valid_url(url):
    try:
        parsed = urlsplit(url)
        return parsed.scheme in ('http', 'https') and bool(parsed.hostname)
    except (TypeError, ValueError):
        return False


def fetch_yaml(url, headers=None):
    # Subscription download may use the existing system proxy, but never changes it.
    try:
        with requests.Session() as session:
            session.headers['User-Agent'] = 'clash.meta/NodeQuality-0.1'
            with session.get(url, timeout=(10, 25), headers=headers, stream=True) as response:
                if response.status_code in (401, 403):
                    raise PanelError(f'订阅服务拒绝更新（HTTP {response.status_code}），保留上次节点。')
                if not response.ok:
                    raise PanelError(f'订阅更新失败（HTTP {response.status_code}），保留上次节点。')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise PanelError('订阅文件超过 8 MB，未导入。')
                    chunks.append(chunk)
                raw = b''.join(chunks).decode('utf-8-sig')
        value = yaml.safe_load(raw)
        if not isinstance(value, dict):
            raise PanelError('暂只支持 Clash / Mihomo YAML 订阅，请使用兼容链接。')
        return value
    except requests.Timeout:
        raise PanelError('订阅下载超时，保留上次节点并稍后重试。') from None
    except requests.RequestException:
        raise PanelError('无法连接订阅服务器，保留上次节点并稍后重试。') from None
    except (UnicodeError, yaml.YAMLError):
        raise PanelError('订阅返回内容不是有效的 Clash YAML。') from None


def extract_nodes(data, profile, base=None, download=False):
    proxies = data.get('proxies', [])
    if not isinstance(proxies, list):
        raise PanelError('订阅中的节点列表格式不正确。')
    proxies = list(proxies)
    providers = data.get('proxy-providers', {}) or {}
    if not isinstance(providers, dict):
        raise PanelError('订阅中的代理集合格式不正确。')
    for provider in providers.values():
        if not isinstance(provider, dict):
            raise PanelError('代理集合格式不正确。')
        items = provider.get('payload')
        if items is None and provider.get('type') == 'http' and download:
            if not valid_url(provider.get('url')):
                raise PanelError('代理集合的链接无效。')
            items = fetch_yaml(provider['url']).get('proxies')
        if items is None and provider.get('path') and base:
            root = Path(base).resolve()
            path = (root / provider['path']).resolve()
            if path.is_relative_to(root):
                items = read_yaml(path).get('proxies')
        if not isinstance(items, list):
            raise PanelError('无法读取代理集合；需要可下载的 YAML 链接或有效的本地缓存。')
        proxies.extend(items)
    nodes, seen = [], set()
    for proxy in proxies:
        if not isinstance(proxy, dict) or not isinstance(proxy.get('name'), str):
            continue
        if not proxy.get('server') or not proxy.get('port'):
            continue
        if re.match(r'^(剩余流量|套餐到期|距离下次重置|注意[:：])', proxy['name']):
            continue
        key = node_id(profile['id'], proxy)
        if key in seen:
            continue
        seen.add(key)
        reason = None
        if proxy.get('dialer-proxy'):
            reason = '链式节点暂不支持独立检测'
        if proxy.get('type') in ('wireguard', 'tailscale', 'openvpn', 'zerotier', 'easy-tiers'):
            reason = '此类隧道暂不支持隔离检测'
        nodes.append({'id': key, 'name': proxy['name'], 'type': proxy.get('type', ''),
                      'profile_id': profile['id'], 'profile_name': profile['name'],
                      'config': proxy, 'fingerprint': digest(proxy), 'unsupported': reason})
    if not nodes:
        raise PanelError('订阅里没有可识别的节点，保留上次节点。')
    return nodes


class Subscriptions:
    def __init__(self, directory, roots=None, now=time.time):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'subscriptions.json'
        self.lock = threading.RLock()
        self.roots, self.now = roots, now
        self.items = {}
        if self.path.exists():
            self.items = json.loads(self.path.read_text(encoding='utf-8'))
        self.scan()

    def save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.items, ensure_ascii=False), encoding='utf-8')
        tmp.replace(self.path)

    def scan(self, extra_root=None):
        roots = self.roots
        if extra_root:
            roots = [extra_root]
        found = discover(roots)
        with self.lock:
            first = not self.items
            selected = next((p['id'] for p in found if p['current']), found[0]['id'] if found else None)
            for source in found:
                key = source['id']
                if key in self.items:
                    # Keep schedule/history; follow renewed links in the source client.
                    old = self.items[key]
                    if old.get('url') != source['url']:
                        old['next_update'] = 0
                    old.update(source)
                    continue
                item = dict(source, enabled=first and key == selected, nodes=[], last_update=0,
                            next_update=0, error=None)
                try:
                    item['nodes'] = extract_nodes(read_yaml(source['cache']), item, source['source_root'])
                except PanelError as error:
                    item['error'] = str(error)
                self.items[key] = item
            self.save()
        return len(found)

    def public(self):
        with self.lock:
            return [{key: p.get(key) for key in ('id', 'name', 'current', 'enabled', 'origin', 'mode',
                                                 'last_update', 'next_update', 'error')} |
                    {'node_count': len(p.get('nodes', []))} for p in self.items.values()]

    def nodes(self, profile_id=None, enabled_only=False):
        with self.lock:
            return copy.deepcopy([n for p in self.items.values()
                                  if (profile_id is None or p['id'] == profile_id)
                                  and (not enabled_only or p['enabled']) for n in p.get('nodes', [])])

    def enable(self, ids):
        if not isinstance(ids, list):
            raise PanelError('订阅选择无效。')
        with self.lock:
            for key, profile in self.items.items():
                if key in ids and not profile['enabled']:
                    profile['next_update'] = 0
                profile['enabled'] = key in ids
            self.save()

    def add(self, name, url='', text=''):
        if not url and not text:
            raise PanelError('请输入订阅链接或选择 YAML 文件。')
        if url and not valid_url(url):
            raise PanelError('请输入有效的 HTTP(S) 订阅链接。')
        key = digest(url or text)[:24]
        item = {'id': key, 'name': (name or '导入的订阅')[:100], 'url': url,
                'enabled': True, 'current': False, 'origin': '手动导入', 'mode': 'remote' if url else 'file',
                'nodes': [], 'last_update': 0, 'next_update': 0, 'error': None}
        if text:
            try:
                data = yaml.safe_load(text)
                if not isinstance(data, dict):
                    raise ValueError()
                item['nodes'] = extract_nodes(data, item)
                item['last_update'] = self.now()
                item['next_update'] = self.now() + 86400 * 365
            except (ValueError, yaml.YAMLError):
                raise PanelError('文件不是有效的 Clash YAML。') from None
        with self.lock:
            if key not in self.items:
                self.items[key] = item
            else:
                self.items[key]['enabled'] = True
            self.save()
        return key

    def refresh(self, key, hours=6):
        with self.lock:
            item = copy.deepcopy(self.items[key])
        now = self.now()
        try:
            if item['mode'] == 'file':
                return
            data = fetch_yaml(item['url']) if item['url'] else read_yaml(item['cache'])
            nodes = extract_nodes(data, item, item.get('source_root'), download=bool(item['url']))
            changes = {'nodes': nodes, 'last_update': now, 'next_update': now + hours * 3600, 'error': None}
        except PanelError as error:
            changes = {'error': str(error), 'next_update': now + 900}
        with self.lock:
            self.items[key].update(changes)
            self.save()
