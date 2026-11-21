"""Dwell plans, provable stability windows, and time-weighted summaries.

A signed window is the only admissible evidence for a planned dwell depth:
rejected readings, unconfirmed tails without a right-hand reference, and
conflicting dwells can never be bridged over by neighbouring points.
"""
from bisect import bisect_right
from fractions import Fraction


class Dwell:
    __slots__ = ('dwell_id', 'probe', 'depth_mm', 'order', 'start_s', 'end_s')

    def __init__(self, dwell_id, probe, depth_mm, order, start_s, end_s):
        self.dwell_id = dwell_id
        self.probe = probe
        self.depth_mm = depth_mm
        self.order = order
        self.start_s = start_s
        self.end_s = end_s


def overlapping(dwells):
    """Return ``{dwell_id: conflicting_dwell_ids}`` for overlapping dwells.

    Only dwells sharing one probe can conflict because their observations
    could otherwise be mixed. Intervals that only touch at a boundary do not
    overlap.
    """
    conflicts = {dwell.dwell_id: set() for dwell in dwells}
    by_probe = {}
    for dwell in dwells:
        by_probe.setdefault(dwell.probe, []).append(dwell)
    for group in by_probe.values():
        group.sort(key=lambda d: (d.start_s, d.end_s, d.order))
        for i, left in enumerate(group):
            for right in group[i + 1:]:
                if right.start_s >= left.end_s:
                    break
                conflicts[left.dwell_id].add(right.dwell_id)
                conflicts[right.dwell_id].add(left.dwell_id)
    return conflicts


def _within(dwell, at):
    return dwell.start_s <= at <= dwell.end_s


def reference_snapshot(references, probe, view_until):
    """Exact reference rows of one probe available at a signing instant."""
    track = sorted(references.get(probe, ()))
    cutoff = bisect_right([row[0] for row in track], view_until)
    return [{'probe': probe, 'reference_row': row, 'at_s': at, 'offset_mc': offset}
            for at, offset, row in track[:cutoff]]


def correct_series(dwell, readings, index, view_until=None):
    """Correct the dwell's own readings against references known by a view.

    Returns ``(points, rejected)``. A rejected reading splits the chain of
    evidence, so it is returned instead of silently dropped.
    """
    points, rejected = [], []
    for row, probe, at, depth, observed in readings:
        if probe != dwell.probe or depth != dwell.depth_mm or not _within(dwell, at):
            continue
        corrected, reason, evidence = index.correct(probe, at, observed, view_until)
        provenance = {'reading_row': row, 'probe': probe, 'at_s': at,
                      'observed_mc': observed, 'reference_rows': evidence}
        if reason is None:
            points.append({'at_s': at, 'corrected_mc': corrected,
                           'observed_mc': observed, 'reading_row': row,
                           'reference_rows': evidence})
        else:
            rejected.append(dict(provenance, depth_mm=depth, reason=reason))
    points.sort(key=lambda point: point['at_s'])
    return points, rejected


def find_windows(points, stability):
    """All provable stability windows over corrected, in-dwell points.

    A window needs at least ``stable_duration_s`` of continuous coverage and
    a corrected-temperature spread no wider than ``tolerance_mc``. A gap
    larger than ``sampling_interval_s`` breaks continuity; rejected readings
    never enter ``points`` and therefore break it as well.
    """
    duration = stability['stable_duration_s']
    interval = stability['sampling_interval_s']
    tolerance = stability['tolerance_mc']
    windows = []
    n = len(points)
    for i in range(n):
        low = high = points[i]['corrected_mc']
        for j in range(i + 1, n):
            if points[j]['at_s'] - points[j - 1]['at_s'] > interval:
                break
            value = points[j]['corrected_mc']
            low, high = min(low, value), max(high, value)
            if high - low > tolerance:
                break
            if points[j]['at_s'] - points[i]['at_s'] >= duration:
                windows.append({'points': points[i:j + 1],
                                'start_s': points[i]['at_s'],
                                'end_s': points[j]['at_s']})
    return windows


def first_complete_window(dwell, readings, index, stability):
    """Earliest window provable with references received at that moment.

    The candidate window is found over the full reference view, but its
    legal sign instant is the earliest time at which every reference the
    window needs has arrived: the maximum ``at_s`` of its evidence rows.
    A rejected reading or a tail without a confirmed right-hand reference
    can therefore never advance an earlier sign, and re-publishing after
    extra readings arrive cannot move an existing sign time.
    """
    points, rejected = correct_series(dwell, readings, index, dwell.end_s)
    windows = find_windows(points, stability)
    if not windows:
        return None, rejected, None
    earliest = min(windows, key=lambda window: (window['end_s'],
                                                 window['start_s']))
    evidence_rows = {row for point in earliest['points']
                     for row in point['reference_rows']}
    track = index.track(dwell.probe)
    view = max(at for at, _, row in track if row in evidence_rows)
    earliest['view_until_s'] = view
    return earliest, rejected, view


def _longest_window(windows):
    return max(windows, key=lambda w: (w['end_s'] - w['start_s'],
                                       -w['start_s'], len(w['points'])))


def sign_dwell(dwell, readings, index, stability, policy, references=None):
    """Produce the sign record for one dwell under the chosen policy."""
    base = {'dwell_id': dwell.dwell_id, 'probe': dwell.probe,
            'depth_mm': dwell.depth_mm, 'order': dwell.order,
            'dwell_start_s': dwell.start_s, 'dwell_end_s': dwell.end_s,
            'policy': policy}
    window, rejected, view = first_complete_window(
        dwell, readings, index, stability)
    first_at = view
    if policy == 'first_window':
        if window is None:
            return dict(base, status='no_provable_window', rejected=rejected,
                        first_signable_at_s=None, signed_at_s=None,
                        wait_used_s=None, extra_wait_s=None)
        if references is not None:
            window['reference_snapshot'] = reference_snapshot(
                references, dwell.probe, first_at)
        return dict(base, status='signed', window=summarize_window(window),
                    first_signable_at_s=first_at, signed_at_s=first_at,
                    wait_used_s=first_at - dwell.start_s,
                    extra_wait_s=0, rejected=rejected)
    points, end_rejected = correct_series(dwell, readings, index, dwell.end_s)
    windows = find_windows(points, stability)
    if not windows:
        return dict(base, status='no_provable_window', rejected=end_rejected,
                    first_signable_at_s=first_at, signed_at_s=None,
                    wait_used_s=None,
                    extra_wait_s=(dwell.end_s - first_at)
                    if first_at is not None else None)
    chosen = _longest_window(windows)
    chosen['view_until_s'] = dwell.end_s
    if references is not None:
        chosen['reference_snapshot'] = reference_snapshot(
            references, dwell.probe, dwell.end_s)
    return dict(base, status='signed', window=summarize_window(chosen),
                first_signable_at_s=first_at, signed_at_s=dwell.end_s,
                wait_used_s=dwell.end_s - dwell.start_s,
                extra_wait_s=(dwell.end_s - first_at)
                if first_at is not None else 0,
                rejected=end_rejected)


def time_weighted_median(points):
    """Median over time, not over row count, using exact fractions.

    Each interior point owns the interval between its neighbours; boundary
    points own half of their adjacent interval. Weight straddling half the
    total duration follows the conventional even-set median average.
    """
    ordered = sorted(points, key=lambda point: point['at_s'])
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]['corrected_mc']
    weights, total = [], Fraction(0)
    last = len(ordered) - 1
    for k, point in enumerate(ordered):
        if k == 0:
            weight = Fraction(ordered[1]['at_s'] - point['at_s'], 2)
        elif k == last:
            weight = Fraction(point['at_s'] - ordered[k - 1]['at_s'], 2)
        else:
            weight = Fraction(ordered[k + 1]['at_s'] - ordered[k - 1]['at_s'], 2)
        weights.append((point['corrected_mc'], weight))
        total += weight
    weights.sort(key=lambda item: item[0])
    half, cumulative = total / 2, Fraction(0)
    for k, (value, weight) in enumerate(weights):
        if cumulative + weight < half:
            cumulative += weight
            continue
        if cumulative + weight == half and k + 1 < len(weights):
            return (value + weights[k + 1][0]) / 2
        return value
    return weights[-1][0]


def summarize_window(window):
    points = window['points']
    values = [point['corrected_mc'] for point in points]
    summary = {
        'start_s': window['start_s'],
        'end_s': window['end_s'],
        'view_until_s': window['view_until_s'],
        'duration_s': window['end_s'] - window['start_s'],
        'time_weighted_median_mc': str(time_weighted_median(points)),
        'min_mc': str(min(values)),
        'max_mc': str(max(values)),
        'reference_rows': sorted({row for point in points
                                  for row in point['reference_rows']}),
        'points': [{'at_s': point['at_s'], 'reading_row': point['reading_row'],
                    'corrected_mc': str(point['corrected_mc']),
                    'observed_mc': point['observed_mc'],
                    'reference_rows': point['reference_rows']}
                   for point in points],
    }
    if window.get('reference_snapshot') is not None:
        summary['reference_snapshot'] = [
            dict(item, offset_mc=str(item['offset_mc']))
            for item in window['reference_snapshot']]
    return summary
