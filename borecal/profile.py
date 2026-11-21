"""Build depth facts and a rejection dataset without discarding provenance."""
from fractions import Fraction
from statistics import median

from .drift import DriftIndex
from .dwell import correct_series, overlapping, sign_dwell


def build(depths, references, readings, max_span):
    """Legacy profile path: row-count medians over every valid reading."""
    index = DriftIndex(references, max_span)
    bins = {depth: [] for depth in sorted(depths)}
    rejected = []
    for row, probe, at, depth, observed in readings:
        if depth not in bins:
            corrected, error, evidence = None, 'unplanned_depth', []
        else:
            corrected, error, evidence = index.correct(probe, at, observed)
        provenance = {'reading_row': row, 'probe': probe, 'at_s': at,
                      'observed_mc': observed, 'reference_rows': evidence}
        if error is None:
            bins[depth].append((corrected, provenance))
        else:
            rejected.append(dict(provenance, depth_mm=depth, reason=error))
    return {
        'depths': [
            {'depth_mm': depth,
             'median_mc': str(median([value for value, _ in rows])) if rows else None,
             'observations': [dict(source, corrected_mc=str(value)) for value, source in rows]}
            for depth, rows in bins.items()
        ],
        'rejected': rejected,
    }


def _window_weights(window):
    """Time weights for one window's points (trapezoidal boundary halves)."""
    points = sorted(window['points'], key=lambda point: point['at_s'])
    if len(points) == 1:
        return [(Fraction(points[0]['corrected_mc']), Fraction(1))]
    weights, last = [], len(points) - 1
    for k, point in enumerate(points):
        value = Fraction(point['corrected_mc'])
        if k == 0:
            weight = Fraction(points[1]['at_s'] - point['at_s'], 2)
        elif k == last:
            weight = Fraction(point['at_s'] - points[k - 1]['at_s'], 2)
        else:
            weight = Fraction(points[k + 1]['at_s'] - points[k - 1]['at_s'], 2)
        weights.append((value, weight))
    return weights


def _pooled_median(windows):
    pooled = []
    for window in windows:
        pooled.extend(_window_weights(window))
    total = sum((weight for _, weight in pooled), Fraction(0))
    pooled.sort(key=lambda item: item[0])
    half, cumulative = total / 2, Fraction(0)
    for k, (value, weight) in enumerate(pooled):
        if cumulative + weight < half:
            cumulative += weight
            continue
        if cumulative + weight == half and k + 1 < len(pooled):
            return (value + pooled[k + 1][0]) / 2
        return value
    return pooled[-1][0]


def build_dwell(depths, references, readings, max_span, stability,
                dwells, policy):
    """Dwell profile path: only signed windows can confirm a planned depth."""
    index = DriftIndex(references, max_span)
    conflicts = overlapping(dwells)
    conflicted = {dwell_id for dwell_id, rivals in conflicts.items() if rivals}
    signs = []
    for dwell in dwells:
        if dwell.dwell_id in conflicted:
            _, rejected = correct_series(dwell, readings, index, dwell.end_s)
            rejected = [dict(item, reason='conflicting_dwell') for item in rejected]
            signs.append({
                'dwell_id': dwell.dwell_id, 'probe': dwell.probe,
                'depth_mm': dwell.depth_mm, 'order': dwell.order,
                'dwell_start_s': dwell.start_s, 'dwell_end_s': dwell.end_s,
                'policy': policy, 'status': 'conflicting_dwell',
                'conflicts_with': sorted(conflicts[dwell.dwell_id]),
                'window': None, 'first_signable_at_s': None,
                'signed_at_s': None, 'wait_used_s': None,
                'extra_wait_s': None, 'rejected': rejected,
            })
            continue
        signs.append(sign_dwell(dwell, readings, index, stability, policy,
                                references=references))

    covered_rows = {item['reading_row'] for sign in signs
                    for item in sign['rejected']}
    covered_rows |= {point['reading_row'] for sign in signs
                     if sign.get('window')
                     for point in sign['window']['points']}
    unused_readings = []
    for row, probe, at, depth, observed in readings:
        if row in covered_rows:
            continue
        reason = ('unplanned_depth' if depth not in depths else 'outside_dwell')
        unused_readings.append({'reading_row': row, 'probe': probe, 'at_s': at,
                                'depth_mm': depth, 'observed_mc': observed,
                                'reference_rows': [], 'reason': reason})

    depth_facts = []
    for depth in sorted(depths):
        local = [sign for sign in signs if sign['depth_mm'] == depth]
        signed = [sign for sign in local if sign['status'] == 'signed']
        windows = [sign['window'] for sign in signed]
        if windows:
            all_values = [Fraction(point['corrected_mc']) for window in windows
                          for point in window['points']]
            ref_rows = sorted({row for window in windows
                               for row in window['reference_rows']})
            fact = {
                'depth_mm': depth, 'status': 'confirmed', 'reason': None,
                'median_mc': str(_pooled_median(windows)),
                'min_mc': str(min(all_values)), 'max_mc': str(max(all_values)),
                'reference_rows': ref_rows,
                'signed_windows': [
                    {'dwell_id': sign['dwell_id'], 'order': sign['order'],
                     'policy': sign['policy'],
                     'signed_at_s': sign['signed_at_s'],
                     'first_signable_at_s': sign['first_signable_at_s'],
                     'wait_used_s': sign['wait_used_s'],
                     'extra_wait_s': sign['extra_wait_s'],
                     **sign['window']}
                    for sign in signed],
            }
        else:
            reason = ('conflicting_dwell'
                      if any(sign['status'] == 'conflicting_dwell' for sign in local)
                      else 'no_signed_window')
            fact = {'depth_mm': depth, 'status': 'unconfirmed', 'reason': reason,
                    'median_mc': None, 'min_mc': None, 'max_mc': None,
                    'reference_rows': [], 'signed_windows': []}
        depth_facts.append(fact)

    flat_rejected = [dict(item, dwell_id=sign['dwell_id'])
                     for sign in signs for item in sign['rejected']]
    flat_rejected.extend(unused_readings)
    return {
        'mode': 'dwell',
        'sign_policy': policy,
        'stability': stability,
        'depths': depth_facts,
        'signs': signs,
        'conflicts': {dwell_id: sorted(rivals)
                      for dwell_id, rivals in conflicts.items() if rivals},
        'unused_readings': unused_readings,
        'rejected': flat_rejected,
    }
