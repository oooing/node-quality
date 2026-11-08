"""Correlate a user-opened Ping0 page with its node and save visible results."""
from datetime import datetime
import ipaddress
import math
import re
import secrets
import threading
import time

from catalog import PanelError
from ping0 import SHANGHAI


class Ping0Bridge:
    def __init__(self, store, timeout_seconds=1800):
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.jobs = {}
        self.lock = threading.Lock()

    def create(self, node_id, profile_id, record, status='waiting'):
        ip = str(ipaddress.IPv4Address(record['ip']))
        with self.lock:
            now = time.monotonic()
            self.jobs = {key: job for key, job in self.jobs.items() if now < job['deadline']}
            key = secrets.token_urlsafe(24)
            self.jobs[key] = dict(status=status, ip=ip, node_id=node_id, profile_id=profile_id,
                                  based_on_checked_at=record['checked_at'],
                                  deadline=now + self.timeout_seconds)
        return key

    def _job(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}', key) or key not in self.jobs:
            raise PanelError('找不到这次检测，请回到应用重新发起。')
        job = self.jobs[key]
        if job['status'] in ('checking', 'waiting') and time.monotonic() >= job['deadline']:
            job.update(status='expired', error='等待验证已超时，请重新发起补充检测。')
        return job

    def snapshot(self, key):
        with self.lock:
            job = self._job(key)
            return {name: job[name] for name in ('status', 'ip', 'applied_to_current', 'error', 'message') if name in job}

    def active(self, profile_id=None):
        with self.lock:
            result = []
            for key in self.jobs:
                job = self._job(key)
                if job['status'] in ('checking', 'waiting') and (profile_id is None or job['profile_id'] == profile_id):
                    result.append(dict(job_id=key, **{name: job[name] for name in
                        ('node_id', 'profile_id', 'ip', 'status', 'message') if name in job}))
            return result

    def recent(self, profile_id):
        with self.lock:
            result = []
            for key in self.jobs:
                job = self._job(key)
                if job['profile_id'] == profile_id:
                    result.append(dict(job_id=key, **{name: job[name] for name in
                        ('node_id', 'ip', 'status', 'message', 'error', 'applied_to_current') if name in job}))
            return result

    def fail(self, key, message):
        with self.lock:
            job = self._job(key)
            if job['status'] in ('checking', 'waiting'):
                job.update(status='error', error=message)

    def require_browser(self, key):
        with self.lock:
            job = self._job(key)
            if job['status'] != 'checking':
                raise PanelError('这次补查已结束，请重新发起。')
            job.update(status='waiting', message='Ping0 需要验证，请在浏览器完成；结果会自动保存。')

    def failed_open(self, key):
        with self.lock:
            self._job(key).update(status='error', error='浏览器未能打开，请检查默认浏览器设置。')

    def receive(self, payload, source='browser_page'):
        with self.lock:
            job = self._job(payload.get('job_id'))
            if job['status'] == 'completed':
                return job['result']
            expected_status = 'checking' if source == 'automatic_page' else 'waiting'
            if job['status'] != expected_status:
                raise PanelError(job.get('error') or '这次补查已结束，请从面板重新打开。')
            ip = payload.get('ip')
            score = payload.get('score')
            label = payload.get('label')
            expected_url = f"https://ping0.cc/ip/{job['ip']}"
            if ip != job['ip'] or payload.get('page_url') != expected_url:
                raise PanelError('网页显示的 IP 与本次查询不一致，结果未保存。')
            if (isinstance(score, bool) or not isinstance(score, (int, float))
                    or not math.isfinite(score) or not 0 <= score <= 100):
                raise PanelError('网页风险值无效，未保存结果。')
            if not isinstance(label, str) or not label.strip() or len(label) > 120:
                raise PanelError('网页风险说明无效，未保存结果。')
            record = dict(status='ok', ip=ip, score=score, label=label.strip(),
                          checked_at=datetime.now(SHANGHAI).isoformat(timespec='milliseconds'),
                          source=source, source_url=expected_url)
            result = self.store.add_ping0(job['node_id'], ip, job['based_on_checked_at'],
                                          record, payload['job_id'])
            job.update(status='completed', applied_to_current=result['applied_to_current'], result=result)
            return result
