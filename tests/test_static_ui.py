"""Serve built React assets without exposing local data or bypassing API auth."""
import http.client
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from main import handler


class StaticUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.ui = cls.root / 'ui'
        (cls.ui / 'assets').mkdir(parents=True)
        (cls.ui / 'index.html').write_text('<html>云鉴<script type="module" src="/assets/app-123.js"></script></html>', encoding='utf-8')
        (cls.ui / 'assets' / 'app-123.js').write_text('export const ready = true;', encoding='utf-8')
        (cls.ui / 'assets' / 'chunk-456.js').write_text('export default 1;', encoding='utf-8')
        (cls.ui / 'assets' / 'theme-123.css').write_text('body{color:#226e60}', encoding='utf-8')
        (cls.root / 'private.txt').write_text('not public', encoding='utf-8')
        (cls.ui / 'settings.json').write_text('not an asset', encoding='utf-8')
        cls.service = Mock()
        cls.service.state.return_value = {'version': '0.3.0', 'nodes': []}
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(cls.service, 'fixture-token', cls.ui))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            conn.request('GET', path, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_built_entry_and_split_modules_are_public_assets(self):
        for path, mime in [('/', 'text/html'), ('/index.html', 'text/html'),
                           ('/assets/app-123.js', 'text/javascript'),
                           ('/assets/chunk-456.js?version=1', 'text/javascript'),
                           ('/assets/theme-123.css', 'text/css')]:
            with self.subTest(path=path):
                status, headers, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertTrue(headers['Content-Type'].startswith(mime))
                self.assertTrue(body)
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')

    def test_unknown_asset_returns_404_without_killing_server(self):
        for path in ('/assets/missing.js', '/assets/', '/favicon.ico'):
            self.assertEqual(self.get(path)[0], 404)
        self.assertEqual(self.get('/')[0], 200)

    def test_asset_traversal_cannot_read_parent_or_other_ui_files(self):
        for path in ('/assets/../../private.txt', '/assets/%2e%2e/%2e%2e/private.txt',
                     '/assets/..%5c..%5cprivate.txt', '/assets/../settings.json'):
            with self.subTest(path=path):
                status, _, body = self.get(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b'not public', body)
                self.assertNotIn(b'not an asset', body)

    def test_api_still_requires_correct_token_and_same_origin(self):
        self.assertEqual(self.get('/api/state')[0], 403)
        self.assertEqual(self.get('/api/state', {'X-App-Token': 'incorrect'})[0], 403)
        self.assertEqual(self.get('/api/state', {'X-App-Token': 'fixture-token', 'Origin': 'https://example.invalid'})[0], 403)
        status, _, body = self.get('/api/state', {'X-App-Token': 'fixture-token'})
        self.assertEqual(status, 200)
        self.assertIn(b'0.3.0', body)

    def test_inline_styles_supported_but_inline_scripts_remain_blocked(self):
        _, headers, _ = self.get('/')
        directives = {part.strip().split(' ', 1)[0]: part.strip() for part in headers['Content-Security-Policy'].split(';')}
        self.assertIn("'unsafe-inline'", directives['style-src'])
        self.assertEqual(directives['script-src'], "script-src 'self'")
        self.assertEqual(directives['connect-src'], "connect-src 'self'")


if __name__ == '__main__':
    unittest.main()
