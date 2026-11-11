"""Production Astryx UI acceptance against an isolated, local real Service.

No source-client discovery, live proxy, risk-site request, or real switch occurs.
Run after building frontend/. Reports and screenshots go to test-results/astryx/.
"""
from datetime import datetime, timezone, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import re
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
import yaml
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tests'))
from service import Service
from main import handler
from diagnostics import diagnosis
from test_service import FakeDetector, FakeNetwork


def main():
    output = ROOT / 'test-results' / 'astryx'
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    with tempfile.TemporaryDirectory(prefix='fixture-', dir=output) as temporary:
        service = Service(Path(temporary), Path('never-started.exe'), roots=[], start=False,
                          detector=FakeDetector(), network=FakeNetwork())
        service.save_settings({'paused': True})
        def add_source(name, names, port):
            return service.subscriptions.add(name, text=yaml.safe_dump({'proxies': [
                {'name': line, 'type': 'trojan', 'server': 'fixture.invalid',
                 'port': port, 'password': 'fixture-only'} for line in names]}, allow_unicode=True))
        primary = add_source('验收列表一', ['香港家宽', '美国高风险', '日本旧评分', '香港连接失败', '新加坡未检测'], 443)
        secondary = add_source('验收列表二', ['香港家宽'], 444)
        lines = service.subscriptions.nodes(primary)
        other = service.subscriptions.nodes(secondary)[0]
        now = datetime.now(timezone.utc)
        def result(node, ip, score, when=None):
            stamp = (when or now).isoformat()
            return {'status': 'ok', 'ip': ip, 'score': score, 'route_verified': True,
                    'fingerprint': node['fingerprint'], 'checked_at': stamp,
                    'connectivity': {'status': 'ok', 'delay_ms': 65, 'checked_at': stamp}}
        for node, score in zip(lines, (12, 78, 5, 2)):
            when = now - timedelta(days=2) if node == lines[2] else now - timedelta(minutes=2)
            service.store.add(node, result(node, '203.0.113.10', score, when))
        service.store.add(lines[3], {
            'status': 'error', 'checked_at': now.isoformat(), 'fingerprint': lines[3]['fingerprint'],
            'error': '连接超时', 'connectivity': {'status': 'timeout'},
            'diagnosis': diagnosis('line', 'connect_timeout', '连接超时',
                                  '独立连接未响应，尚未查询风险。', ['两个测试站均未连接'], '稍后重试')})
        service.store.add(other, result(other, '203.0.113.20', 16))
        for node in (lines[1], lines[3], other):
            service.favorite(node['id'], True)
        service.store.set_favorite({'id': 'removed-fixture', 'name': '已移除收藏', 'profile_id': secondary,
                                   'profile_name': '验收列表二', 'client': '手动导入', 'type': 'trojan'}, True)

        class FixtureControl:
            selected = lines[1]['name']
            calls = []
            def status(self, profile):
                allowed = profile == primary
                return {'profile_id': profile, 'available': True, 'can_switch': allowed,
                        'reason': '' if allowed else '不是当前 Clash 列表', 'mode': 'rule',
                        'switchable_ids': [n['id'] for n in lines] if allowed else [],
                        'groups': [{'name': '验收分组', 'selected': self.selected,
                                    'members': [n['name'] for n in lines]}] if allowed else []}
            def select(self, profile, node_id, group):
                assert profile == primary and group == '验收分组'
                assert node_id in [n['id'] for n in lines]
                self.selected = next(n['name'] for n in lines if n['id'] == node_id)
                self.calls.append((profile, node_id, group))
                return {'verified': True, 'persisted': True, 'selected': self.selected, 'group': group}
        control = FixtureControl()
        service.control = control
        service.ping0_runner.query = lambda ip: {'status': 'ok', 'ip': ip, 'score': 7, 'label': '极度纯净'}
        service.ping0_runner.opener = lambda url: (_ for _ in ()).throw(AssertionError('No browser challenge expected'))
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(service, 'fixture-token', ROOT / 'ui'))
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f'http://127.0.0.1:{server.server_port}'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(origin + '/') as response:
                html = response.read().decode()
                assert "script-src 'self'" in response.headers.get('Content-Security-Policy', '')
            assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
            assert assets, 'Production UI is not a built Vite application'
            for asset in assets:
                with opener.open(origin + asset) as response:
                    assert response.status == 200
                    assert response.headers.get('Content-Type', '').startswith(
                        ('text/javascript', 'application/javascript', 'text/css'))
            try:
                opener.open(origin + '/api/state')
                raise AssertionError('Unauthenticated state must be denied')
            except urllib.error.HTTPError as error:
                assert error.code == 403
            checks.append('built assets load with script CSP; API token remains required')
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1180, 'height': 800})
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
                page.set_default_timeout(12000)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                requests = []
                page.on('request', lambda request: requests.append(request.url))
                page.goto(origin + '/#token=fixture-token')
                try:
                    expect(page.locator('.r-app')).to_be_visible()
                except AssertionError:
                    page.screenshot(path=str(output / 'startup-failure.png'))
                    print(json.dumps({'errors': errors, 'body': page.locator('body').inner_text()}, ensure_ascii=False))
                    raise
                expect(page.locator('#candidates .r-card')).to_have_count(2)
                # The backend keeps old scores, but never promotes a connection failure.
                ids = page.locator('#candidates .r-card').evaluate_all('(xs)=>xs.map(x=>x.dataset.node)')
                assert ids == [item['id'] for item in service.state(primary)['recommendations']['items']]
                assert lines[3]['id'] not in ids
                expect(page.locator(f'[data-node="{lines[2]["id"]}"]')).to_contain_text('待复查')
                checks.append('backend ranking preserved; old score retained; failed low-score line excluded')

                first = page.locator(f'#candidates [data-node="{lines[0]["id"]}"]')
                handle = first.element_handle()
                search = page.get_by_role('textbox', name='搜索线路', exact=True)
                search.fill('香港')
                search.focus()
                page.wait_for_timeout(2500)
                expect(search).to_be_focused()
                expect(search).to_have_value('香港')
                assert handle.evaluate('(element)=>element.isConnected')
                page.get_by_role('combobox', name='检测范围', exact=True).select_option('filtered')
                page.get_by_role('button', name='检测 1 条', exact=True).click()
                expect(page.get_by_role('button', name='同步中', exact=True)).to_be_disabled()
                service.step()
                expect(first.get_by_role('button', name=re.compile('排队|等待'))).to_be_disabled()
                assert list(service.queue) == [lines[0]['id']]
                assert not control.calls
                with service.lock:
                    service.queue.clear()
                search.fill('')
                page.get_by_role('combobox', name='检测范围', exact=True).select_option('all')
                page.get_by_role('button', name='检测 5 条', exact=True).click()
                expect(page.get_by_role('button', name='同步中', exact=True)).to_be_disabled()
                service.step()
                deadline = time.monotonic() + 8
                while len(service.queue) != 5 and time.monotonic() < deadline:
                    page.wait_for_timeout(100)
                assert set(service.queue) == {n['id'] for n in lines}
                with service.lock:
                    service.queue.clear()
                expect(page.get_by_role('button', name='更新线路', exact=True)).to_have_count(0)
                checks.append('batch refreshes first; home refresh removed; poll keeps input focus/card DOM; filtered/all queue scope accurate; no implicit switch')

                page.get_by_role('button', name=re.compile('^收藏')).first.click()
                expect(page.locator('#favorites-grid .r-card')).to_have_count(4)
                expect(page.locator('.r-nav [aria-current="page"]')).to_have_count(1)
                expect(page.locator('.r-nav [aria-current="page"]')).to_contain_text('收藏')
                expect(page.locator(f'#favorites-grid [data-node="{lines[1]["id"]}"]')).to_contain_text('78')
                expect(page.locator('#favorites-grid [data-node="removed-fixture"]')).to_contain_text('移除')
                foreign = page.locator(f'#favorites-grid [data-node="{other["id"]}"]')
                expect(foreign.get_by_role('button', name='换用', exact=True)).to_be_disabled()
                assert not control.calls
                expect(page.locator('.r-progress')).to_contain_text('自动检测已暂停')
                page.screenshot(path=str(output / 'favorites.png'), full_page=True)
                checks.append('all favorites retained, including high-risk/removed; cross-source same-name switch disabled')
                # A waiting job belongs to the foreign favorite, not the selected source.
                opened = []
                service.ping0_runner.opener = opened.append
                service.ping0_runner.callback_port = server.server_port
                job = service.ping0_bridge.create(other['id'], secondary, service.store.snapshot()[0][other['id']])
                foreign.get_by_role('button', name='详情', exact=True).click()
                with page.expect_request(lambda r: r.method == 'POST' and r.url.endswith('/api/ping0/reopen')) as request:
                    page.get_by_role('button', name='打开验证', exact=True).click()
                assert request.value.post_data_json == {'job_id': job}
                expect(page.get_by_role('dialog')).to_contain_text('请在浏览器完成验证')
                assert len(opened) == 1 and job in opened[0]
                service.ping0_bridge.receive({'job_id': job, 'ip': '203.0.113.20', 'score': 11,
                    'label': '极度纯净', 'page_url': 'https://ping0.cc/ip/203.0.113.20'})
                expect(page.get_by_role('dialog')).to_contain_text('11%')
                assert service.store.ping0_history(other['id'])[0]['score'] == 11
                page.keyboard.press('Escape')
                checks.append('foreign-source waiting Ping0 job reopens correctly; simulated extension result persists')
                failed = page.locator(f'#favorites-grid [data-node="{lines[3]["id"]}"]')
                failed.get_by_role('button', name='详情', exact=True).click()
                expect(page.get_by_role('dialog')).to_contain_text('线路问题：连接超时')
                page.get_by_text('诊断详情', exact=True).first.click()
                expect(page.get_by_role('dialog')).to_contain_text('两个测试站均未连接')
                page.keyboard.press('Escape')
                checks.append('failed line detail preserves diagnosis category and concrete evidence')
                page.get_by_role('button', name='线路', exact=True).click()
                first.get_by_role('button', name='详情', exact=True).click()
                dialog = page.get_by_role('dialog')
                expect(dialog).to_contain_text('203.0.113.10')
                page.get_by_role('button', name='Ping0 补测', exact=True).click()
                expect(dialog).to_contain_text('7%')
                assert service.store.ping0_history(lines[0]['id'])
                page.screenshot(path=str(output / 'history-modal.png'), full_page=True)
                page.get_by_role('button', name='复测延迟', exact=True).click()
                deadline = time.monotonic() + 8
                while lines[0]['id'] not in service.latency_ids and time.monotonic() < deadline:
                    page.wait_for_timeout(100)
                assert lines[0]['id'] in service.latency_ids
                assert service.store.snapshot()[0][lines[0]['id']]['score'] == 12
                with service.lock:
                    service.queue.clear(); service.latency_ids.clear()
                page.keyboard.press('Escape')
                expect(page.get_by_role('dialog')).to_have_count(0)
                checks.append('detail uses stored history; Ping0 persists; latency-only queue keeps score; Escape closes')

                first.get_by_role('button', name='换用', exact=True).click()
                expect(first).to_contain_text('使用中')
                expect(first.get_by_role('button', name='换用', exact=True)).to_have_count(0)
                assert len(control.calls) == 1
                assert control.selected == lines[0]['name']
                expect(page.locator('.r-progress')).to_contain_text('自动检测已暂停')
                page.screenshot(path=str(output / 'current-best.png'), full_page=True)
                checks.append('explicit switch checks persisted result and renders single current-use state')

                # Alerts are scoped to IDs; acknowledging one never clears another.
                service.store.add(lines[0], result(lines[0], '203.0.113.11', 12, now + timedelta(seconds=1)))
                service.store.add(lines[2], result(lines[2], '203.0.113.12', 5, now + timedelta(seconds=1)))
                expect(page.get_by_role('button', name=re.compile('2.*IP.*变化'))).to_be_visible()
                page.get_by_role('button', name=re.compile('2.*IP.*变化')).click()
                page.get_by_role('button', name='已知晓', exact=True).first.click()
                expect(page.get_by_role('button', name='已知晓', exact=True)).to_have_count(1)
                assert len(service.store.extras()[2]) == 1
                page.keyboard.press('Escape')
                checks.append('IP alert acknowledgment affects one line only')

                plan = page.get_by_role('button', name=re.compile('^(自动计划|计划暂停|未选列表)$'))
                plan.click()
                expect(page.get_by_role('dialog')).to_contain_text('列表')
                switch = page.get_by_role('switch', name=re.compile('自动检测|每天检测'))
                expect(switch).not_to_be_checked()
                switch.check()
                page.get_by_role('checkbox', name='验收列表一', exact=True).check()
                page.get_by_role('checkbox', name='验收列表二', exact=True).check()
                page.get_by_role('button', name='保存', exact=True).click()
                expect(page.get_by_role('button', name='自动计划', exact=True)).to_be_visible()
                assert not service.settings['paused']
                assert {p['id'] for p in service.subscriptions.public() if p['enabled']} == {primary, secondary}
                first.get_by_role('button', name='检测', exact=True).click()
                expect(first.get_by_role('button', name='排队中', exact=True)).to_be_disabled()
                page.get_by_role('button', name='自动计划', exact=True).click()
                page.get_by_role('switch', name='自动检测', exact=True).uncheck()
                page.get_by_role('button', name='保存', exact=True).click()
                expect(page.get_by_role('button', name='计划暂停', exact=True)).to_be_visible()
                assert service.settings['paused']
                assert list(service.queue) == [lines[0]['id']], 'Pausing automatic work must not cancel a manual request'
                page.get_by_role('button', name='清空排队', exact=True).click()
                expect(page.get_by_role('button', name='清空排队', exact=True)).to_have_count(0)
                assert not service.queue
                assert len(control.calls) == 1
                checks.append('multi-source automatic plan persists; pause preserves manual queue; clearing queue is explicit')
                page.get_by_role('button', name='推荐设置', exact=True).click()
                risk = page.get_by_role('spinbutton', name='风险上限', exact=True)
                risk.fill('27')
                risk.focus()
                page.wait_for_timeout(2200)
                expect(risk).to_be_focused()
                expect(risk).to_have_value('27')
                page.get_by_role('checkbox', name='美国', exact=True).check()
                page.get_by_role('button', name='保存', exact=True).click()
                expect(page.locator('#candidates .r-card')).to_have_count(0)
                assert service.settings['recommendation']['regions'] == ['US']
                page.reload()
                expect(page.locator('.r-app')).to_be_visible()
                page.get_by_role('button', name='推荐设置', exact=True).click()
                expect(page.get_by_role('spinbutton', name='风险上限', exact=True)).to_have_value('27')
                expect(page.get_by_role('checkbox', name='美国', exact=True)).to_be_checked()
                page.get_by_role('button', name='清空选择', exact=True).click()
                page.get_by_role('button', name='保存', exact=True).click()
                expect(page.locator('#candidates .r-card')).to_have_count(2)
                checks.append('recommendation regions persist across reload and clear without losing other settings')
                for width in (1180, 780, 390):
                    page.set_viewport_size({'width': width, 'height': 800})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
                page.set_viewport_size({'width': 1180, 'height': 800})
                close_toast = page.get_by_role('button', name='关闭提示', exact=True)
                if close_toast.count():
                    close_toast.click()
                page.screenshot(path=str(output / 'production-08.png'), full_page=True)
                assert not errors, errors
                assert all(url.startswith(origin) for url in requests), 'External resource requested by production UI'
                checks.append('paused plan preserved; 1180/780/390 layouts fit; no external resources/page errors')
                browser.close()
            (output / 'result.json').write_text(json.dumps({'passed': checks}, ensure_ascii=False, indent=2), encoding='utf-8')
            print('PASS: Astryx production acceptance; ' + str(len(checks)) + ' groups; no real proxies or external checks.')
        finally:
            service.close()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
