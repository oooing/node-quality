"""Local-only UI fixture: no scheduler, no client discovery, no real traffic."""
from pathlib import Path
from http.server import ThreadingHTTPServer
from datetime import datetime, timezone
import sys, yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'tests')]
from service import Service
from main import handler
from test_service import FakeDetector, FakeNetwork
s=Service(ROOT/'test-results/progress-fixture',Path('never-started.exe'),roots=[],start=False,detector=FakeDetector(),network=FakeNetwork())
s.save_settings({'paused':True})
for index,name in enumerate(['已检查列表','后台列表','新加入列表']):
 s.subscriptions.add(name,text=yaml.safe_dump({'proxies':[{'name':'香港家宽 '+str(i),'type':'trojan','server':'fixture.invalid','port':443+index,'password':'fixture'} for i in range(3)]},allow_unicode=True))
profiles=s.subscriptions.public()
main=next(p['id'] for p in profiles if p['name']=='已检查列表')
other=next(p['id'] for p in profiles if p['name']=='后台列表')
for n in s.subscriptions.nodes(main):
 s.store.add(n,{'status':'ok','ip':'203.0.113.20','score':8,'fingerprint':n['fingerprint'],'checked_at':datetime.now(timezone.utc).isoformat(),'route_verified':True})
s.enqueue(other)
class Control:
 def status(self,profile):return {'profile_id':profile,'groups':[],'can_switch':False,'reason':'隔离验收'}
s.control=Control()
server=ThreadingHTTPServer(('127.0.0.1',17795),handler(s,'fixture-token',ROOT/'ui'))
print('ready',flush=True)
server.serve_forever()
