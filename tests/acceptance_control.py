"""Real core without official GUI must refuse an unsaved switch. No outbound probes."""
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from clash_control import ClashControl, LocalController
from subscriptions import Subscriptions
from catalog import PanelError


def main():
    engine = ROOT/'resources/engine/mihomo.exe'
    if not engine.is_file():
        raise SystemExit('Run scripts/fetch_engine.py first')
    with tempfile.TemporaryDirectory(prefix='node-quality-control-') as temp:
        directory = Path(temp)
        (directory/'profiles').mkdir()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        config = {'external-controller': f'127.0.0.1:{port}', 'secret': secrets.token_urlsafe(24),
                  'mode': 'rule', 'allow-lan': False, 'tun': {'enable': False}, 'dns': {'enable': False},
                  'find-process-mode': 'off', 'log-level': 'silent', 'geo-auto-update': False,
                  'proxies': [dict(name=name,type='http',server='127.0.0.1',port=1) for name in ('A','B')],
                  'proxy-groups': [dict(name=name,type='select',proxies=['A','B']) for name in ('Test / AI','Unchanged')],
                  'rules': ['MATCH,DIRECT']}
        raw = yaml.safe_dump(config)
        (directory/'clash-verge.yaml').write_text(raw,encoding='utf-8')
        (directory/'profiles'/'test.yaml').write_text(raw,encoding='utf-8')
        (directory/'profiles.yaml').write_text(yaml.safe_dump({'current':'test','items':[
            dict(uid='test',type='local',name='Local test',file='test.yaml')]}),encoding='utf-8')
        process = subprocess.Popen([str(engine),'-d',temp,'-f',str(directory/'clash-verge.yaml')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            controller = LocalController(config)
            for _ in range(100):
                try:
                    controller.request('GET','/version')
                    break
                except Exception:
                    if process.poll() is not None:
                        raise RuntimeError('Isolated Mihomo exited')
                    time.sleep(.1)
            subscriptions = Subscriptions(directory/'data',roots=[directory])
            profile = subscriptions.public()[0]['id']
            nodes = subscriptions.nodes(profile)
            control = ClashControl(subscriptions)
            before = controller.request('GET','/proxies')['proxies']
            assert control.status(profile)['can_switch']
            try:
                control.select(profile,next(n['id'] for n in nodes if n['name']=='B'),'Test / AI')
                raise AssertionError('A core without the official GUI must not report durable switching')
            except PanelError:
                pass
            after = controller.request('GET','/proxies')['proxies']
            assert before['Test / AI']['now']==after['Test / AI']['now']=='A'
            assert before['Unchanged']['now']==after['Unchanged']['now']
            assert before['GLOBAL']['now']==after['GLOBAL']['now']
            assert (directory/'clash-verge.yaml').read_text(encoding='utf-8')==raw
            print('PASS: core without supported GUI refused switch; all selectors/config remained unchanged.')
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__=='__main__':
    main()
