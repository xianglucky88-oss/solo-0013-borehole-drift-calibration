"""Normalize survey plans, instrument references, and probe readings."""
from collections import defaultdict


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


def decode(doc):
    site, version = key(doc['borehole']), key(doc['version'])
    gap = integer(doc['max_reference_span_s'], 'maximum reference span', 1)
    depths = doc['depths_mm']
    if not isinstance(depths, list) or not depths:
        raise ValueError('expected a nonempty depth plan')
    depth_set = {integer(depth, 'depth') for depth in depths}
    if len(depth_set) != len(depths):
        raise ValueError('duplicate planned depth')
    references, seen = defaultdict(list), set()
    if not isinstance(doc['references'], list) or not isinstance(doc['readings'], list):
        raise ValueError('references and readings must be arrays')
    for row, item in enumerate(doc['references'], 1):
        probe = key(item['probe'])
        at = integer(item['at_s'], 'reference time')
        if (probe, at) in seen:
            raise ValueError('duplicate probe reference time')
        seen.add((probe, at))
        offset = temperature(item['observed_mc']) - temperature(item['certified_mc'])
        references[probe].append((at, offset, row))
    readings = []
    for row, item in enumerate(doc['readings'], 1):
        readings.append((row, key(item['probe']), integer(item['at_s'], 'reading time'),
                         integer(item['depth_mm'], 'depth'), temperature(item['observed_mc'])))
    return site, version, gap, depth_set, references, readings
