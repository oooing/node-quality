"""Smoke-test the built Windows shell with empty, isolated app-data directories.

Never import real subscriptions, start a detector, or operate the live Clash app.
The temporary WebView debug port is local to this owned test process.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / 'test-results' / 'packaged-033'
    output.mkdir(parents=True, exist_ok=True)
    executable = ROOT / 'src-tauri/target/release/node-quality.exe'
    assert executable.is_file(), 'Build the desktop first'
    with tempfile.TemporaryDirectory(prefix='runtime-', dir=output) as temporary:
        runtime = Path(temporary)
        for name in ('roaming', 'local', 'data', 'webview'):
            (runtime / name).mkdir()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, APPDATA=str(runtime / 'roaming'),
                   LOCALAPPDATA=str(runtime / 'local'),
                   NODEQUALITY_DATA_DIR=str(runtime / 'data'), NODEQUALITY_PAUSED='1',
                   WEBVIEW2_USER_DATA_FOLDER=str(runtime / 'webview'),
                   WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={port}')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        process = subprocess.Popen([str(executable)], env=env, startupinfo=startup)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        endpoint = f'http://127.0.0.1:{port}'
        try:
            deadline = time.monotonic() + 45
            while True:
                assert process.poll() is None, 'Desktop exited before its WebView was ready'
                try:
                    with opener.open(endpoint + '/json/version', timeout=1):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise AssertionError('WebView startup timed out')
                    time.sleep(.2)
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(endpoint)
                context = browser.contexts[0]
                deadline = time.monotonic() + 15
                while not context.pages and time.monotonic() < deadline:
                    time.sleep(.1)
                page = context.pages[0]
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                expect(page.locator('.production-app')).to_be_visible(timeout=20000)
                assert page.title() == '云鉴'
                state = page.evaluate("""async () => (await fetch('/api/state', {
                    headers: {'X-App-Token':sessionStorage.getItem('app-token')}})).json()""")
                assert state['version'] == '0.3.3'
                assert state['profiles'] == [] and state['favorites'] == []
                assert state['settings']['paused'] is True
                assert not state['activity']['active_id']
                page.get_by_role('button', name='线路管理', exact=True).click()
                expect(page.get_by_role('dialog')).to_be_visible()
                expect(page.get_by_role('textbox', name='列表名称', exact=True)).to_be_visible()
                page.keyboard.press('Escape')
                expect(page.get_by_role('dialog')).not_to_be_visible()
                page.screenshot(path=str(output / 'windows-shell.png'))
                assert not errors, errors
                (output / 'result.json').write_text(json.dumps({
                    'version': state['version'], 'desktop_shell': True,
                    'packaged_backend': True, 'packaged_ui': True,
                    'empty_isolated_data': True, 'paused': True,
                    'dialog_keyboard': True, 'page_errors': errors,
                    'live_clash_operations': 0}, ensure_ascii=False, indent=2), encoding='utf-8')
                browser.close()
            print('PASS: Windows shell, packaged backend/UI, empty isolated data, dialog + Escape.')
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)
            # WebView child processes release their profile files after the owned job closes.
            time.sleep(2)


if __name__ == '__main__':
    main()
