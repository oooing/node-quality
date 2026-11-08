"""Desktop handoff and switch integration, using an isolated fake Clash controller."""
import copy
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock
from urllib.parse import quote

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from catalog import PanelError
from clash_control import ClashControl
from official_selection import OfficialSelection, saved_selection
from main import handler
from service import Service
from test_service import FakeDetector, FakeNetwork


class Controller:
    def __init__(self):
        self.calls, self.mode, self.confirm = [], 'rule', True
        self.proxies = {'香港 01': {'type': 'Shadowsocks'}, '日本 02': {'type': 'Shadowsocks'},
            '主组 / AI': {'type': 'Selector', 'now': '香港 01', 'all': ['香港 01', '日本 02']},
            '自动': {'type': 'URLTest', 'now': '香港 01', 'all': ['香港 01', '日本 02']},
            '嵌套': {'type': 'Selector', 'now': '主组 / AI', 'all': ['主组 / AI']},
            'GLOBAL': {'type': 'Selector', 'now': '香港 01', 'all': ['香港 01', '日本 02']}}

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path == '/configs':
            return {'mode': self.mode, 'secret': 'private-secret'}
        if path == '/proxies':
            return {'proxies': copy.deepcopy(self.proxies)}
        name = next(name for name in self.proxies if path == '/proxies/' + quote(name, safe=''))
        if method == 'PUT':
            if self.confirm:
                self.proxies[name]['now'] = payload['name']
            return None
        return copy.deepcopy(self.proxies[name])


class OfficialUi(OfficialSelection):
    """Fixture for the external GUI; never invokes the user's application."""
    def __init__(self, controller):
        super().__init__(verify_timeout=.05)
        self.controller, self.calls, self.persist, self.failure = controller, [], True, None

    def _invoke(self, profile, group, node):
        self.calls.append((group, node))
        if self.failure:
            raise PanelError(self.failure)
        if self.controller.confirm:
            self.controller.proxies[group]['now'] = node
        if self.persist:
            path = Path(profile['source_root']) / 'profiles.yaml'
            record = yaml.safe_load(path.read_text(encoding='utf-8'))
            item = next(p for p in record['items'] if p['uid'] == profile['source_uid'])
            item['selected'] = [p for p in item.get('selected', []) if p['name'] != group] + [{'name': group, 'now': node}]
            path.write_text(yaml.safe_dump(record, allow_unicode=True), encoding='utf-8')


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clash = self.root / 'clash'
        (self.clash / 'profiles').mkdir(parents=True)
        self.config = {'proxies': [dict(name=name, type='ss', server='example.invalid', port=443,
            cipher='aes-128-gcm', password='private-password') for name in ('香港 01', '日本 02')],
            'proxy-groups': [{'name': '主组 / AI'}], 'secret': 'private-secret'}
        self.write_config()
        (self.clash / 'profiles' / 'one.yaml').write_text(yaml.safe_dump(self.config), encoding='utf-8')
        (self.clash / 'profiles.yaml').write_text(yaml.safe_dump({'current': 'one', 'items': [
            dict(uid='one', name='测试列表', type='local', file='one.yaml')]}), encoding='utf-8')
        self.service = Service(self.root / 'data', Path('unused.exe'), roots=[self.clash], start=False,
                               detector=FakeDetector(), network=FakeNetwork())
        self.profile = self.service.subscriptions.public()[0]['id']
        self.service.subscriptions.items[self.profile]['next_update'] = time.time() + 99999
        self.nodes = self.service.subscriptions.nodes(self.profile)
        self.controller = Controller()
        self.official = OfficialUi(self.controller)
        self.service.control = ClashControl(self.service.subscriptions, lambda _: self.controller, self.official)
        self.service.ping0_runner.query = Mock(return_value={'status': 'error', 'block_kind': 'challenge'})
        self.service.ping0_runner.opener = Mock()
        ui = Path(__file__).resolve().parents[1] / 'ui'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.service, 'test-token', ui))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.session = requests.Session()
        self.session.trust_env = False
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.auth = {'X-App-Token': 'test-token'}

    def tearDown(self):
        self.wait_ping0()
        self.session.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def write_config(self):
        (self.clash / 'clash-verge.yaml').write_text(yaml.safe_dump(self.config), encoding='utf-8')

    def wait_ping0(self):
        deadline = time.monotonic() + 3
        while self.service.ping0_runner.busy() and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(self.service.ping0_runner.busy())

    def post(self, path, data, headers=None):
        return self.session.post(self.base + path, json=data, headers=headers or self.auth, timeout=5)

    def record(self, ip='203.0.113.7'):
        node = self.nodes[0]
        return self.service.store.add(node, {'status': 'ok', 'ip': ip, 'score': 12,
            'checked_at': datetime.now(timezone.utc).isoformat(), 'fingerprint': node['fingerprint'], 'route_verified': True})

    def start_ping0(self):
        response = self.post('/api/ping0/open', {'profile_id': self.profile, 'node_id': self.nodes[0]['id']})
        self.assertEqual(response.status_code, 200, response.text)
        self.wait_ping0()
        return response.json()['job_id']

    def payload(self, job):
        return {'job_id': job, 'ip': '203.0.113.7', 'score': 0, 'label': '极度纯净',
                'page_url': 'https://ping0.cc/ip/203.0.113.7'}

    def test_only_explicit_switch_writes_named_selector_and_verifies(self):
        before = {p: p.read_bytes() for p in self.clash.rglob('*.yaml')}
        state = self.session.get(self.base + '/api/control?profile=' + self.profile, headers=self.auth).json()
        self.assertTrue(state['can_switch'])
        self.assertEqual(len(state['switchable_ids']), 2)  # ss <-> Shadowsocks alias
        self.assertNotIn('private-', json.dumps(state))
        self.assertTrue(all(call[0] == 'GET' for call in self.controller.calls))
        result = self.post('/api/switch', {'profile_id': self.profile, 'node_id': self.nodes[1]['id'], 'group': '主组 / AI'})
        self.assertTrue(result.json()['verified'])
        self.assertTrue(result.json()['persisted'])
        self.assertEqual(self.controller.proxies['主组 / AI']['now'], '日本 02')
        self.assertEqual(self.controller.proxies['GLOBAL']['now'], '香港 01')
        self.assertEqual(self.official.calls, [('主组 / AI', '日本 02')])
        self.assertTrue(all(c[0] == 'GET' for c in self.controller.calls))
        after = {p: p.read_bytes() for p in self.clash.rglob('*.yaml')}
        self.assertEqual([p.name for p in before if before[p] != after[p]], ['profiles.yaml'])
        self.assertEqual(saved_selection(self.service.subscriptions.items[self.profile], '主组 / AI'), '日本 02')

    def test_switch_without_durable_record_reports_partial_failure(self):
        self.official.persist = False
        with self.assertRaisesRegex(PanelError, '线路已换用，但未确认保存'):
            self.service.control.select(self.profile, self.nodes[1]['id'], '主组 / AI')
        self.assertEqual(self.controller.proxies['主组 / AI']['now'], '日本 02')
        self.assertTrue(all(c[0] == 'GET' for c in self.controller.calls))

    def test_ui_failure_never_falls_back_to_api_only_switch(self):
        self.official.failure = '未找到目标线路'
        with self.assertRaisesRegex(PanelError, '未找到目标线路'):
            self.service.control.select(self.profile, self.nodes[1]['id'], '主组 / AI')
        self.assertEqual(self.controller.proxies['主组 / AI']['now'], '香港 01')
        self.assertTrue(all(c[0] == 'GET' for c in self.controller.calls))

    def test_current_line_is_saved_once_then_skips_ui(self):
        for _ in range(2):
            result = self.service.control.select(self.profile, self.nodes[0]['id'], '主组 / AI')
            self.assertTrue(result['persisted'])
        self.assertEqual(self.official.calls, [('主组 / AI', '香港 01')])

    def test_concurrent_switch_is_rejected_before_any_action(self):
        with self.service.control.selection_lock:
            with self.assertRaisesRegex(PanelError, '正在换用并保存'):
                self.service.control.select(self.profile, self.nodes[1]['id'], '主组 / AI')
        self.assertEqual(self.official.calls, [])
        self.assertEqual(self.controller.calls, [])

    def test_mismatched_config_unlinked_import_and_wrong_profile_never_switch(self):
        self.config['proxies'][1]['password'] = 'changed'
        self.write_config()
        for profile, node in [(self.profile, self.nodes[1]['id']), ('absent', self.nodes[0]['id'])]:
            self.assertEqual(self.post('/api/switch', {'profile_id': profile, 'node_id': node, 'group': '主组 / AI'}).status_code, 400)
        imported = self.service.subscriptions.add('导入', text=yaml.safe_dump(self.config))
        self.assertFalse(self.service.control.status(imported)['can_switch'])
        (self.clash / 'profiles.yaml').write_text('current: other\nitems: []\n', encoding='utf-8')
        self.assertFalse(self.service.control.status(self.profile)['can_switch'])
        self.assertFalse(any(c[0] == 'PUT' for c in self.controller.calls))
        self.assertEqual(self.official.calls, [])

    def test_groups_modes_and_unconfirmed_result(self):
        for group in ('自动', '嵌套', 'GLOBAL', '不存在'):
            with self.assertRaises(PanelError):
                self.service.control.select(self.profile, self.nodes[1]['id'], group)
        self.controller.mode = 'direct'
        self.assertFalse(self.service.control.status(self.profile)['can_switch'])
        self.controller.mode = 'global'
        self.assertEqual([g['name'] for g in self.service.control.status(self.profile)['groups']], ['GLOBAL'])
        self.assertFalse(any(c[0] == 'PUT' for c in self.controller.calls))
        self.controller.confirm = False
        with self.assertRaisesRegex(PanelError, '未确认成功'):
            self.service.control.select(self.profile, self.nodes[1]['id'], 'GLOBAL')

    def test_automatic_ping0_saves_without_browser_or_clash_change(self):
        self.service.step()
        self.record()
        self.service.ping0_runner.query.return_value = {'status': 'ok', 'ip': '203.0.113.7', 'score': 7, 'label': '纯净'}
        job = self.start_ping0()
        self.assertEqual(self.service.ping0_bridge.snapshot(job)['status'], 'completed')
        self.service.ping0_runner.opener.assert_not_called()
        self.assertEqual(self.service.store.ping0_history(self.nodes[0]['id'])[0]['score'], 7)
        self.assertEqual(self.controller.calls, [])

    def test_challenge_extension_callback_is_bound_to_port_job_and_ip(self):
        self.record()
        original = self.service.store.history(self.nodes[0]['id'])
        job = self.start_ping0()
        self.service.ping0_runner.opener.assert_called_once_with(
            f'https://ping0.cc/ip/203.0.113.7#node-quality={job}&port={self.server.server_port}')
        self.assertEqual(self.service.ping0_bridge.recent(self.profile)[0]['status'], 'waiting')
        extension = {'Origin': 'chrome-extension://' + 'a' * 32}
        for bad in [dict(ip='203.0.113.8'), dict(job_id='x' * 32), dict(score=True)]:
            self.assertEqual(self.post('/api/ping0/result', self.payload(job) | bad, extension).status_code, 400)
        for _ in range(2):
            response = self.post('/api/ping0/result', self.payload(job), extension)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['applied_to_current'])
        self.assertEqual(self.service.store.history(self.nodes[0]['id']), original)
        self.assertEqual(len(self.service.store.ping0_history(self.nodes[0]['id'])), 1)
        self.assertEqual(self.controller.calls, [])

    def test_late_result_stays_in_old_ip_history(self):
        self.record()
        job = self.start_ping0()
        self.record('203.0.113.8')
        response = self.post('/api/ping0/result', self.payload(job))
        self.assertFalse(response.json()['applied_to_current'])
        self.assertEqual(self.service.store.snapshot()[0][self.nodes[0]['id']]['ip'], '203.0.113.8')

    def test_missing_or_changed_config_cannot_query_wrong_exit(self):
        target = {'profile_id': self.profile, 'node_id': self.nodes[0]['id']}
        self.assertEqual(self.post('/api/ping0/open', target).status_code, 400)
        self.record()
        self.service.subscriptions.items[self.profile]['nodes'][0]['fingerprint'] = 'new'
        self.assertEqual(self.post('/api/ping0/open', target).status_code, 400)
        self.service.ping0_runner.query.assert_not_called()

    def test_websites_and_extension_cannot_switch_or_open_more_queries(self):
        for origin in ('https://ping0.cc', 'chrome-extension://' + 'a' * 32):
            for route in ('/api/switch', '/api/ping0/open', '/api/settings'):
                self.assertEqual(self.post(route, {}, {'Origin': origin}).status_code, 403)
        self.assertEqual(self.post('/api/ping0/result', {}, {'Origin': 'https://ping0.cc'}).status_code, 403)
        self.assertEqual(self.controller.calls, [])


if __name__ == '__main__':
    unittest.main()
