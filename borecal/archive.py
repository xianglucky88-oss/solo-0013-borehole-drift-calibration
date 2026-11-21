"""Create immutable calibration releases and reopen them independently."""
from contextlib import closing
from fractions import Fraction
from hashlib import sha256
import json
import sqlite3

from .contract import decode, key
from .drift import DriftIndex
from .dwell import correct_series, find_windows, summarize_window
from .profile import build, build_dwell

SCHEMA = '''
CREATE TABLE IF NOT EXISTS profile_release (
 borehole TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL,
 source TEXT NOT NULL, profile TEXT NOT NULL, PRIMARY KEY(borehole, version)
);
'''


def _build(doc):
    (site, version, max_span, depths, references, readings,
     stability, dwells, policy, review_of) = decode(doc)
    if dwells:
        profile = build_dwell(depths, references, readings, max_span,
                              stability, dwells, policy)
    else:
        profile = build(depths, references, readings, max_span)
    return {
        'site': site, 'version': version, 'max_span': max_span,
        'depths': depths, 'references': references, 'readings': readings,
        'stability': stability, 'dwells': dwells, 'policy': policy,
        'review_of': review_of, 'profile': profile,
    }


def _evaluate_window(dwell, window_dict, readings, references, max_span,
                     stability, view_until):
    """Re-correct one previously signed window with a chosen reference view."""
    index = DriftIndex(references, max_span)
    points, rejected = correct_series(dwell, readings, index, view_until)
    wanted = {point['at_s'] for point in window_dict['points']}
    points = [point for point in points if point['at_s'] in wanted]
    if len(points) != len(wanted):
        return None, rejected
    spread = (max(point['corrected_mc'] for point in points)
              - min(point['corrected_mc'] for point in points))
    if spread > stability['tolerance_mc']:
        return None, rejected
    rebuilt = {'points': points, 'start_s': window_dict['start_s'],
               'end_s': window_dict['end_s'], 'view_until_s': view_until}
    return summarize_window(rebuilt), rejected


def _references_from_snapshot(window):
    """Rebuild a reference index input from a signed window's frozen view."""
    grouped = {}
    for item in window.get('reference_snapshot', []):
        grouped.setdefault(item['probe'], []).append(
            (item['at_s'], Fraction(item['offset_mc']), item['reference_row']))
    return grouped


def review_release(previous, references, readings, max_span, stability, dwells):
    """Re-check an earlier release against references arriving later.

    Late references can falsify a signed window or support another one; the
    old release itself stays frozen and the findings only appear in the new
    review release, which also names the affected depths and why.
    """
    if previous.get('mode') != 'dwell':
        raise ValueError('reviews require a dwell-mode prior release')
    index = DriftIndex(references, max_span)
    dwell_lookup = {dwell.dwell_id: dwell for dwell in dwells}
    items, affected = [], set()
    for sign in previous['signs']:
        dwell = dwell_lookup.get(sign['dwell_id'])
        item = {'dwell_id': sign['dwell_id'], 'depth_mm': sign['depth_mm'],
                'prior_status': sign['status']}
        if dwell is None:
            item.update(status='dwell_missing', prior_window_holds=None,
                        alternative_window=None,
                        reason='dwell plan no longer present')
            items.append(item)
            affected.add(sign['depth_mm'])
            continue
        if sign['status'] != 'signed':
            points, _ = correct_series(dwell, readings, index, dwell.end_s)
            candidates = find_windows(points, stability)
            alternative = (summarize_window(dict(candidates[0],
                                                  view_until_s=dwell.end_s))
                           if candidates else None)
            item.update(
                status='alternative_supported' if alternative else 'still_unconfirmed',
                prior_window_holds=None, alternative_window=alternative,
                reason=('new references support a window' if alternative
                        else 'no window provable with current references'))
            if alternative:
                affected.add(sign['depth_mm'])
            items.append(item)
            continue
        replay, _ = _evaluate_window(
            dwell, sign['window'], readings,
            _references_from_snapshot(sign['window']), max_span,
            stability, sign['signed_at_s'])
        current, _ = _evaluate_window(
            dwell, sign['window'], readings, references, max_span,
            stability, dwell.end_s)
        points_all, _ = correct_series(dwell, readings, index, dwell.end_s)
        alternative = None
        for candidate in find_windows(points_all, stability):
            if (candidate['start_s'] == sign['window']['start_s']
                    and candidate['end_s'] == sign['window']['end_s']):
                continue
            alternative = summarize_window(
                dict(candidate, view_until_s=dwell.end_s))
            break
        if current is not None:
            status = ('alternative_also_supported' if alternative
                      else 'supported')
            reason = 'signed window still holds under current references'
        else:
            status = 'falsified'
            reason = 'late references break the signed window calibration'
            affected.add(sign['depth_mm'])
        if alternative is not None:
            affected.add(sign['depth_mm'])
        item.update(status=status, prior_window_holds=current is not None,
                    replay_with_original_view_holds=replay is not None,
                    alternative_window=alternative, reason=reason,
                    prior_window=sign['window'])
        items.append(item)
    return {'reviewed': items,
            'affected_depths_mm': sorted(affected),
            'affected_depth_facts': [fact for fact in previous['depths']
                                     if fact['depth_mm'] in affected]}


def publish(path, doc):
    parts = _build(doc)
    site, version = parts['site'], parts['version']
    result = parts['profile']
    raw = json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False)
    digest = sha256(raw.encode()).hexdigest()
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(SCHEMA)
        conn.execute('BEGIN IMMEDIATE')
        saved = conn.execute(
            'SELECT digest, profile FROM profile_release WHERE borehole=? AND version=?',
            (site, version)).fetchone()
        if saved:
            if saved[0] != digest:
                raise ValueError('calibration version is immutable')
            return {'status': 'replay', 'sha256': digest}
        review_of = parts['review_of']
        if review_of is not None:
            prior_row = conn.execute(
                'SELECT profile FROM profile_release WHERE borehole=? AND version=?',
                (review_of['borehole'], review_of['version'])).fetchone()
            if prior_row is None:
                raise ValueError('review references an unknown calibration version')
            prior = json.loads(prior_row[0])
            review = review_release(
                prior, parts['references'], parts['readings'],
                parts['max_span'], parts['stability'], parts['dwells'])
            result['review'] = dict(review_of=review_of, **review)
        conn.execute('INSERT INTO profile_release VALUES(?,?,?,?,?)',
                     (site, version, digest, raw, json.dumps(result)))
    return {'status': 'published', 'sha256': digest}


def read_profile(path, borehole, version):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(SCHEMA)
        saved = conn.execute('SELECT digest, profile FROM profile_release WHERE borehole=? AND version=?',
                             (key(borehole), key(version))).fetchone()
    if not saved:
        raise ValueError('unknown calibration version')
    return {'sha256': saved[0], **json.loads(saved[1])}
