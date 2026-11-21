"""Normalize survey plans, instrument references, probe readings, and dwells."""
from collections import defaultdict

from .dwell import Dwell

SIGN_POLICIES = ('first_window', 'dwell_end')


def key(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise ValueError('invalid dataset or probe identifier')
    return value


def integer(value, name, minimum=0, maximum=10**12):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'invalid {name}')
    return value


def temperature(value):
    return integer(value, 'temperature in millidegrees', -100_000, 250_000)


def _decode_stability(doc):
    block = doc.get('stability')
    if block is None:
        return None
    if not isinstance(block, dict):
        raise ValueError('stability must be an object')
    return {
        'stable_duration_s': integer(block['stable_duration_s'], 'stable duration', 1),
        'tolerance_mc': integer(block['tolerance_mc'], 'stability tolerance', 0),
        'sampling_interval_s': integer(block['sampling_interval_s'], 'sampling interval', 1),
    }


def _decode_dwells(doc, depth_set):
    raw = doc.get('dwells')
    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        raise ValueError('dwells must be a nonempty array')
    dwells, seen_ids, seen_orders = [], set(), set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('invalid dwell entry')
        dwell_id = key(item['dwell_id'])
        if dwell_id in seen_ids:
            raise ValueError('duplicate dwell id')
        seen_ids.add(dwell_id)
        order = integer(item['order'], 'dwell order', 1)
        if order in seen_orders:
            raise ValueError('duplicate dwell order')
        seen_orders.add(order)
        depth = integer(item['depth_mm'], 'depth')
        if depth not in depth_set:
            raise ValueError('dwell depth is not in the depth plan')
        start = integer(item['start_s'], 'dwell start')
        end = integer(item['end_s'], 'dwell end', start + 1)
        dwells.append(Dwell(dwell_id, key(item['probe']), depth, order, start, end))
    return dwells


def _decode_review(doc):
    raw = doc.get('review_of')
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError('review_of must be an object')
    return {'borehole': key(raw['borehole']), 'version': key(raw['version'])}


def decode(doc):
    if not isinstance(doc, dict):
        raise ValueError('input must be an object')
    site, version = key(doc['borehole']), key(doc['version'])
    gap = integer(doc['max_reference_span_s'], 'maximum reference span', 1)
    depths = doc['depths_mm']
    if not isinstance(depths, list) or not depths:
        raise ValueError('expected a nonempty depth plan')
    depth_set = {integer(depth, 'depth') for depth in depths}
    if len(depth_set) != len(depths):
        raise ValueError('duplicate planned depth')
    if not isinstance(doc.get('references'), list) or not isinstance(doc.get('readings'), list):
        raise ValueError('references and readings must be arrays')
    stability = _decode_stability(doc)
    dwells = _decode_dwells(doc, depth_set)
    if dwells and stability is None:
        raise ValueError('stability parameters are required for dwell plans')
    policy = doc.get('sign_policy', 'first_window')
    if policy not in SIGN_POLICIES:
        raise ValueError('invalid sign policy')
    references, seen = defaultdict(list), set()
    for row, item in enumerate(doc['references'], 1):
        probe = key(item['probe'])
        at = integer(item['at_s'], 'reference time')
        if (probe, at) in seen:
            raise ValueError('duplicate probe reference time')
        seen.add((probe, at))
        offset = temperature(item['observed_mc']) - temperature(item['certified_mc'])
        references[probe].append((at, offset, row))
    readings, reading_times = [], set()
    for row, item in enumerate(doc['readings'], 1):
        probe, at = key(item['probe']), integer(item['at_s'], 'reading time')
        if dwells and (probe, at) in reading_times:
            raise ValueError('duplicate probe reading time')
        reading_times.add((probe, at))
        readings.append((row, probe, at,
                         integer(item['depth_mm'], 'depth'), temperature(item['observed_mc'])))
    return (site, version, gap, depth_set, references, readings,
            stability, dwells, policy, _decode_review(doc))
