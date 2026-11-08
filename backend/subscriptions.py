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


def client_name(directory):
    return {
        'io.github.clash-verge-rev.clash-verge-rev': 'Clash Verge Rev',
        'io.github.clash-verge.clash-verge': 'Clash Verge',
    }.get(Path(directory).name.lower(), 'Clash 兼容客户端')


def read_yaml(path):
    try:
        value = yaml.safe_load(Path(path).read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}


def discover(roots=None, valid_roots=None):
    if roots is None:
        appdata = Path(os.environ.get('APPDATA', str(Path.home())))
        roots = [appdata / 'io.github.clash-verge-rev.clash-verge-rev',
                 appdata / 'io.github.clash-verge.clash-verge']
    found = []
    for root in dict.fromkeys(str(Path(p).resolve()) for p in roots):
        directory = Path(root)
        data = read_yaml(directory / 'profiles.yaml')
        # Only a readable client list can establish that a source was deleted.
        # A missing/partially written file must keep the last known sources.
        if not isinstance(data.get('items'), list):
            continue
        if valid_roots is not None:
            valid_roots.add(root)
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
            found.append({'id': digest([root, uid])[:24], 'name': item.get('name') or '未命名列表',
                          'url': url, 'cache': str(cache), 'source_root': root, 'source_uid': uid,
                          'current': uid == data.get('current'), 'origin': client_name(directory),
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
                    raise PanelError(f'列表服务拒绝更新（HTTP {response.status_code}），保留上次线路。')
                if not response.ok:
                    raise PanelError(f'列表更新失败（HTTP {response.status_code}），保留上次线路。')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise PanelError('列表文件超过 8 MB，未导入。')
                    chunks.append(chunk)
                raw = b''.join(chunks).decode('utf-8-sig')
        value = yaml.safe_load(raw)
        if not isinstance(value, dict):
            raise PanelError('请使用 Clash 兼容的线路链接。')
        return value
    except requests.Timeout:
        raise PanelError('列表下载超时，保留上次线路并稍后重试。') from None
    except requests.RequestException:
        raise PanelError('无法连接列表服务器，保留上次线路并稍后重试。') from None
    except (UnicodeError, yaml.YAMLError):
        raise PanelError('链接返回的内容不是 Clash 兼容的线路列表。') from None


def extract_nodes(data, profile, base=None, download=False):
    proxies = data.get('proxies', [])
    if not isinstance(proxies, list):
        raise PanelError('列表中的线路列表格式不正确。')
    proxies = list(proxies)
    providers = data.get('proxy-providers', {}) or {}
    if not isinstance(providers, dict):
        raise PanelError('列表中的代理集合格式不正确。')
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
            raise PanelError('未能读取线路，请检查链接或重新导入文件。')
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
            reason = '暂不支持需要多条线路接力的连接。'
        if proxy.get('type') in ('wireguard', 'tailscale', 'openvpn', 'zerotier', 'easy-tiers'):
            reason = '暂不支持这类线路的独立检测。'
        nodes.append({'id': key, 'name': proxy['name'], 'type': proxy.get('type', ''),
                      'profile_id': profile['id'], 'profile_name': profile['name'],
                      'config': proxy, 'fingerprint': digest(proxy), 'unsupported': reason})
    if not nodes:
        raise PanelError('列表里没有可识别的线路，保留上次线路。')
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
        valid_roots = set()
        found = discover(roots, valid_roots)
        with self.lock:
            first = not self.items
            found_ids = {p['id'] for p in found}
            for key, item in self.items.items():
                source_root = item.get('source_root')
                if source_root and str(Path(source_root).resolve()) in valid_roots:
                    item['source_missing'] = key not in found_ids
                    if item['source_missing']:
                        item['current'] = False
            selected = next((p['id'] for p in found if p['current']), found[0]['id'] if found else None)
            for source in found:
                key = source['id']
                if key in self.items:
                    # Keep schedule/history; follow renewed links in the source client.
                    old = self.items[key]
                    if old.get('url') != source['url']:
                        old['next_update'] = 0
                    old.update(source)
                    for node in old.get('nodes', []):
                        node['profile_name'] = source['name']
                    old['source_missing'] = False
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
                    {'node_count': len(p.get('nodes', []))} for p in self.items.values() if not p.get('source_missing')]

    def nodes(self, profile_id=None, enabled_only=False):
        with self.lock:
            return copy.deepcopy([n for p in self.items.values()
                                  if not p.get('source_missing') and (profile_id is None or p['id'] == profile_id)
                                  and (not enabled_only or p['enabled']) for n in p.get('nodes', [])])

    def enable(self, ids):
        if not isinstance(ids, list):
            raise PanelError('列表选择无效。')
        with self.lock:
            for key, profile in self.items.items():
                if key in ids and not profile['enabled']:
                    profile['next_update'] = 0
                profile['enabled'] = key in ids
            self.save()

    def add(self, name, url='', text=''):
        if not url and not text:
            raise PanelError('请粘贴线路链接或导入文件。')
        if url and not valid_url(url):
            raise PanelError('链接需以 http:// 或 https:// 开头。')
        key = digest(url or text)[:24]
        item = {'id': key, 'name': (name or '导入的列表')[:100], 'url': url,
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
                raise PanelError('文件格式不支持，请选择 Clash 兼容文件。') from None
        with self.lock:
            if key not in self.items:
                self.items[key] = item
            else:
                self.items[key]['enabled'] = True
            self.save()
        return key

    def refresh(self, key, hours=6):
        with self.lock:
            if self.items[key].get('source_missing'):
                return False
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
