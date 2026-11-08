"""UI acceptance in a fresh browser, with local synthetic data and no external checks."""
from datetime import datetime, timezone, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time
import yaml
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from service import Service
from main import handler
from diagnostics import diagnosis


def main():
    with tempfile.TemporaryDirectory() as temp:
        service=Service(Path(temp),Path('unused.exe'),roots=[],start=False)
        service.save_settings({'paused':True})
        key=service.subscriptions.add('界面验收列表',text=yaml.safe_dump({'proxies':[
            {'name':name,'type':'trojan','server':'example.invalid','port':443,'password':'fixture'}
            for name in ('香港 01','美国 02','日本 03')]}))
        nodes=service.subscriptions.nodes(key)
        class UIControl:
            selected='美国 02'
            def status(self, profile):
                return {'profile_id':profile,'can_switch':True,'available':True,'mode':'rule',
                    'switchable_ids':[n['id'] for n in nodes],
                    'groups':[{'name':'测试代理组','selected':self.selected,'members':[n['name'] for n in nodes]}]}
            def select(self, profile, node_id, group):
                assert profile==key and group=='测试代理组'
                self.selected=next(n['name'] for n in nodes if n['id']==node_id)
                return {'verified':True,'persisted':True,'selected':self.selected,'group':group}
        service.control=UIControl()
        service.ping0_runner.query=lambda ip: {'status':'ok','ip':ip,'score':7,'label':'极度纯净'}
        service.ping0_runner.opener=lambda url: (_ for _ in ()).throw(AssertionError('Synthetic success must not open a browser'))
        for node,score in zip(nodes,(12,78)):
            service.store.add(node,{'status':'ok','ip':'203.0.113.1','score':score,'route_verified':True,
                                   'fingerprint':node['fingerprint'],'checked_at':datetime.now(timezone.utc).isoformat(),
                                   'connectivity':{'status':'ok','delay_ms':65}})
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(service,'ui-test-token',ROOT/'ui'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                page=browser.new_page(viewport={'width':1180,'height':780})
                errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/#token=ui-test-token')
                page.locator('#candidates .card').wait_for()
                assert page.locator('#candidates .card').count()==1
                assert page.locator('#others').get_attribute('open') is None
                expect(page.locator('#progress-count')).to_have_text('已完成 2 / 3')
                expect(page.locator('#status')).to_have_text('自动检测已关闭')
                expect(page.get_by_role('switch',name='自动检测',exact=True)).to_have_attribute('aria-checked','false')
                first=page.locator('#candidates .card').element_handle()
                page.wait_for_timeout(4300)
                assert first.evaluate('(e)=>e.isConnected'), 'Unchanged cards were replaced by polling'
                page.locator('#candidates [data-action="history"]').click()
                page.locator('#history-content .history-row').wait_for()
                assert '203.0.113.1' in page.locator('#history-content').inner_text()
                page.locator('#history-dialog .close').click()
                page.locator('#candidates [data-action="ping0"]').click()
                expect(page.locator('#candidates .ping0-score')).to_have_text('Ping07%')
                page.locator('#candidates [data-action="history"]').click()
                expect(page.locator('#history-content')).to_contain_text('补测记录')
                expect(page.locator('#history-content')).to_contain_text('7%')
                page.locator('#history-dialog .close').click()
                page.locator('#candidates [data-action="switch"]').click()
                expect(page.locator('#toast')).to_have_text('已换用并保存：香港 01')
                expect(page.locator('#candidates .current-state')).to_have_text('使用中')
                expect(page.locator('#candidates [data-action="switch"]')).to_have_count(0)
                assert service.control.selected=='香港 01'
                page.screenshot(path=str(ROOT/'test-results/readme-current.png'))
                page.locator('#settings').click()
                expect(page.get_by_role('tab',name='线路管理')).to_have_attribute('aria-selected','true')
                expect(page.locator('#panel-sources')).to_be_visible()
                page.locator('#rescan').click()
                expect(page.locator('#toast')).to_have_text('已同步 1 个线路列表')
                page.locator('#subscription-list input').uncheck()
                page.locator('#save-subscriptions').click()
                expect(page.locator('#settings-dialog')).not_to_be_visible()
                assert not service.subscriptions.public()[0]['enabled']
                page.locator('#settings').click()
                expect(page.locator('#subscription-list input')).not_to_be_checked()
                page.locator('#subscription-list input').check()
                page.locator('#save-subscriptions').click()
                expect(page.locator('#settings-dialog')).not_to_be_visible()
                page.locator('#settings').click()
                page.screenshot(path=str(ROOT/'test-results/settings-sources.png'))
                page.get_by_role('tab',name='线路管理').focus()
                page.keyboard.press('ArrowDown')
                expect(page.get_by_role('tab',name='推荐设置')).to_be_focused()
                expect(page.locator('#panel-recommend')).to_be_visible()
                page.get_by_role('tab',name='自动检测').click()
                expect(page.locator('#auto-enabled')).not_to_be_checked()
                assert page.locator('.daily-toggle').evaluate('(e)=>getComputedStyle(e).flexDirection')=='row'
                page.screenshot(path=str(ROOT/'test-results/settings-automatic-024.png'))
                assert page.locator('#fresh-hours,#limit,#update-hours,#candidate-hours,#other-hours').count()==0
                page.locator('#save-settings').click()
                expect(page.locator('#settings-dialog')).not_to_be_visible()
                assert service.settings['paused']
                page.locator('#settings').click()
                page.get_by_role('tab',name='推荐设置').click()
                page.set_viewport_size({'width':520,'height':700})
                assert page.locator('.settings-content').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
                page.set_viewport_size({'width':1180,'height':780})
                page.screenshot(path=str(ROOT/'test-results/settings-recommend.png'))
                assert page.locator('#regions input').evaluate_all('(es)=>es.slice(0,5).map(e=>e.value)')==['HK','TW','JP','SG','US']
                page.locator('#regions input[value="US"]').check()
                page.locator('#settings-form button[type="submit"]').click()
                expect(page.locator('#candidate-count')).to_have_text('0')
                assert '超过 30' in page.locator('#empty').inner_text()
                page.reload()
                page.locator('#settings').click()
                page.get_by_role('tab',name='推荐设置').click()
                assert page.locator('#regions input[value="US"]').is_checked()
                page.locator('#clear-regions').click()
                assert page.locator('#regions input:checked').count()==0
                page.locator('#settings-form button[type="submit"]').click()
                expect(page.locator('#candidate-count')).to_have_text('1')
                page.locator('#others summary').click()
                page.locator('#other-grid [data-action="check"]').nth(0).click()
                page.locator('#other-grid [data-action="check"]').nth(1).click()
                expect(page.locator('#other-grid [data-action="check"]:disabled')).to_have_count(2)
                assert len(service.queue)==2
                expect(page.locator('#progress-count')).to_have_text('已完成 1 / 3')
                # A real scheduler transition, without sending traffic to any proxy.
                active_id=service.queue.popleft()
                service.active=next(n for n in nodes if n['id']==active_id)
                service.active_started=time.monotonic()-7
                service.detector.progress={'node_id':active_id,'stage':'dns'}
                expect(page.locator('#status')).to_contain_text('查找检测网站地址')
                expect(page.locator('#elapsed')).to_be_visible()
                assert int(page.locator('#elapsed').inner_text().split()[0])>=7
                assert page.locator('#status-icon').evaluate('(e)=>getComputedStyle(e).animationName')=='checking-spin'
                active_card=page.locator('.card.checking').element_handle()
                page.wait_for_timeout(2200)
                assert active_card.evaluate('(e)=>e.isConnected'), 'Timer refresh replaced the active card'
                page.emulate_media(reduced_motion='reduce')
                assert page.locator('#status-icon').evaluate('(e)=>getComputedStyle(e).animationName')=='none'
                assert page.locator('.checking .spinner').evaluate('(e)=>getComputedStyle(e).animationName')=='none'
                page.emulate_media(reduced_motion='no-preference')
                for width in (1180,780):
                    page.set_viewport_size({'width':width,'height':780})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Horizontal overflow'
                    assert page.locator('.card').evaluate_all('(es)=>es.every(e=>e.getBoundingClientRect().height<=140)')
                page.set_viewport_size({'width':1180,'height':780})
                page.screenshot(path=str(ROOT/'test-results/ui-acceptance.png'))
                service.detector.progress={'node_id':active_id,'stage':'connectivity_retry'}
                expect(page.locator('#status')).to_contain_text('尝试连接另一个测试网站')
                service.active=service.active_started=None
                service.detector.progress=None
                service.cooldown_until=time.time()+120
                expect(page.locator('#status')).to_contain_text('等待重试')
                assert page.locator('#status-icon').evaluate('(e)=>getComputedStyle(e).animationName')=='none'
                assert page.locator('.checking').count()==0
                service.cooldown_until=0
                service.queue.clear()
                expect(page.locator('#status')).to_have_text('自动检测已关闭')
                service.save_settings({'paused':False})
                for node in nodes:
                    service.store.add(node,{'status':'error','error':'fixture timeout',
                        'fingerprint':node['fingerprint'],'checked_at':datetime.now(timezone.utc).isoformat()})
                expect(page.locator('#status')).to_have_text('本轮已完成，之后会按计划重测。')
                auto=page.get_by_role('switch',name='自动检测',exact=True)
                expect(auto).to_have_attribute('aria-checked','true')
                expect(page.locator('#footer-status')).to_have_count(0)
                auto.click()
                expect(auto).to_have_attribute('aria-checked','false')
                expect(page.locator('#status')).to_have_text('自动检测已关闭')
                auto.click()
                expect(auto).to_have_attribute('aria-checked','true')
                expect(page.locator('#status')).to_have_text('本轮已完成，之后会按计划重测。')
                expect(page.locator('#progress-detail')).to_have_text('剩余 0 · 失败 3')
                expect(page.locator('#progress')).to_have_attribute('aria-valuetext','已完成 3，共 3 个；剩余 0，失败 3')
                # A fresh failure remains visible even when a previous good score exists.
                reason=diagnosis('line','tls_closed','TLS 握手被提前断开',
                    '服务器端口能连接，但加密握手未完成。',
                    ['独立 TCP 探测：服务器端口可连接','独立 TLS 探测：握手未完成，连接被断开'],
                    '可稍后重试或联系线路提供方。')
                service.store.add(nodes[0],{'status':'error','error':reason['message'],'diagnosis':reason,
                    'fingerprint':nodes[0]['fingerprint'],'checked_at':datetime.now(timezone.utc).isoformat()})
                if page.locator('#others').get_attribute('open') is None:
                    page.locator('#others>summary').click()
                page.locator('#search').fill('香港 01')
                failure=page.get_by_role('button',name='查看失败原因',exact=True)
                expect(failure).to_have_text('线路问题：TLS 握手被提前断开')
                assert failure.locator('..').bounding_box()['height']<=140
                failure.click()
                expect(page.locator('#history-content')).to_contain_text(reason['message'])
                page.locator('#history-content .diagnosis-detail summary').first.click()
                expect(page.locator('#history-content .diagnosis-detail').first).to_contain_text('独立 TCP 探测')
                expect(page.locator('#history-content .diagnosis-detail').first).to_contain_text('联系线路提供方')
                page.locator('#history-dialog .close').click()
                page.locator('#search').fill('')
                # Fresh, stale and query-only failures in a separate synthetic list.
                service.save_settings({'paused': True})
                review_key=service.subscriptions.add('复查验收',text=yaml.safe_dump({'proxies':[
                    {'name':f'美国 {i}','type':'trojan','server':'example.invalid','port':443,'password':'fixture'}
                    for i in range(8)]}))
                review_nodes=service.subscriptions.nodes(review_key)
                old_time=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
                for node in review_nodes:
                    service.store.add(node,{'status':'ok','ip':'203.0.113.9','score':8,'route_verified':True,
                        'fingerprint':node['fingerprint'],'checked_at':old_time,
                        'connectivity':{'status':'ok','delay_ms':50}})
                expect(page.locator('#profiles option')).to_have_count(2)
                page.locator('#profiles').select_option(review_key)
                expect(page.locator('#candidate-count')).to_have_text('8')
                expect(page.locator('#candidates .card')).to_have_count(8)
                expect(page.locator('#candidates .fold')).to_have_count(0)
                expect(page.locator('#candidates .review-badge').first).to_have_text('待复查')
                expect(page.locator('#more-candidates')).to_have_count(0)
                expect(page.locator('#candidates .card')).to_have_count(8)
                node=review_nodes[0]
                service.store.add(node,{'status':'error','error':'评分网站暂时不可用',
                    'diagnosis':diagnosis('site','score_request','评分网站暂时不可用'),
                    'fingerprint':node['fingerprint'],'checked_at':datetime.now(timezone.utc).isoformat(),
                    'connectivity':{'status':'ok','delay_ms':50}})
                retained=page.locator(f'#candidates [data-node="{node["id"]}"]')
                expect(retained.locator('.failure-reason')).to_have_text('评分问题：评分网站暂时不可用')
                expect(retained.locator('.ip')).to_contain_text('上次 203.0.113.9 · 风险 8')
                assert '评分检测于' in retained.locator('[data-action="history"]').get_attribute('title')
                service.store.add(review_nodes[1],{'status':'error','error':'两个测试网站都连接超时',
                    'fingerprint':review_nodes[1]['fingerprint'],'checked_at':datetime.now(timezone.utc).isoformat(),
                    'connectivity':{'status':'timeout'}})
                expect(page.locator('#candidate-count')).to_have_text('7')
                expect(page.locator('#other-count')).to_have_text('1')
                for width in (520,780,1180):
                    page.set_viewport_size({'width':width,'height':780})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('#candidates .card').evaluate_all('(es)=>es.every(e=>e.scrollHeight<=e.clientHeight+2)')
                page.screenshot(path=str(ROOT/'test-results/review-policy-024.png'))
                expect(page.locator('#candidates .card')).to_have_count(7)
                # Same original subscription name in different clients remains identifiable.
                filename='Clash_1793077309.yaml'
                service.subscriptions.items[key].update(name=filename,origin='Clash Verge')
                service.subscriptions.items[review_key].update(name=filename,origin='Clash Verge Rev')
                posts=[]
                page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
                route_before=service.control.selected
                enabled_before={p['id']:p['enabled'] for p in service.subscriptions.public()}
                expect(page.locator('#clients')).to_have_value('Clash Verge Rev')
                expect(page.locator('#clients option')).to_have_count(2)
                expect(page.locator('#profiles option')).to_have_count(1)
                expect(page.locator('#profiles option')).to_have_text(filename)
                page.locator('#clients').select_option('Clash Verge')
                expect(page.locator('#profiles')).to_have_value(key)
                expect(page.locator('#profiles option')).to_have_text(filename)
                page.locator('#clients').select_option('Clash Verge Rev')
                expect(page.locator('#profiles')).to_have_value(review_key)
                expect(page.locator('#candidate-count')).to_have_text('7')
                page.locator('#settings').click()
                expect(page.locator('.source-group h4')).to_have_text(['Clash Verge','Clash Verge Rev'])
                expect(page.locator('.source-info strong')).to_have_text([filename,filename])
                page.screenshot(path=str(ROOT/'test-results/sources-025.png'))
                page.locator('#settings-dialog .close').click()
                for width in (520,780,1180):
                    page.set_viewport_size({'width':width,'height':780})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    expect(page.locator('#clients')).to_be_visible()
                    expect(page.locator('#profiles')).to_be_visible()
                page.screenshot(path=str(ROOT/'test-results/source-picker-025.png'))
                assert not posts, 'Changing the viewed source must not mutate app or VPN state'
                assert service.control.selected==route_before
                assert {p['id']:p['enabled'] for p in service.subscriptions.public()}==enabled_before
                assert not errors,errors
                browser.close()
                print('PASS: progress counts, active stages and elapsed time, animation, reduced motion, pause/cooldown/completion, stable cards, history, filters, queue, compact layout, no JS errors.')
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
