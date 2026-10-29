"""Loopback-only UI host, bundled by PyInstaller and owned by the desktop process."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sys
import threading
from urllib.parse import parse_qs, urlsplit

from catalog import PanelError
from service import Service


def handler(service, token, ui):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, payload, status=200, content_type='application/json; charset=utf-8'):
            body = json.dumps(payload, ensure_ascii=False).encode() if isinstance(payload, (dict, list)) else payload
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (ConnectionError, OSError):
                pass

        def authorized(self):
            expected = f'127.0.0.1:{self.server.server_port}'
            origin = self.headers.get('Origin')
            return (self.headers.get('Host') == expected and
                    (not origin or origin == 'http://' + expected) and
                    hmac.compare_digest(self.headers.get('X-App-Token', ''), token))

        def do_GET(self):
            route = urlsplit(self.path)
            if route.path in ('/', '/app.js', '/style.css'):
                file = ui / ('index.html' if route.path == '/' else route.path[1:])
                self.send(file.read_bytes(), content_type=(mimetypes.guess_type(str(file))[0] or 'text/plain') + '; charset=utf-8')
                return
            if not self.authorized():
                self.send({'error': '请从桌面应用打开。'}, 403)
                return
            query = parse_qs(route.query)
            if route.path == '/api/state':
                self.send(service.state(query.get('profile', [None])[0]))
            elif route.path == '/api/history':
                self.send(service.store.history(query.get('node', [''])[0]))
            else:
                self.send({'error': '未找到该功能。'}, 404)

        def do_POST(self):
            if not self.authorized():
                self.send({'error': '请从桌面应用打开。'}, 403)
                return
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 8 * 1024 * 1024:
                    raise PanelError('请求大小不正确。')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise PanelError('请求格式不正确。')
                if self.path == '/api/settings':
                    service.save_settings(data)
                elif self.path == '/api/check':
                    service.enqueue(data.get('profile_id'), data.get('node_id'))
                elif self.path == '/api/refresh':
                    service.refresh(data['profile_id'])
                elif self.path == '/api/enable':
                    service.subscriptions.enable(data['ids'])
                elif self.path == '/api/discover':
                    service.subscriptions.scan(data.get('directory'))
                elif self.path == '/api/add':
                    service.subscriptions.add(data.get('name'), data.get('url', ''), data.get('text', ''))
                elif self.path == '/api/clear-queue':
                    with service.lock:
                        service.queue.clear()
                else:
                    self.send({'error': '未找到该功能。'}, 404)
                    return
                service.wake.set()
                self.send({'ok': True})
            except (PanelError, ValueError) as error:
                self.send({'error': str(error)}, 400)
            except (KeyError, TypeError):
                self.send({'error': '请求缺少必要信息。'}, 400)
            except Exception:
                self.send({'error': '操作未完成，请重试。'}, 500)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'NodeQuality')
    parser.add_argument('--core', type=Path, required=True)
    parser.add_argument('--ui', type=Path, required=True)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--paused', action='store_true')
    args = parser.parse_args()
    service = Service(args.data_dir, args.core, start=False)
    if args.paused:
        service.save_settings({'paused': True})
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(service, token, args.ui))
    server.daemon_threads = True
    service.thread = threading.Thread(target=service.run, daemon=True)
    service.thread.start()
    print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/#token={token}'}), flush=True)
    def shutdown_on_stdin():
        sys.stdin.readline()
        service.close()
        server.shutdown()
    threading.Thread(target=shutdown_on_stdin, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        service.close()
        server.server_close()


if __name__ == '__main__':
    main()
