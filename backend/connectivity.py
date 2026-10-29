"""URL tests on the panel's isolated Mihomo controller, never the user's selector."""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

TARGETS = ('https://cp.cloudflare.com/generate_204', 'https://www.gstatic.com/generate_204')
TIMEOUT_MS = 5000


def check_connectivity(control, port, name):
    result = {'status': 'error', 'delay_ms': None,
              'checked_at': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='milliseconds'),
              'timeout_ms': TIMEOUT_MS, 'attempts': []}
    for target in TARGETS:
        attempt = {'url': target, 'status': 'error'}
        try:
            response = control.get(f'http://127.0.0.1:{port}/proxies/{quote(name, safe="")}/delay',
                                   params={'url': target, 'timeout': TIMEOUT_MS, 'expected': '204'},
                                   timeout=(1, TIMEOUT_MS / 1000 + 2))
            attempt['http_status'] = response.status_code
            if response.status_code == 200:
                delay = response.json().get('delay')
                if isinstance(delay, (int, float)) and not isinstance(delay, bool) and 0 < delay < TIMEOUT_MS:
                    attempt.update(status='ok', delay_ms=delay)
            elif response.status_code == 504:
                attempt['status'] = 'timeout'
        except requests.Timeout:
            attempt['status'] = 'timeout'
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            pass
        result['attempts'].append(attempt)
        if attempt['status'] == 'ok':
            result.update(status='ok', delay_ms=attempt['delay_ms'], test_url=target)
            break
    else:
        if all(item['status'] == 'timeout' for item in result['attempts']):
            result['status'] = 'timeout'
    return result
