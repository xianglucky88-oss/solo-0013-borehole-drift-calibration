"""Create immutable calibration releases and reopen them independently."""
from contextlib import closing
from hashlib import sha256
import json
import sqlite3

from .contract import decode, key
from .profile import build, build_certified

SCHEMA = '''
CREATE TABLE IF NOT EXISTS profile_release (
 borehole TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL,
 source TEXT NOT NULL, profile TEXT NOT NULL, kind TEXT NOT NULL,
 PRIMARY KEY(borehole, version)
);
CREATE TABLE IF NOT EXISTS delivery_ledger (
 borehole TEXT NOT NULL, version TEXT NOT NULL, request TEXT NOT NULL,
 response TEXT NOT NULL, PRIMARY KEY(borehole, version, request)
);
'''


def publish(path, doc):
    (site, version, max_span, depths, reference, readings,
     certificates, hypotheses, width_limit, requests) = decode(doc)
    raw = json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False)
    digest = sha256(raw.encode()).hexdigest()
    if certificates:
        kind = 'certified'
        result = build_certified(depths, reference, readings, max_span,
                                 certificates, hypotheses, width_limit, requests)
    else:
        kind = 'direct'
        result = build(depths, reference, readings, max_span)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.execute('BEGIN IMMEDIATE')
        saved = conn.execute(
            'SELECT digest FROM profile_release WHERE borehole=? AND version=?',
            (site, version)).fetchone()
        if saved:
            if saved[0] != digest:
                raise ValueError('calibration version is immutable')
            return {'status': 'replay', 'sha256': digest, 'kind': kind}
        conn.execute('INSERT INTO profile_release VALUES(?,?,?,?,?,?)',
                     (site, version, digest, raw, json.dumps(result), kind))
        if kind == 'certified':
            for response in result['delivery']:
                conn.execute(
                    'INSERT INTO delivery_ledger VALUES(?,?,?,?)',
                    (site, version, response['request'], json.dumps(response)))
    return {'status': 'published', 'sha256': digest, 'kind': kind}


def read_profile(path, borehole, version):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
        saved = conn.execute(
            'SELECT digest, profile, kind FROM profile_release WHERE borehole=? AND version=?',
            (key(borehole), key(version))).fetchone()
    if not saved:
        raise ValueError('unknown calibration version')
    digest, profile_json, kind = saved
    return {'sha256': digest, 'kind': kind, **json.loads(profile_json)}


def read_delivery(path, borehole, version):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
        rows = conn.execute(
            'SELECT response FROM delivery_ledger WHERE borehole=? AND version=? ORDER BY request',
            (key(borehole), key(version))).fetchall()
        exists = conn.execute(
            'SELECT 1 FROM profile_release WHERE borehole=? AND version=?',
            (key(borehole), key(version))).fetchone()
    if not exists:
        raise ValueError('unknown calibration version')
    return [json.loads(row[0]) for row in rows]
