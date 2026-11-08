"""Small local history store, with the last successful result kept on failure."""
import json
import ipaddress
import sqlite3
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

KEEP = 10


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(node_id, checked_at)
                );
                CREATE INDEX IF NOT EXISTS checks_node ON checks(node_id, checked_at DESC);
                CREATE TABLE IF NOT EXISTS latest (
                    node_id TEXT PRIMARY KEY,
                    checked_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ping0_checks (
                    id INTEGER PRIMARY KEY,
                    job_id TEXT NOT NULL UNIQUE,
                    node_id TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    applied_to_current INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ping0_checks_node ON ping0_checks(node_id, checked_at DESC);
                CREATE TABLE IF NOT EXISTS favorites (node_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS latency (node_id TEXT PRIMARY KEY, checked_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ip_watch (
                    node_id TEXT PRIMARY KEY, ip TEXT NOT NULL, checked_at TEXT NOT NULL,
                    old_ip TEXT, changed_at TEXT, acknowledged INTEGER NOT NULL DEFAULT 1
                );
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, node, record):
        record = dict(record, node_id=node['id'], node_name=node['name'],
                      source='IPPure + Ping0' if record.get('ping0') else 'IPPure')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT payload FROM latest WHERE node_id=?', (node['id'],)).fetchone()
            previous = json.loads(previous[0]) if previous else None
            if record.get('connectivity'):
                self._save_latency(db, node['id'], record)
            record['ip_changed'] = None
            record['score_delta'] = None
            if record['status'] == 'ok' and previous and record['checked_at'] > previous['checked_at']:
                record['ip_changed'] = record['ip'] != previous['ip']
                record['score_delta'] = record['score'] - previous['score']
            self._observe_ip(db, node['id'], record, previous)
            previous_ping0 = previous.get('ping0_latest') if previous else None
            ping0 = record.get('ping0')
            if ping0:
                ping0 = dict(ping0, ip_changed=None, score_delta=None)
                if ping0['status'] == 'ok' and previous_ping0 and ping0['checked_at'] > previous_ping0['checked_at']:
                    ping0['ip_changed'] = ping0['ip'] != previous_ping0['ip']
                    ping0['score_delta'] = ping0['score'] - previous_ping0['score']
                record['ping0'] = ping0
            encoded = json.dumps(record, ensure_ascii=False)
            db.execute('INSERT OR IGNORE INTO checks(node_id,checked_at,payload) VALUES(?,?,?)',
                       (node['id'], record['checked_at'], encoded))
            if record['status'] == 'ok':
                latest = dict(record, ping0_latest=ping0 if ping0 and ping0['status'] == 'ok' else previous_ping0)
                db.execute('''INSERT INTO latest VALUES(?,?,?) ON CONFLICT(node_id) DO UPDATE
                              SET checked_at=excluded.checked_at,payload=excluded.payload
                              WHERE excluded.checked_at > latest.checked_at''',
                           (node['id'], record['checked_at'], json.dumps(latest, ensure_ascii=False)))
            db.execute('''DELETE FROM checks WHERE node_id=? AND id NOT IN
                          (SELECT id FROM checks WHERE node_id=? ORDER BY checked_at DESC,id DESC LIMIT ?)''',
                       (node['id'], node['id'], KEEP))
        return record

    def _observe_ip(self, db, node_id, record, previous):
        address = record.get('observed_ip') or (record.get('ip') if record['status'] == 'ok' else None)
        try:
            address = str(ipaddress.IPv4Address(address))
        except (ValueError, TypeError):
            return
        row = db.execute('SELECT ip,checked_at FROM ip_watch WHERE node_id=?', (node_id,)).fetchone()
        old_ip, old_time = row if row else ((previous or {}).get('ip'), (previous or {}).get('checked_at'))
        if old_time and datetime.fromisoformat(record['checked_at']) <= datetime.fromisoformat(old_time):
            return
        changed = bool(old_ip and old_ip != address)
        if changed:
            record['previous_ip'] = old_ip
            record['ip_changed'] = True
            db.execute('''INSERT INTO ip_watch VALUES(?,?,?,?,?,0) ON CONFLICT(node_id) DO UPDATE SET
                ip=excluded.ip,checked_at=excluded.checked_at,old_ip=excluded.old_ip,
                changed_at=excluded.changed_at,acknowledged=0''',
                (node_id,address,record['checked_at'],old_ip,record['checked_at']))
        else:
            db.execute('''INSERT INTO ip_watch(node_id,ip,checked_at) VALUES(?,?,?)
                ON CONFLICT(node_id) DO UPDATE SET ip=excluded.ip,checked_at=excluded.checked_at''',
                (node_id,address,record['checked_at']))

    def set_favorite(self, node, saved):
        with self.connect() as db:
            if saved:
                public = {k:node[k] for k in ('id','name','profile_id','profile_name','client','type')}
                db.execute('INSERT INTO favorites VALUES(?,?) ON CONFLICT(node_id) DO UPDATE SET payload=excluded.payload',
                           (node['id'],json.dumps(public,ensure_ascii=False)))
            else:
                db.execute('DELETE FROM favorites WHERE node_id=?', (node['id'],))

    def extras(self):
        with self.connect() as db:
            favorites = {key:json.loads(value) for key,value in db.execute('SELECT * FROM favorites')}
            latency = {key:json.loads(value) for key,_,value in db.execute('SELECT * FROM latency')}
            alerts = {key:{'previous_ip':old,'current_ip':ip,'checked_at':at}
                      for key,ip,old,at in db.execute('SELECT node_id,ip,old_ip,changed_at FROM ip_watch WHERE acknowledged=0')}
        return favorites,latency,alerts

    def acknowledge_ip(self, node_id):
        with self.connect() as db:
            db.execute('UPDATE ip_watch SET acknowledged=1 WHERE node_id=?', (node_id,))

    def _save_latency(self, db, node_id, record):
        row = db.execute('SELECT checked_at FROM latency WHERE node_id=?', (node_id,)).fetchone()
        if row and datetime.fromisoformat(record['checked_at']) <= datetime.fromisoformat(row[0]):
            return
        db.execute('INSERT OR REPLACE INTO latency VALUES(?,?,?)',
                   (node_id,record['checked_at'],json.dumps(record,ensure_ascii=False)))

    def add_latency(self, node, record):
        with self.connect() as db:
            self._save_latency(db, node['id'], record)

    def add_ping0(self, node_id, target_ip, based_on_checked_at, result, job_id):
        """Save a browser supplement without creating or refreshing an IPPure check."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload,applied_to_current FROM ping0_checks WHERE job_id=?',
                                  (job_id,)).fetchone()
            if existing:
                return {'record': json.loads(existing[0]), 'applied_to_current': bool(existing[1])}
            if result['ip'] != target_ip:
                raise ValueError('Ping0 result does not match the requested IP')
            record = dict(result, status='ok', node_id=node_id,
                          based_on_checked_at=based_on_checked_at, job_id=job_id)
            row = db.execute('SELECT payload FROM latest WHERE node_id=?', (node_id,)).fetchone()
            latest = json.loads(row[0]) if row else None
            applied = False
            if latest and latest.get('ip') == target_ip:
                previous = latest.get('ping0_latest')
                if (not previous or previous.get('ip') != target_ip
                        or datetime.fromisoformat(record['checked_at'])
                        >= datetime.fromisoformat(previous['checked_at'])):
                    latest['ping0_latest'] = record
                    db.execute('UPDATE latest SET payload=? WHERE node_id=?',
                               (json.dumps(latest, ensure_ascii=False), node_id))
                    applied = True
            db.execute('''INSERT INTO ping0_checks(job_id,node_id,checked_at,applied_to_current,payload)
                          VALUES(?,?,?,?,?)''',
                       (job_id, node_id, record['checked_at'], int(applied), json.dumps(record, ensure_ascii=False)))
            db.execute('''DELETE FROM ping0_checks WHERE node_id=? AND id NOT IN
                          (SELECT id FROM ping0_checks WHERE node_id=? ORDER BY checked_at DESC,id DESC LIMIT ?)''',
                       (node_id, node_id, KEEP))
        return {'record': record, 'applied_to_current': applied}

    def ping0_history(self, node_id):
        with self.connect() as db:
            rows = db.execute('''SELECT payload FROM ping0_checks WHERE node_id=?
                                 ORDER BY checked_at DESC,id DESC LIMIT ?''', (node_id, KEEP)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def history(self, key):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM checks WHERE node_id=? ORDER BY checked_at DESC,id DESC LIMIT ?',
                              (key, KEEP)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def snapshot(self):
        with self.connect() as db:
            latest = {key: json.loads(payload) for key, payload in db.execute('SELECT node_id,payload FROM latest')}
            attempts = {}
            counts = {}
            for key, payload in db.execute('SELECT node_id,payload FROM checks ORDER BY checked_at DESC,id DESC'):
                counts[key] = counts.get(key, 0) + 1
                if key not in attempts:
                    attempts[key] = json.loads(payload)
        return latest, attempts, counts

    def histories(self, keys):
        keys = set(keys)
        result = {key: [] for key in keys}
        with self.connect() as db:
            for key, payload in db.execute('SELECT node_id,payload FROM checks ORDER BY checked_at DESC,id DESC'):
                if key in keys:
                    result[key].append(json.loads(payload))
        return result

    def import_validation(self, path, nodes):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        by_name = {node['name']: node for node in nodes}
        count = 0
        for name, records in data.get('nodes', {}).items():
            if name not in by_name:
                continue
            for row in sorted(records, key=lambda item: item['checked_at']):
                if row.get('status') != 'ok':
                    continue
                self.add(by_name[name], {'checked_at': row['checked_at'], 'status': 'ok',
                         'ip': row['ip'], 'score': row['fraudScore'],
                         'country': row.get('country'), 'city': row.get('city'),
                         'asn': row.get('asn'), 'is_residential': row.get('isResidential'),
                         'is_broadcast': row.get('isBroadcast'), 'elapsed_seconds': row.get('elapsed_seconds'),
                         'route_verified': bool(row.get('route_evidence') or row.get('route_log_evidence'))})
                count += 1
        return count
