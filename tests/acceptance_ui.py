"""UI acceptance in a fresh browser, with local synthetic data and no external checks."""
from datetime import datetime, timezone
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


def main():
    with tempfile.TemporaryDirectory() as temp:
        service=Service(Path(temp),Path('unused.exe'),roots=[],start=False)
        service.save_settings({'paused':True})
        key=service.subscriptions.add('界面验收订阅',text=yaml.safe_dump({'proxies':[
            {'name':name,'type':'trojan','server':'example.invalid','port':443,'password':'fixture'}
            for name in ('香港 01','美国 02','日本 03')]}))
        nodes=service.subscriptions.nodes(key)
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
                first=page.locator('#candidates .card').element_handle()
                page.wait_for_timeout(4300)
                assert first.evaluate('(e)=>e.isConnected'), 'Unchanged cards were replaced by polling'
                page.locator('#candidates [data-action="history"]').click()
                page.locator('#history-content .history-row').wait_for()
                assert '203.0.113.1' in page.locator('#history-content').inner_text()
                page.locator('#history-dialog .close').click()
                page.locator('#settings').click()
                assert page.locator('#regions input').evaluate_all('(es)=>es.slice(0,5).map(e=>e.value)')==['HK','TW','JP','SG','US']
                page.locator('#regions input[value="US"]').check()
                page.locator('#settings-form button[type="submit"]').click()
                expect(page.locator('#candidate-count')).to_have_text('0')
                assert '超过 30' in page.locator('#empty').inner_text()
                page.reload()
                page.locator('#settings').click()
                assert page.locator('#regions input[value="US"]').is_checked()
                page.locator('#clear-regions').click()
                assert page.locator('#regions input:checked').count()==0
                page.locator('#settings-form button[type="submit"]').click()
                expect(page.locator('#candidate-count')).to_have_text('1')
                page.locator('#others summary').click()
                page.locator('#other-grid [data-action="check"]').nth(0).click()
                page.locator('#other-grid [data-action="check"]').nth(1).click()
                assert len(service.queue)==2
                for width in (1180,780):
                    page.set_viewport_size({'width':width,'height':780})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Horizontal overflow'
                    assert page.locator('.card').evaluate_all('(es)=>es.every(e=>e.getBoundingClientRect().height<=140)')
                page.set_viewport_size({'width':1180,'height':780})
                page.screenshot(path=str(ROOT/'test-results/ui-acceptance.png'))
                assert not errors,errors
                browser.close()
                print('PASS: stable cards, history, region filters, settings persistence, multi-node queue, 780/1180px layout, no JS errors.')
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
