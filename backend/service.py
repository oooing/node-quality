"""Persistent, sequential background scheduling; no API for switching user proxies."""
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import threading
import time

from catalog import PanelError
from detector import Detector
from network import Network
from recommendations import rank_nodes, normalize_options
from store import Store
from subscriptions import Subscriptions

DEFAULTS = {'paused': False, 'update_hours': 6, 'candidate_hours': 6, 'other_hours': 24,
            'recommendation': {'max_risk': 30, 'fresh_hours': 24, 'limit': 5, 'regions': []}}


def timestamp(value):
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return 0


def is_due(node, attempt, now, candidate_ids, settings):
    if node.get('unsupported'):
        return False
    if not attempt or attempt.get('fingerprint') != node['fingerprint']:
        return True
    hours = settings['candidate_hours'] if node['id'] in candidate_ids else settings['other_hours']
    return now - timestamp(attempt['checked_at']) >= hours * 3600


class Service:
    def __init__(self, directory, core, roots=None, start=True, detector=None, network=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.directory / 'settings.json'
        self.settings = json.loads(json.dumps(DEFAULTS))
        if self.settings_path.exists():
            self.settings.update(json.loads(self.settings_path.read_text(encoding='utf-8')))
        self.subscriptions = Subscriptions(self.directory, roots)
        self.store = Store(self.directory / 'history.sqlite3')
        self.detector = detector or Detector(core, self.directory / 'runtime')
        self.network = network or Network()
        self.lock = threading.RLock()
        self.queue = deque()
        self.refresh_queue = deque()
        self.stop_event, self.wake = threading.Event(), threading.Event()
        self.active, self.updating = None, None
        self.message = ''
        self.cooldown_until = 0
        self.schedule_path = self.directory / 'schedule.json'
        if self.schedule_path.exists():
            schedule = json.loads(self.schedule_path.read_text(encoding='utf-8'))
            self.cooldown_until = schedule.get('cooldown_until', 0)
            if self.cooldown_until > time.time():
                self.message = schedule.get('message', '')
        self.finished = 0
        self.thread = None
        if start:
            self.thread = threading.Thread(target=self.run, name='scheduler', daemon=True)
            self.thread.start()

    def save_settings(self, changes):
        with self.lock:
            values = dict(self.settings)
            if 'paused' in changes:
                if not isinstance(changes['paused'], bool):
                    raise PanelError('暂停设置无效。')
                values['paused'] = changes['paused']
            for key in ('update_hours', 'candidate_hours', 'other_hours'):
                if key in changes:
                    value = changes[key]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in (6, 12, 24, 48):
                        raise PanelError('检测间隔需为 6、12、24 或 48 小时。')
                    values[key] = value
            if 'recommendation' in changes:
                values['recommendation'] = normalize_options(changes['recommendation'])
            tmp = self.settings_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(values, ensure_ascii=False), encoding='utf-8')
            tmp.replace(self.settings_path)
            self.settings = values
        self.wake.set()

    def enqueue(self, profile_id, node_id=None):
        nodes = self.subscriptions.nodes(profile_id)
        if node_id:
            nodes = [n for n in nodes if n['id'] == node_id]
        if not nodes:
            raise PanelError('节点不存在，请刷新订阅。')
        with self.lock:
            existing = set(self.queue) | ({self.active['id']} if self.active else set())
            for node in nodes:
                if not node['unsupported'] and node['id'] not in existing:
                    self.queue.append(node['id'])
                    existing.add(node['id'])
        self.wake.set()

    def refresh(self, profile_id):
        with self.lock:
            if profile_id not in {p['id'] for p in self.subscriptions.public()}:
                raise PanelError('订阅不存在。')
            if profile_id not in self.refresh_queue:
                self.refresh_queue.append(profile_id)
        self.wake.set()

    def state(self, profile_id=None):
        profiles = self.subscriptions.public()
        if not profile_id or profile_id not in {p['id'] for p in profiles}:
            profile_id = next((p['id'] for p in profiles if p['enabled'] and p['current']), None) or next(
                (p['id'] for p in profiles if p['enabled']), profiles[0]['id'] if profiles else None)
        nodes = self.subscriptions.nodes(profile_id) if profile_id else []
        latest, attempts, counts = self.store.snapshot()
        public = []
        for node in nodes:
            last = attempts.get(node['id'])
            changed = bool(last and last.get('fingerprint') != node['fingerprint'])
            public.append({k: node[k] for k in ('id', 'name', 'type', 'unsupported')} |
                          {'latest': None if changed else latest.get(node['id']),
                           'last_attempt': None if changed else last, 'config_changed': changed,
                           'history_count': counts.get(node['id'], 0)})
        histories = self.store.histories(n['id'] for n in public if not n['config_changed'])
        recommendations = rank_nodes(public, histories, options=self.settings['recommendation'])
        with self.lock:
            return {'version': '0.1.0', 'profiles': profiles, 'profile_id': profile_id, 'nodes': public,
                    'settings': dict(self.settings), 'recommendations': recommendations,
                    'activity': {'active_id': self.active['id'] if self.active else None,
                                 'active_name': self.active['name'] if self.active else None,
                                 'queued': list(self.queue), 'updating': self.updating,
                                 'stage': self.detector.progress, 'finished': self.finished,
                                 'message': self.message, 'cooldown_until': self.cooldown_until,
                                 'interface': self.network.value}}

    def step(self):
        now = time.time()
        with self.lock:
            manual = self.queue.popleft() if self.queue else None
            refresh = self.refresh_queue.popleft() if self.refresh_queue and not manual else None
            paused = self.settings['paused']
        profiles = self.subscriptions.public()
        if not manual and not refresh and not paused:
            refresh = next((p['id'] for p in profiles if p['enabled'] and p['mode'] != 'file'
                            and p['next_update'] <= now), None)
        if refresh:
            self.updating = refresh
            try:
                self.subscriptions.refresh(refresh, self.settings['update_hours'])
            finally:
                self.updating = None
            return True
        if now < self.cooldown_until:
            if manual:
                with self.lock:
                    self.queue.appendleft(manual)
            return False
        if self.cooldown_until:
            self.cooldown_until, self.message = 0, ''
        all_nodes = self.subscriptions.nodes(enabled_only=not bool(manual))
        node = next((n for n in all_nodes if n['id'] == manual), None) if manual else None
        if node is None and not manual and not paused:
            _, attempts, _ = self.store.snapshot()
            candidates = set()
            for profile in profiles:
                if profile['enabled']:
                    candidates.update(i['id'] for i in self.state(profile['id'])['recommendations']['items'])
            due = [n for n in all_nodes if is_due(n, attempts.get(n['id']), now, candidates, self.settings)]
            due.sort(key=lambda n: (n['id'] not in candidates, timestamp(attempts.get(n['id'], {}).get('checked_at'))))
            node = due[0] if due else None
        if node is None:
            return False
        try:
            self.detector.interface = self.network.interface()
        except PanelError as error:
            self.message, self.cooldown_until = str(error), now + 60
            if manual:
                with self.lock:
                    self.queue.appendleft(manual)
            return False
        with self.lock:
            self.active, self.message = node, ''
        try:
            record = self.detector.check(node)
            record['fingerprint'] = node['fingerprint']
            self.store.add(node, record)
            self.finished += 1
            if record.get('service_blocked'):
                self.cooldown_until = time.time() + 1800
                self.message = 'IPPure 限制了查询，30 分钟后重试。' if record.get('block_kind') == 'rate_limit' else 'IPPure 暂未允许查询，30 分钟后重试；连通结果已保存。'
                self.schedule_path.write_text(json.dumps({'cooldown_until': self.cooldown_until,
                                                         'message': self.message}, ensure_ascii=False), encoding='utf-8')
        finally:
            self.active = None
        return True

    def run(self):
        scan_at = time.time() + 60
        while not self.stop_event.is_set():
            try:
                if time.time() >= scan_at:
                    self.subscriptions.scan()
                    scan_at = time.time() + 60
                worked = self.step()
            except Exception:
                # Never expose URLs or credentials through exception text.
                self.message = '本轮任务未完成，已保存的结果不受影响；稍后重试。'
                self.cooldown_until = time.time() + 60
                worked = False
            self.wake.wait(3 if worked else 5)
            self.wake.clear()

    def close(self):
        self.stop_event.set()
        self.wake.set()
