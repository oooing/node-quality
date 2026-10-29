import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from catalog import PanelError
from subscriptions import Subscriptions, discover, extract_nodes
from service import Service, is_due, DEFAULTS
from main import handler
from http.server import ThreadingHTTPServer
import threading
import requests
import yaml


def proxy(name='香港 01', password='secret'):
    return {'name': name, 'server': 'node.invalid', 'port': 443, 'type': 'trojan', 'password': password}


class FakeNetwork:
    value = {'name': 'Ethernet'}
    def interface(self): return 'Ethernet'


class FakeDetector:
    progress = None
    def __init__(self): self.calls = []
    def check(self, node):
        self.calls.append(node['id'])
        return {'status': 'ok', 'checked_at': datetime.now(timezone.utc).isoformat(), 'route_verified': True,
                'ip': '1.2.3.4', 'score': 10, 'connectivity': {'status': 'ok', 'delay_ms': 45}}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = self.root / 'clash'
        (self.client / 'profiles').mkdir(parents=True)
        (self.client / 'profiles.yaml').write_text(yaml.safe_dump({'current': 'one', 'items': [
            {'uid': 'one', 'type': 'remote', 'name': '第一份', 'file': 'one.yaml', 'url': 'https://example.invalid/a?token=secret'},
            {'uid': 'two', 'type': 'local', 'name': '第二份', 'file': 'two.yaml'},
            {'uid': 'script', 'type': 'script', 'file': 'script.js'}]}), encoding='utf-8')
        for key in ('one', 'two'):
            (self.client / 'profiles' / (key + '.yaml')).write_text(yaml.safe_dump({'proxies': [proxy(), proxy('日本 02')]}), encoding='utf-8')
        self.detector = FakeDetector()
        self.service = Service(self.root / 'data', Path('unused.exe'), roots=[self.client], start=False,
                               detector=self.detector, network=FakeNetwork())
        self.subs = self.service.subscriptions
        self.id = next(p['id'] for p in self.subs.public() if p['current'])
        # Most tests target detection; avoid a live subscription fetch.
        self.subs.items[self.id]['next_update'] = time.time() + 99999
        self.subs.save()

    def tearDown(self): self.temp.cleanup()

    def test_discovery_current_only_enabled_no_script(self):
        rows = self.subs.public()
        self.assertEqual(len(rows), 2)
        self.assertEqual([x['id'] for x in rows if x['enabled']], [self.id])
        self.assertNotIn('secret', json.dumps(rows))
        self.assertNotIn('url', rows[0])

    def test_source_unchanged_after_refresh(self):
        before = {p: p.read_bytes() for p in self.client.rglob('*') if p.is_file()}
        with patch('subscriptions.fetch_yaml', return_value={'proxies': [proxy('美国 03')]}):
            self.subs.refresh(self.id)
        self.assertEqual(len(self.subs.nodes(self.id)), 1)
        self.assertGreater(self.subs.items[self.id]['last_update'], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.client.rglob('*') if p.is_file()})

    def test_refresh_failure_keeps_nodes(self):
        before = self.subs.nodes(self.id)
        with patch('subscriptions.fetch_yaml', side_effect=PanelError('下载超时')):
            self.subs.refresh(self.id)
        self.assertEqual(before, self.subs.nodes(self.id))
        self.assertEqual(self.subs.items[self.id]['error'], '下载超时')

    def test_automatic_initial_check_and_resume(self):
        self.assertTrue(self.service.step())
        self.assertEqual(len(self.detector.calls), 1)
        second = Service(self.root / 'data', Path('unused.exe'), roots=[self.client], start=False,
                         detector=self.detector, network=FakeNetwork())
        self.assertTrue(second.step())
        self.assertEqual(len(set(self.detector.calls)), 2)
        self.assertFalse(second.step())

    def test_pause_blocks_auto_but_manual_queue_works(self):
        self.service.save_settings({'paused': True})
        self.assertFalse(self.service.step())
        self.service.enqueue(self.id)
        self.service.enqueue(self.id)
        self.assertEqual(len(self.service.queue), 2)
        self.assertTrue(self.service.step())
        self.assertEqual(len(self.service.queue), 1)

    def test_rate_limit_survives_relaunch(self):
        with patch.object(self.detector, 'check', return_value={'status': 'error', 'checked_at': datetime.now(timezone.utc).isoformat(),
                          'error': 'rate limited', 'service_blocked': True, 'block_kind': 'rate_limit'}):
            self.service.step()
        second = Service(self.root/'data', Path('unused.exe'), roots=[self.client], start=False,
                         detector=self.detector, network=FakeNetwork())
        self.assertGreater(second.cooldown_until, time.time())
        self.assertFalse(second.step())

    def test_changed_password_due_and_not_recommended(self):
        self.service.step()
        node = self.subs.nodes(self.id)[0]
        self.assertTrue(self.service.state(self.id)['recommendations']['items'])
        with patch('subscriptions.fetch_yaml', return_value={'proxies': [proxy(password='changed'), proxy('日本 02')]}):
            self.subs.refresh(self.id)
        changed = self.subs.nodes(self.id)[0]
        self.assertEqual(node['id'], changed['id'])
        self.assertNotEqual(node['fingerprint'], changed['fingerprint'])
        self.assertFalse(self.service.state(self.id)['recommendations']['items'])
        self.assertTrue(is_due(changed, self.service.store.history(node['id'])[0], time.time(), set(), DEFAULTS))

    def test_rate_limit_stops_following_checks(self):
        with patch.object(self.detector, 'check', return_value={'status': 'error', 'checked_at': datetime.now(timezone.utc).isoformat(),
                          'error': 'rate limited', 'service_blocked': True, 'block_kind': 'rate_limit'}):
            self.service.step()
        self.assertGreater(self.service.cooldown_until, time.time())
        self.assertFalse(self.service.step())

    def test_no_network_does_not_mark_node_dead(self):
        with patch.object(self.service.network, 'interface', side_effect=PanelError('没有网络')):
            self.assertFalse(self.service.step())
        self.assertEqual(self.service.store.snapshot()[1], {})
        self.assertEqual(self.service.message, '没有网络')

    def test_settings_persist(self):
        self.service.save_settings({'paused': True, 'recommendation': {'max_risk': 20, 'regions': ['HK', 'US']}})
        new = Service(self.root/'data', Path('unused.exe'), roots=[self.client], start=False)
        self.assertTrue(new.settings['paused'])
        self.assertEqual(new.settings['recommendation']['regions'], ['HK', 'US'])

    def test_history_retains_ten_and_ip_change(self):
        node = self.subs.nodes(self.id)[0]
        for i in range(12):
            self.service.store.add(node, {'checked_at': (datetime.now(timezone.utc)+timedelta(seconds=i)).isoformat(),
                'status': 'ok', 'ip': '1.2.3.'+str(i+1), 'score': i, 'fingerprint': node['fingerprint']})
        history = self.service.store.history(node['id'])
        self.assertEqual(len(history), 10)
        self.assertTrue(history[0]['ip_changed'])
        self.assertEqual(history[0]['score_delta'], 1)

    def test_local_import_no_client_dependency(self):
        detached = Subscriptions(self.root/'detached', roots=[])
        key = detached.add('本地', text=yaml.safe_dump({'proxies': [proxy()]}))
        self.assertEqual(detached.nodes(key)[0]['name'], '香港 01')

    def test_provider_payload_supported(self):
        nodes = extract_nodes({'proxy-providers': {'p': {'type': 'inline', 'payload': [proxy()]}}}, {'id':'p','name':'p'})
        self.assertEqual(len(nodes), 1)

    def test_provider_failure_not_silent_empty(self):
        with self.assertRaises(PanelError):
            extract_nodes({'proxy-providers': {'p': {'type':'http','url':'https://example.invalid'}}}, {'id':'p','name':'p'})

    def test_removed_client_does_not_remove_import(self):
        self.subs.roots = []
        self.subs.scan()
        self.assertEqual(len(self.subs.nodes(self.id)), 2)

    def test_http_auth_and_no_switch_endpoint(self):
        ui = Path(__file__).resolve().parents[1] / 'ui'
        server = ThreadingHTTPServer(('127.0.0.1',0),handler(self.service, 'test-token', ui))
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        session=requests.Session();session.trust_env=False
        try:
            self.assertEqual(session.get(base+'/api/state').status_code,403)
            headers={'X-App-Token':'test-token'}
            result=session.get(base+'/api/state',headers=headers)
            self.assertEqual(result.status_code,200)
            self.assertNotIn('secret',result.text)
            self.assertEqual(session.post(base+'/api/switch',json={},headers=headers).status_code,404)
            headers['Origin']='https://unrelated.invalid'
            self.assertEqual(session.post(base+'/api/check',json={'profile_id':self.id},headers=headers).status_code,403)
        finally:
            session.close();server.shutdown();server.server_close();thread.join()


if __name__=='__main__': unittest.main()
