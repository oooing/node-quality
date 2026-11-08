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
from service import Service, is_due, detection_progress, DEFAULTS
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

    def test_client_sources_keep_same_named_subscriptions_distinct(self):
        roots = [self.root / 'io.github.clash-verge.clash-verge',
                 self.root / 'io.github.clash-verge-rev.clash-verge-rev']
        for root in roots:
            root.mkdir()
            (root / 'profiles.yaml').write_text(yaml.safe_dump({'items': [
                {'uid': 'same-uid', 'type': 'remote', 'name': 'Clash_1793077309.yaml',
                 'file': 'one.yaml', 'url': 'https://example.invalid/?token=secret'}]}), encoding='utf-8')
        rows = discover(roots)
        self.assertEqual([r['origin'] for r in rows], ['Clash Verge', 'Clash Verge Rev'])
        self.assertEqual([r['name'] for r in rows], ['Clash_1793077309.yaml'] * 2)
        self.assertNotEqual(rows[0]['id'], rows[1]['id'])
        self.assertEqual([r['id'] for r in rows], [r['id'] for r in discover(roots)])

    def test_source_rename_keeps_history_nodes_and_schedule(self):
        self.service.step()
        before = self.subs.nodes(self.id)
        history = self.service.store.history(before[0]['id'])
        original = self.subs.items[self.id].copy()
        path = self.client / 'profiles.yaml'
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        data['items'][0]['name'] = 'Clash_1793077309.yaml'
        path.write_text(yaml.safe_dump(data), encoding='utf-8')
        self.subs.scan()
        after = self.subs.nodes(self.id)
        self.assertEqual([(n['id'], n['fingerprint']) for n in before],
                         [(n['id'], n['fingerprint']) for n in after])
        self.assertTrue(all(n['profile_name'] == 'Clash_1793077309.yaml' for n in after))
        self.assertEqual(self.service.store.history(before[0]['id']), history)
        for key in ('enabled', 'next_update', 'last_update'):
            self.assertEqual(self.subs.items[self.id][key], original[key])

    def test_deleted_source_leaves_active_list_and_jobs_but_keeps_history(self):
        self.service.step()
        node = self.subs.nodes(self.id)[0]
        history = self.service.store.history(node['id'])
        original = (self.client / 'profiles.yaml').read_text(encoding='utf-8')
        imported = self.subs.add('Manual', text=yaml.safe_dump({'proxies': [proxy('Manual')]}))
        data = yaml.safe_load(original)
        data['items'] = [p for p in data['items'] if p['uid'] != 'one']
        data['current'] = 'two'
        (self.client / 'profiles.yaml').write_text(yaml.safe_dump(data), encoding='utf-8')
        self.service.refresh_queue.append(self.id)
        self.subs.scan()
        self.assertNotIn(self.id, [p['id'] for p in self.subs.public()])
        self.assertIn(imported, [p['id'] for p in self.subs.public()])
        self.assertEqual(self.subs.nodes(self.id), [])
        self.assertNotEqual(self.service.state(self.id)['profile_id'], self.id)
        with patch('subscriptions.fetch_yaml') as fetch:
            self.service.step()
            fetch.assert_not_called()
        self.assertEqual(self.service.store.history(node['id']), history)
        reopened = Subscriptions(self.root / 'data', roots=[self.client])
        self.assertNotIn(self.id, [p['id'] for p in reopened.public()])
        (self.client / 'profiles.yaml').write_text(original, encoding='utf-8')
        self.subs.scan()
        self.assertIn(self.id, [p['id'] for p in self.subs.public()])
        self.assertEqual(self.service.store.history(node['id']), history)

    def test_unreadable_list_or_other_directory_does_not_hide_sources(self):
        original = (self.client / 'profiles.yaml').read_text(encoding='utf-8')
        before = self.subs.public()
        for content in ('', 'items: [', 'items: null'):
            (self.client / 'profiles.yaml').write_text(content, encoding='utf-8')
            self.subs.scan()
            self.assertEqual(self.subs.public(), before)
        (self.client / 'profiles.yaml').write_text(original, encoding='utf-8')
        other = self.root / 'other-client'
        other.mkdir()
        (other / 'profiles.yaml').write_text('items: []', encoding='utf-8')
        self.subs.scan(str(other))
        self.assertEqual(self.subs.public(), before)
        (self.client / 'profiles.yaml').write_text('items: []', encoding='utf-8')
        with self.assertRaisesRegex(PanelError, '列表已在 Clash 中删除'):
            self.service.refresh(self.id)
        self.assertEqual(self.subs.public(), [])

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

    def test_progress_records_failures_and_survives_relaunch(self):
        self.assertEqual(self.service.state(self.id)['activity']['progress'],
                         {'total': 2, 'completed': 0, 'remaining': 2, 'failed': 0, 'skipped': 0})
        self.service.step()
        with patch.object(self.detector, 'check', return_value={
                'status': 'error', 'checked_at': datetime.now(timezone.utc).isoformat(), 'error': 'timeout'}):
            self.service.step()
        expected = {'total': 2, 'completed': 2, 'remaining': 0, 'failed': 1, 'skipped': 0}
        self.assertEqual(self.service.state(self.id)['activity']['progress'], expected)
        second = Service(self.root / 'data', Path('unused.exe'), roots=[self.client], start=False,
                         detector=self.detector, network=FakeNetwork())
        self.assertEqual(second.state(self.id)['activity']['progress'], expected)

    def test_progress_manual_recheck_and_subscription_scope(self):
        self.service.step()
        self.service.step()
        node = self.subs.nodes(self.id)[0]
        self.service.enqueue(self.id, node['id'])
        progress = self.service.state(self.id)['activity']['progress']
        self.assertEqual((progress['completed'], progress['remaining']), (1, 1))
        other = next(p['id'] for p in self.subs.public() if p['id'] != self.id)
        self.assertEqual(self.service.state(other)['activity']['progress']['completed'], 0)
        self.service.step()
        self.assertEqual(self.service.state(self.id)['activity']['progress']['completed'], 2)

    def test_progress_expiry_config_change_and_unsupported(self):
        nodes = self.subs.nodes(self.id)
        old = datetime.now(timezone.utc) - timedelta(hours=12)
        attempts = {n['id']: {'status': 'ok', 'checked_at': old.isoformat(), 'fingerprint': n['fingerprint']} for n in nodes}
        unsupported = dict(nodes[0], id='unsupported', unsupported='unsupported protocol')
        progress = detection_progress(nodes + [unsupported], attempts, time.time(), {nodes[0]['id']}, DEFAULTS)
        self.assertEqual(progress, {'total': 2, 'completed': 2, 'remaining': 0, 'failed': 0, 'skipped': 1})
        nodes[1]['fingerprint'] = 'changed'
        self.assertEqual(detection_progress(nodes, attempts, time.time(), {nodes[0]['id']}, DEFAULTS)['completed'], 1)

    def test_active_progress_covers_network_setup_and_check(self):
        def network():
            activity = self.service.state(self.id)['activity']
            self.assertEqual(activity['stage']['stage'], 'network')
            self.assertEqual(activity['active_profile_id'], self.id)
            self.assertIsNotNone(activity['active_id'])
            self.assertGreaterEqual(activity['elapsed_seconds'], 0)
            return 'Ethernet'
        with patch.object(self.service.network, 'interface', side_effect=network):
            self.service.step()
        self.assertIsNone(self.service.state(self.id)['activity']['active_id'])
        self.assertIsNone(self.service.detector.progress)

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
        self.service.store.add(changed, {'status': 'error', 'checked_at': datetime.now(timezone.utc).isoformat(),
            'fingerprint': changed['fingerprint'], 'connectivity': {'status': 'ok'}, 'error': '评分查询失败'})
        state = self.service.state(self.id)
        self.assertFalse(state['recommendations']['items'])
        self.assertIsNone(next(n for n in state['nodes'] if n['id'] == changed['id'])['latest'])

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
        activity = self.service.state(self.id)['activity']
        self.assertIsNone(activity['active_id'])
        self.assertIsNone(activity['stage'])
        self.assertEqual(activity['progress']['remaining'], 2)

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

    def test_http_auth_and_switch_requires_explicit_target(self):
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
            self.assertEqual(session.post(base+'/api/switch',json={},headers=headers).status_code,400)
            headers['Origin']='https://unrelated.invalid'
            self.assertEqual(session.post(base+'/api/check',json={'profile_id':self.id},headers=headers).status_code,403)
        finally:
            session.close();server.shutdown();server.server_close();thread.join()


if __name__=='__main__': unittest.main()
