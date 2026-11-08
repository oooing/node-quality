"""Favorites and latency UI acceptance using loopback fixtures only."""
from datetime import datetime,timezone,timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys,tempfile,threading,time,json
import yaml
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'tests'))
from service import Service
from main import handler
from test_service import FakeDetector,FakeNetwork

def main():
    with tempfile.TemporaryDirectory() as temp:
        service=Service(Path(temp),Path('unused'),roots=[],start=False,detector=FakeDetector(),network=FakeNetwork())
        service.save_settings({'paused':True})
        keys=[service.subscriptions.add('列表'+str(i+1),text=yaml.safe_dump({'proxies':[
            {'name':'香港 01','type':'trojan','server':'example.invalid','port':443+i,'password':'private-config'}]})) for i in range(2)]
        nodes=[service.subscriptions.nodes(key)[0] for key in keys]
        clock=datetime.now(timezone.utc)
        def result(ip):
            nonlocal clock
            clock+=timedelta(seconds=1)
            return {'status':'ok','ip':ip,'score':12,'route_verified':True,'fingerprint':nodes[0]['fingerprint'],
                    'checked_at':clock.isoformat(),'connectivity':{'status':'ok','delay_ms':45,'checked_at':clock.isoformat()}}
        service.store.add(nodes[0],result('203.0.113.1'))
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(service,'fixture',ROOT/'ui'))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True)
                page=browser.new_page(viewport={'width':1180,'height':780})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/#token=fixture')
                expect(page.locator('#candidates .card')).to_have_count(1)
                card=page.locator('#candidates .card')
                card.click(button='right')
                expect(page.get_by_role('menuitem',name='收藏线路')).to_be_visible()
                page.get_by_role('menuitem',name='收藏线路').click()
                expect(card.locator('.favorite-toggle')).to_have_attribute('aria-pressed','true')
                page.locator('#view-favorites').click()
                expect(page.locator('#favorites-page')).to_be_visible()
                expect(page.locator('#favorites-grid .card')).to_have_count(1)
                page.reload()
                expect(page.locator('#favorites-grid .card')).to_have_count(1)
                expect(page.locator('#favorites-page')).to_be_visible()
                # Add another source server-side; the live favorites page must show both.
                service.favorite(nodes[1]['id'],True)
                expect(page.locator('#favorites-grid .favorite-group')).to_have_count(2)
                # New IP remains prominently marked after later stable checks.
                service.store.add(nodes[0],result('203.0.113.2'))
                expect(page.locator('#ip-change-notice')).to_be_visible()
                expect(page.get_by_role('button',name='查看 IP 变化')).to_have_count(1)
                service.store.add(nodes[0],result('203.0.113.2'))
                page.reload();expect(page.locator('#ip-change-notice')).to_be_visible()
                page.get_by_role('button',name='查看 IP 变化').click()
                expect(page.locator('#ip-change-content')).to_contain_text('203.0.113.1 → 203.0.113.2')
                page.get_by_role('button',name='已知晓',exact=True).click()
                expect(page.locator('#ip-change-notice')).not_to_be_visible()
                # Click milliseconds: only a latency job is queued, existing score unchanged.
                first=page.locator(f'#favorites-grid [data-node="{nodes[0]["id"]}"]')
                first.get_by_role('button',name='复测延迟 香港 01',exact=True).click()
                expect(first.locator('.latency')).to_be_disabled()
                assert nodes[0]['id'] in service.latency_ids
                assert service.store.snapshot()[0][nodes[0]['id']]['score']==12
                with service.lock:service.queue.clear();service.latency_ids.clear()
                measure=result('203.0.113.2');measure['connectivity']['delay_ms']=83
                service.store.add_latency(nodes[0],measure)
                expect(first.locator('.latency')).to_have_text('83 ms')
                # Keyboard context menu and opening the original line page.
                first.focus();page.keyboard.press('Shift+F10')
                expect(page.get_by_role('menuitem',name='查看线路',exact=True)).to_be_visible()
                page.get_by_role('menuitem',name='查看线路',exact=True).click()
                expect(page.locator('#results')).to_be_visible()
                expect(page.locator('#profiles')).to_have_value(keys[0])
                for width in (1180,780,520):
                    page.set_viewport_size({'width':width,'height':780})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('.card:visible').evaluate_all('(xs)=>xs.every(x=>x.scrollHeight<=x.clientHeight+2)')
                page.set_viewport_size({'width':1180,'height':780})
                page.locator('#view-favorites').click()
                page.screenshot(path=str(ROOT/'test-results/favorites-029.png'))
                first=page.locator(f'#favorites-grid [data-node="{nodes[0]["id"]}"]')
                first.locator('.favorite-toggle').click()
                expect(page.locator('#favorites-grid .card')).to_have_count(1)
                assert not errors,errors
                browser.close()
                print('PASS: right-click and keyboard favorites, cross-source persistence, IP alerts/acknowledgment, latency-only refresh, compact layout.')
        finally:server.shutdown();server.server_close()

if __name__=='__main__':main()
