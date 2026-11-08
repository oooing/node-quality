"""Persistent favorites, acknowledged IP changes and risk-free latency rechecks."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import MagicMock
import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from service import Service
from store import Store
from test_service import FakeDetector, FakeNetwork


class FavoritesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.service=Service(self.root,Path('unused.exe'),roots=[],start=False,
                             detector=FakeDetector(),network=FakeNetwork())
        self.service.save_settings({'paused':True})
        self.profiles=[self.service.subscriptions.add(name,text=yaml.safe_dump({'proxies':[
            {'name':'香港 01','type':'trojan','server':'example.invalid','port':443+i,'password':'private-config'}]}))
            for i,name in enumerate(('列表一','列表二'))]
        self.nodes=[self.service.subscriptions.nodes(p)[0] for p in self.profiles]
        self.clock=datetime.now(timezone.utc)

    def tearDown(self):self.temp.cleanup()

    def record(self,ip='203.0.113.1',status='ok',**extra):
        self.clock+=timedelta(seconds=1)
        return {'status':status,'ip':ip,'score':12,'checked_at':self.clock.isoformat(),
                'fingerprint':self.nodes[0]['fingerprint'],'route_verified':True,
                'connectivity':{'status':'ok','delay_ms':40},**extra}

    def test_favorites_persist_across_restart_and_span_sources(self):
        for node in self.nodes:self.service.favorite(node['id'],True)
        state=self.service.state(self.profiles[0])
        self.assertEqual(len(state['favorites']),2)
        self.assertTrue(state['nodes'][0]['favorite'])
        self.assertEqual({n['profile_id'] for n in state['favorites']},set(self.profiles))
        self.assertNotIn('private-config',json.dumps(state))
        reopened=Store(self.root/'history.sqlite3')
        self.assertEqual(len(reopened.extras()[0]),2)
        self.service.favorite(self.nodes[0]['id'],False)
        self.assertEqual(len(self.service.state()['favorites']),1)

    def test_removed_line_is_retained_but_cannot_be_checked(self):
        self.service.favorite(self.nodes[0]['id'],True)
        self.service.subscriptions.items[self.profiles[0]]['nodes']=[]
        row=self.service.state()['favorites'][0]
        self.assertTrue(row['missing'])
        self.assertEqual(row['unsupported'],'线路已移除')
        self.service.favorite(row['id'],False)
        self.assertEqual(self.service.state()['favorites'],[])

    def test_changed_ip_alert_survives_stable_rechecks_until_acknowledged(self):
        node=self.nodes[0];store=self.service.store
        store.add(node,self.record())
        self.assertFalse(store.extras()[2])
        changed=store.add(node,self.record('203.0.113.2'))
        self.assertEqual(changed['previous_ip'],'203.0.113.1')
        alert=store.extras()[2][node['id']]
        store.add(node,self.record('203.0.113.2'))
        self.assertEqual(store.extras()[2][node['id']],alert)
        store.acknowledge_ip(node['id'])
        self.assertFalse(store.extras()[2])
        store.add(node,self.record('203.0.113.2'))
        self.assertFalse(store.extras()[2])
        store.add(node,self.record('203.0.113.3'))
        self.assertEqual(store.extras()[2][node['id']]['previous_ip'],'203.0.113.2')

    def test_changed_ip_warns_even_when_risk_lookup_failed(self):
        node=self.nodes[0];self.service.store.add(node,self.record())
        self.service.favorite(node['id'],True)
        self.service.store.add(node,self.record(status='error',observed_ip='203.0.113.9',error='评分查询失败'))
        state=self.service.state(self.profiles[0])
        self.assertEqual(state['favorites'][0]['ip_alert']['current_ip'],'203.0.113.9')
        self.assertEqual(state['nodes'][0]['latest']['ip'],'203.0.113.1')
        self.assertEqual(state['nodes'][0]['rating_state'],'ip_changed')

    def test_old_or_ipless_failure_never_creates_or_clears_alert(self):
        node=self.nodes[0];self.service.store.add(node,self.record())
        self.service.store.add(node,self.record(status='error',observed_ip=None))
        self.assertFalse(self.service.store.extras()[2])
        self.service.store.add(node,self.record('203.0.113.2'))
        alert=self.service.store.extras()[2][node['id']]
        old=self.record('203.0.113.8');old['checked_at']=(self.clock-timedelta(days=2)).isoformat()
        self.service.store.add(node,old)
        self.assertEqual(self.service.store.extras()[2][node['id']],alert)

    def test_latency_recheck_does_not_touch_risk_history_or_ippure_cooldown(self):
        node=self.nodes[0];self.service.store.add(node,self.record())
        before=self.service.store.snapshot()
        self.service.cooldown_until=__import__('time').time()+1000
        until=self.service.cooldown_until
        self.service.detector.check=MagicMock(return_value={'status':'ok','checked_at':self.record()['checked_at'],
            'connectivity':{'status':'ok','delay_ms':77}})
        self.service.enqueue(self.profiles[0],node['id'],latency_only=True)
        self.assertTrue(self.service.step())
        self.service.detector.check.assert_called_once_with(node,latency_only=True)
        self.assertEqual(before,self.service.store.snapshot())
        self.assertEqual(self.service.cooldown_until,until)
        self.assertEqual(self.service.state(self.profiles[0])['nodes'][0]['latency']['connectivity']['delay_ms'],77)

    def test_latency_queue_dedup_and_full_check_upgrades_pending_latency(self):
        node=self.nodes[0]
        self.service.enqueue(self.profiles[0],node['id'],latency_only=True)
        self.service.enqueue(self.profiles[0],node['id'],latency_only=True)
        self.assertEqual(list(self.service.queue),[node['id']])
        self.service.enqueue(self.profiles[0],node['id'])
        self.assertNotIn(node['id'],self.service.latency_ids)


if __name__=='__main__':unittest.main()
