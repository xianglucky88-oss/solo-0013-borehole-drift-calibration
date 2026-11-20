"""Create immutable calibration releases and reopen them independently."""
from contextlib import closing
from hashlib import sha256
import json
import sqlite3

from .contract import decode, key
from .profile import build

SCHEMA = '''
CREATE TABLE IF NOT EXISTS profile_release (
 borehole TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL,
 source TEXT NOT NULL, profile TEXT NOT NULL, PRIMARY KEY(borehole, version)
);
'''


def publish(path, doc):
    site, version, max_span, depths, reference, readings = decode(doc)
    raw = json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False)
    digest = sha256(raw.encode()).hexdigest()
    result = build(depths, reference, readings, max_span)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(SCHEMA)
        conn.execute('BEGIN IMMEDIATE')
        saved = conn.execute('SELECT digest FROM profile_release WHERE borehole=? AND version=?', (site, version)).fetchone()
        if saved:
            if saved[0] != digest:
                raise ValueError('calibration version is immutable')
            return {'status': 'replay', 'sha256': digest}
        conn.execute('INSERT INTO profile_release VALUES(?,?,?,?,?)', (site, version, digest, raw, json.dumps(result)))
    return {'status': 'published', 'sha256': digest}


def read_profile(path, borehole, version):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(SCHEMA)
        saved = conn.execute('SELECT digest, profile FROM profile_release WHERE borehole=? AND version=?',
                             (key(borehole), key(version))).fetchone()
    if not saved:
        raise ValueError('unknown calibration version')
    return {'sha256': saved[0], **json.loads(saved[1])}
