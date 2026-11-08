"""One deterministic page query; challenges continue in the user's browser."""
import logging
import threading

from catalog import PanelError
from ping0 import query_ping0_auto


class Ping0Runner:
    def __init__(self, bridge, opener, query=None):
        self.bridge = bridge
        self.opener = opener
        self.query = query or query_ping0_auto
        self.lock = threading.Lock()
        self.workers = {}
        self.callback_port = None

    def start(self, node_id, profile_id, record):
        with self.lock:
            for job in self.bridge.active(profile_id):
                if job['node_id'] == node_id and job['ip'] == record['ip']:
                    return dict(job, checked_at=record['checked_at'])
            key = self.bridge.create(node_id, profile_id, record, status='checking')
            thread = threading.Thread(target=self._run, args=(key, record['ip']), daemon=True,
                                      name='ping0-page-query')
            self.workers[key] = thread
            thread.start()
        return dict(job_id=key, ip=record['ip'], checked_at=record['checked_at'], status='checking')

    def busy(self):
        with self.lock:
            return bool(self.workers)

    def open_browser(self, key):
        state = self.bridge.snapshot(key)
        if state['status'] != 'waiting':
            raise PanelError('这次补查不在等待验证，请刷新查看结果。')
        if not isinstance(self.callback_port, int) or not 1024 <= self.callback_port <= 65535:
            raise PanelError('回填服务尚未就绪，请从客户端重新补测。')
        url = f"https://ping0.cc/ip/{state['ip']}#node-quality={key}&port={self.callback_port}"
        try:
            self.opener(url)
        except OSError:
            self.bridge.fail(key, '浏览器未能打开，请检查默认浏览器设置后重试。')
            raise PanelError('浏览器未能打开，请检查默认浏览器设置。') from None
        return dict(job_id=key, ip=state['ip'], status='waiting')

    def _run(self, key, ip):
        try:
            result = self.query(ip)
            if result.get('status') == 'ok':
                self.bridge.receive(dict(job_id=key, ip=result.get('ip'), score=result.get('score'),
                    label=result.get('label'), page_url=f'https://ping0.cc/ip/{ip}'), source='automatic_page')
            elif result.get('block_kind') == 'challenge':
                self.bridge.require_browser(key)
                self.open_browser(key)
            else:
                self.bridge.fail(key, result.get('error') or 'Ping0 未返回有效结果，请稍后重试。')
        except PanelError as error:
            self.bridge.fail(key, str(error))
        except Exception:
            logging.exception('Ping0 automatic query or save failed')
            self.bridge.fail(key, 'Ping0 查询或保存失败，上次成功结果已保留，请稍后重试。')
        finally:
            with self.lock:
                self.workers.pop(key, None)
