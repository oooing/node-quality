"""Persistent, sequential background scheduling; no API for switching user proxies."""
from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time

from catalog import PanelError
from clash_control import ClashControl
from detector import Detector
from network import Network
from recommendations import rank_nodes, normalize_options, assess_node
from store import Store
from subscriptions import Subscriptions
from ping0_bridge import Ping0Bridge
from ping0_runner import Ping0Runner

CHECK_HOURS = 24
UPDATE_HOURS = 24
DEFAULTS = {'paused': False, 'recommendation': {'max_risk': 30, 'regions': []}}


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
    return now - timestamp(attempt['checked_at']) >= CHECK_HOURS * 3600


def detection_progress(nodes, attempts, now, candidate_ids, settings, pending=()):
    """Current subscription coverage, using the same freshness rules as the scheduler.

    Completed means attempted (including failures), not necessarily usable. A
    manual recheck is pending even when its previous result is still fresh.
    """
    eligible = [node for node in nodes if not node.get('unsupported')]
    completed = [attempts[node['id']] for node in eligible
                 if node['id'] not in pending and not is_due(
                     node, attempts.get(node['id']), now, candidate_ids, settings)]
    return {'total': len(eligible), 'completed': len(completed),
            'remaining': len(eligible) - len(completed),
            'failed': sum(row['status'] != 'ok' for row in completed),
            'skipped': len(nodes) - len(eligible)}


class Service:
    def __init__(self, directory, core, roots=None, start=True, detector=None, network=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.directory / 'settings.json'
        self.settings = json.loads(json.dumps(DEFAULTS))
        if self.settings_path.exists():
            saved = json.loads(self.settings_path.read_text(encoding='utf-8'))
            self.settings['paused'] = saved.get('paused', False)
            self.settings['recommendation'] = normalize_options(saved.get('recommendation'))
        self.subscriptions = Subscriptions(self.directory, roots)
        self.store = Store(self.directory / 'history.sqlite3')
        self.control = ClashControl(self.subscriptions)
        self.ping0_bridge = Ping0Bridge(self.store)
        self.ping0_runner = Ping0Runner(self.ping0_bridge, lambda url: os.startfile(url))
        self.detector = detector or Detector(core, self.directory / 'runtime')
        self.network = network or Network()
        self.lock = threading.RLock()
        self.queue = deque()
        self.latency_ids = set()
        self.active_kind = None
        self.refresh_queue = deque()
        self.stop_event, self.wake = threading.Event(), threading.Event()
        self.active, self.updating = None, None
        self.active_started = None
        self.next_check_at = 0
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
            if 'recommendation' in changes:
                values['recommendation'] = normalize_options(changes['recommendation'])
            tmp = self.settings_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(values, ensure_ascii=False), encoding='utf-8')
            tmp.replace(self.settings_path)
            self.settings = values
        self.wake.set()

    def enqueue(self, profile_id, node_id=None, latency_only=False):
        nodes = self.subscriptions.nodes(profile_id)
        if node_id:
            nodes = [n for n in nodes if n['id'] == node_id]
        if not nodes:
            raise PanelError('线路不存在，请刷新列表。')
        with self.lock:
            existing = set(self.queue) | ({self.active['id']} if self.active else set())
            for node in nodes:
                if not node['unsupported'] and node['id'] not in existing:
                    self.queue.append(node['id'])
                    existing.add(node['id'])
                    if latency_only:
                        self.latency_ids.add(node['id'])
                elif not latency_only:
                    self.latency_ids.discard(node['id'])
        self.wake.set()

    def favorite(self, node_id, saved):
        if not isinstance(saved, bool):
            raise PanelError('收藏状态无效。')
        node = next((n for n in self.subscriptions.nodes() if n['id'] == node_id), None)
        if not node:
            if not saved:
                self.store.set_favorite({'id':node_id}, False)
                return
            raise PanelError('线路已不在列表中，请刷新。')
        profile = next(p for p in self.subscriptions.public() if p['id'] == node['profile_id'])
        self.store.set_favorite(node | {'profile_name':profile['name'],'client':profile.get('origin','其他来源')}, saved)

    def refresh(self, profile_id):
        self.subscriptions.scan()
        with self.lock:
            if profile_id not in {p['id'] for p in self.subscriptions.public()}:
                raise PanelError('这个列表已在 Clash 中删除，请选择其他列表。')
            if profile_id not in self.refresh_queue:
                self.refresh_queue.append(profile_id)
        self.wake.set()

    def open_ping0(self, profile_id, node_id):
        if not all(isinstance(v, str) and v for v in (profile_id, node_id)):
            raise PanelError('请指定列表和线路。')
        node = next((n for n in self.subscriptions.nodes(profile_id) if n['id'] == node_id), None)
        if node is None:
            raise PanelError('线路已不在当前列表中，请刷新。')
        latest, _, _ = self.store.snapshot()
        record = latest.get(node_id) or {}
        if record.get('status') != 'ok' or record.get('fingerprint') != node['fingerprint']:
            raise PanelError('请先检测这条线路，再进行补充检测。')
        return self.ping0_runner.start(node_id, profile_id, record)

    def state(self, profile_id=None):
        profiles = self.subscriptions.public()
        if not profile_id or profile_id not in {p['id'] for p in profiles}:
            profile_id = next((p['id'] for p in profiles if p['enabled'] and p['current']), None) or next(
                (p['id'] for p in profiles if p['enabled']), profiles[0]['id'] if profiles else None)
        all_nodes = self.subscriptions.nodes()
        nodes = [n for n in all_nodes if n['profile_id'] == profile_id]
        favorites,latencies,alerts = self.store.extras()
        selected = {n['id'] for n in nodes} | set(favorites)
        latest, attempts, counts = self.store.snapshot()
        histories = self.store.histories(selected)
        public = []
        for node in all_nodes:
            if node['id'] not in selected:
                continue
            last = attempts.get(node['id'])
            changed = bool(last and last.get('fingerprint') != node['fingerprint'])
            success = latest.get(node['id'])
            if success and success.get('fingerprint') != node['fingerprint']:
                success = None
            histories[node['id']] = [r for r in histories[node['id']]
                                     if r.get('fingerprint') == node['fingerprint']]
            observed = next((r.get('observed_ip') or r.get('ip') for r in histories[node['id']]
                             if r.get('observed_ip') or r.get('status') == 'ok'), None)
            public.append({k: node[k] for k in ('id', 'name', 'type', 'unsupported','profile_id')} |
                          {'latest': None if changed else success, 'observed_ip': observed,
                           'last_attempt': None if changed else last, 'config_changed': changed,
                           'history_count': counts.get(node['id'], 0), 'favorite':node['id'] in favorites,
                           'latency':latencies.get(node['id']) if latencies.get(node['id'],{}).get('fingerprint') == node['fingerprint'] else None,
                           'ip_alert':alerts.get(node['id'])})
            assessment = assess_node(public[-1])
            public[-1]['rating_state'] = assessment['state']
        by_id = {n['id']:n for n in public}
        favorite_nodes = [by_id.get(key,meta | {'missing':True,'favorite':True,'unsupported':'线路已移除','ip_alert':alerts.get(key)}) |
                          {'profile_name':next((p['name'] for p in profiles if p['id']==meta['profile_id']),meta['profile_name']),
                           'client':meta['client']} for key,meta in favorites.items()]
        public = [n for n in public if n['profile_id'] == profile_id]
        recommendations = rank_nodes(public, histories, options=self.settings['recommendation'])
        with self.lock:
            pending = (set(self.queue) - self.latency_ids) | ({self.active['id']} if self.active and self.active_kind != 'latency' else set())
            progress = detection_progress(nodes, attempts, time.time(),
                                          {row['id'] for row in recommendations['items']}, self.settings, pending)
            return {'version': '0.2.9', 'profiles': profiles, 'profile_id': profile_id, 'nodes': public,
                    'settings': dict(self.settings), 'recommendations': recommendations,
                    'favorites':favorite_nodes,
                    'ping0_jobs': self.ping0_bridge.recent(profile_id),
                    'activity': {'active_id': self.active['id'] if self.active else None,
                                 'active_name': self.active['name'] if self.active else None,
                                 'active_kind': self.active_kind,
                                 'active_profile_id': self.active['profile_id'] if self.active else None,
                                 'elapsed_seconds': round(time.monotonic() - self.active_started, 1)
                                 if self.active_started is not None else 0,
                                 'progress': progress,
                                 'wait_seconds': max(0, self.next_check_at - time.time()),
                                 'queued': list(self.queue), 'updating': self.updating,
                                 'stage': self.detector.progress, 'finished': self.finished,
                                 'message': self.message, 'cooldown_until': self.cooldown_until,
                                 'interface': self.network.value}}

    def step(self):
        now = time.time()
        with self.lock:
            manual = self.queue.popleft() if self.queue else None
            latency_only = manual in self.latency_ids
            refresh = self.refresh_queue.popleft() if self.refresh_queue and not manual else None
            paused = self.settings['paused']
        profiles = self.subscriptions.public()
        if not manual and not refresh and not paused:
            refresh = next((p['id'] for p in profiles if p['enabled'] and p['mode'] != 'file'
                            and p['next_update'] <= now), None)
        if refresh:
            self.updating = refresh
            try:
                self.subscriptions.refresh(refresh, UPDATE_HOURS)
            finally:
                self.updating = None
            return True
        if now < self.cooldown_until and not latency_only:
            if manual:
                with self.lock:
                    self.queue.appendleft(manual)
            return False
        if self.cooldown_until and not latency_only:
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
        with self.lock:
            self.active, self.message = node, ''
            self.active_kind = 'latency' if latency_only else 'full'
            self.latency_ids.discard(manual)
            self.active_started = time.monotonic()
            self.detector.progress = {'node_id': node['id'], 'stage': 'network'}
        try:
            try:
                self.detector.interface = self.network.interface()
                self.detector.interface_index = (self.network.value or {}).get('index')
            except PanelError as error:
                self.message, self.cooldown_until = str(error), time.time() + 60
                if manual:
                    with self.lock:
                        self.queue.appendleft(manual)
                        if latency_only:
                            self.latency_ids.add(manual)
                return False
            record = self.detector.check(node, latency_only=True) if latency_only else self.detector.check(node)
            record['fingerprint'] = node['fingerprint']
            if latency_only:
                self.store.add_latency(node, record)
            else:
                self.store.add(node, record)
                self.finished += 1
            if record.get('service_blocked'):
                self.cooldown_until = time.time() + 1800
                self.message = 'IPPure 暂时限制查询，30 分钟后自动重试。' if record.get('block_kind') == 'rate_limit' else 'IPPure 暂未允许查询，30 分钟后重试；连通结果已保存。'
                self.schedule_path.write_text(json.dumps({'cooldown_until': self.cooldown_until,
                                                         'message': self.message}, ensure_ascii=False), encoding='utf-8')
        finally:
            with self.lock:
                self.active = self.active_started = None
                self.active_kind = None
                self.detector.progress = None
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
            self.next_check_at = time.time() + (3 if worked else 5)
            self.wake.wait(3 if worked else 5)
            self.wake.clear()
            self.next_check_at = 0

    def close(self):
        self.stop_event.set()
        self.wake.set()
