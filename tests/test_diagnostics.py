"""Failure categories reflect evidence, persist to history, and use isolated sockets."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from catalog import QueryBlocked
from detector import Detector
from diagnostics import FailureDiagnostics, log_cause, transport_probe
from store import Store


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.node = {'id': 'fixture', 'name': 'fixture', 'unsupported': '',
            'config': {'name': 'fixture', 'type': 'anytls', 'server': 'example.invalid',
                       'port': 443, 'password': 'never-persist-this-secret'}}
        self.detector = Detector(sys.executable, self.root/'runtime')
        self.detector.interface = 'fixture-interface'
        self.detector.interface_index = 7

    def tearDown(self):
        self.temp.cleanup()

    def run_core(self, connection, request=None, logs='', diagnostics=None, latency_only=False):
        process = MagicMock()
        process.poll.return_value = None
        def start(args, **kwargs):
            config = (Path(args[-1])).read_text(encoding='utf-8')
            self.assertIn('enable: false', config)
            self.assertIn('MATCH,REJECT', config)
            self.assertIn('fixture-interface', config)
            kwargs['stdout'].write(logs)
            kwargs['stdout'].flush()
            return process
        if diagnostics is not None:
            self.detector.diagnostics = diagnostics
        with patch('detector.subprocess.Popen', side_effect=start), \
             patch('detector.requests.Session') as session, \
             patch('detector.check_connectivity', return_value=connection), \
             patch.object(self.detector, '_request', side_effect=request):
            session.return_value.__enter__.return_value.get.return_value.ok = True
            record = self.detector.check(self.node, latency_only=latency_only)
            if latency_only and connection.get('status')=='ok':
                self.detector._request.assert_not_called()
        process.terminate.assert_called_once()
        self.assertEqual(list(self.detector.runtime.iterdir()), [])
        return record

    def test_latency_only_stops_before_ip_and_risk_requests(self):
        result=self.run_core({'status':'ok','delay_ms':42},latency_only=True)
        self.assertEqual(result['status'],'ok')
        self.assertNotIn('ip',result)
        self.assertNotIn('score',result)

    def test_eof_tls_diagnosis_survives_temp_cleanup_and_history(self):
        logs = 'level=warning msg="[TCP] dial user-secret error: failed to create session: EOF"\n'
        with patch('diagnostics.transport_probe', return_value={'tcp':'ok','tls':'closed'}) as probe:
            result = self.run_core({'status':'error','attempts':[{'http_status':503}]*2}, logs=logs)
        probe.assert_called_once()
        self.assertEqual(result['diagnosis']['code'], 'tls_closed')
        self.assertEqual(result['diagnosis']['category'], 'line')
        self.assertNotIn('user-secret', json.dumps(result))
        self.assertNotIn('never-persist', json.dumps(result))
        store = Store(self.root/'history.sqlite3')
        store.add(self.node, result)
        self.assertEqual(store.history('fixture')[0]['diagnosis'], result['diagnosis'])

    def test_generic_delay_503_is_not_mislabeled_as_eof_or_website_503(self):
        with patch('diagnostics.requests.Session') as session:
            result = self.run_core({'status':'error'})
            # Shared Session mock also serves only the loopback readiness endpoint.
        self.assertEqual(result['diagnosis']['category'], 'unknown')
        self.assertEqual(result['diagnosis']['code'], 'connectivity_failed')

    def test_score_site_failure_retains_working_connection(self):
        result = self.run_core({'status':'ok','delay_ms':45}, request=QueryBlocked('评分网站限制查询',kind='rate_limit'))
        self.assertTrue(result['service_blocked'])
        self.assertEqual(result['diagnosis']['category'], 'site')
        self.assertEqual(result['connectivity']['status'], 'ok')

    def test_diagnostic_failure_preserves_original_error_as_unknown(self):
        diagnostics = MagicMock()
        diagnostics.inspect.side_effect = OSError('optional probe failed')
        result = self.run_core({'status':'timeout'}, diagnostics=diagnostics)
        self.assertEqual(result['diagnosis']['code'], 'diagnosis_incomplete')
        self.assertIn('两个测试网站都连接超时', result['diagnosis']['detail'])

    def test_missing_engine_is_local_without_network_calls(self):
        self.detector.core = self.root/'missing.exe'
        with patch('diagnostics.requests.Session') as request:
            result = self.detector.check(self.node)
        self.assertEqual(result['diagnosis']['category'], 'local')
        self.assertEqual(result['diagnosis']['code'], 'engine_missing')
        request.assert_not_called()

    def test_local_process_error_after_connectivity_is_not_blamed_on_site(self):
        result = self.run_core({'status':'ok','delay_ms':45}, request=FileNotFoundError('curl missing'))
        self.assertEqual(result['diagnosis']['category'], 'local')
        self.assertEqual(result['diagnosis']['code'], 'process_failed')
        self.assertEqual(result['connectivity']['status'], 'ok')

    def test_known_log_errors_do_not_infer_auth_failure_from_eof(self):
        self.assertEqual(log_cause('level=warning error: failed to create session: EOF'), 'eof')
        self.assertEqual(log_cause('level=warning error: authentication failed'), 'auth')
        self.assertEqual(log_cause('level=warning error: tls: x509: certificate has expired'), 'certificate')
        self.assertEqual(log_cause('level=warning error: connection refused'), 'refused')
        self.assertIsNone(log_cause('EOF is in a node name, not in an error'))

    @unittest.skipUnless(os.name == 'nt', 'Windows physical adapter binding')
    def test_failed_interface_bind_never_falls_back_to_default_route(self):
        with patch('diagnostics.socket.getaddrinfo', return_value=[(2,1,6,'',('203.0.113.1',443))]), \
             patch('diagnostics.socket.socket') as socket:
            raw = socket.return_value.__enter__.return_value
            raw.setsockopt.side_effect = OSError('adapter unavailable')
            result = transport_probe(self.node['config'], 'fixture', 7)
        self.assertIn('skipped', result)
        raw.connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
