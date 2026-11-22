"""Propagate direct reference drift across co-location certificates.

A probe that cannot enter the temperature bath never receives a direct
standard.  Its drift nodes are affine expressions built from the shared
common-error variables of the certificates that link it, through the probe
graph, back to a directly referenced probe.  Components with no path to a
direct standard stay unanchored and can only surrender relative values.
"""
from bisect import bisect_left
from fractions import Fraction

from .affineexpr import Affine

ERROR_PREFIX = 'err:'
FREE_PREFIX = 'free:'


class ReferenceTrack:
    """Direct-standard drift track, mirroring the baseline interpolation."""

    def __init__(self, rows, max_span):
        self._track = sorted(rows)
        self._times = [row[0] for row in self._track]
        self._max_span = max_span

    def node(self, at):
        times, track = self._times, self._track
        i = bisect_left(times, at)
        if i < len(times) and times[i] == at:
            _, offset, row = track[i]
            return Affine(offset), None, [row]
        if i == 0 or i == len(times):
            nearest = track[0] if i == 0 else track[-1]
            return None, 'outside_reference_range', [nearest[2]]
        start, left, left_row = track[i - 1]
        end, right, right_row = track[i]
        if end - start > self._max_span:
            return None, 'reference_span_exceeded', [left_row, right_row]
        weight = Fraction(at - start, end - start)
        node = Affine(left) * (1 - weight) + Affine(right) * weight
        return node, None, [left_row, right_row]


def error_symbol(certificate):
    return f'{ERROR_PREFIX}{certificate}'


def build_tracks(references, max_span):
    return {probe: ReferenceTrack(rows, max_span) for probe, rows in references.items()}


def _as_equation(left, rhs_constant):
    """Turn an affine left side minus a constant into an LP constraint row."""
    return ({str(symbol): coef for symbol, coef in left.terms.items()},
            '==', Fraction(rhs_constant) - left.constant)


def evaluate_hypothesis(certificates, references, readings, max_span, suspended, planned_depths):
    active = [cert for cert in certificates if cert['certificate'] not in suspended]
    tracks = build_tracks(references, max_span)

    variables = [(error_symbol(cert['certificate']), cert['error_min_mc'], cert['error_max_mc'])
                 for cert in active]
    bounded = {name for name, _, _ in variables}
    constraints = []

    # probe -> time -> affine drift node; direct tracks seed exact offsets.
    nodes = {probe: {} for probe in tracks}
    anchor = {probe: f'direct:{probe}' for probe in tracks}

    edges = []
    for cert in active:
        symbol = error_symbol(cert['certificate'])
        for joint in cert['rows']:
            edges.append((cert['certificate'], symbol, joint))

    def seed_direct(probe, at):
        if at in nodes.get(probe, {}):
            return nodes[probe][at]
        if probe not in tracks:
            return None
        node, _, _ = tracks[probe].node(at)
        if node is not None:
            nodes.setdefault(probe, {})[at] = node
        return node

    needed = set()
    for _, _, joint in edges:
        needed.add((joint['probe_a'], joint['at_s']))
        needed.add((joint['probe_b'], joint['at_s']))
    for _, probe, at, _, _ in readings:
        needed.add((probe, at))
    for probe, at in needed:
        if probe in tracks:
            seed_direct(probe, at)

    # Fixpoint propagation across certificate equations.  Identity at a joint
    # time: d_a - d_b = observed_a - observed_b + e_cert.
    pending = list(edges)
    progress = True
    while pending and progress:
        progress = False
        remaining = []
        for cert_id, symbol, joint in pending:
            at = joint['at_s']
            a, b = joint['probe_a'], joint['probe_b']
            node_a = nodes.get(a, {}).get(at)
            node_b = nodes.get(b, {}).get(at)
            gap = joint['observed_a_mc'] - joint['observed_b_mc']
            if node_a is not None and node_b is not None:
                # Record the joint equation coupling the bounded error var.
                constraints.append(_as_equation(node_a - node_b - Affine(0, {symbol: 1}), gap))
                progress = True
            elif node_a is not None:
                nodes.setdefault(b, {})[at] = (
                    node_a - Affine(gap) - Affine(0, {symbol: 1}))
                anchor[b] = anchor.get(a)
                progress = True
            elif node_b is not None:
                nodes.setdefault(a, {})[at] = (
                    node_b + Affine(gap) + Affine(0, {symbol: 1}))
                anchor[a] = anchor.get(b)
                progress = True
            else:
                remaining.append((cert_id, symbol, joint))
        pending = remaining

    certificate_rejections = [{
        'certificate': cert_id, 'joint_row': joint['joint_row'], 'at_s': joint['at_s'],
        'probe_a': joint['probe_a'], 'probe_b': joint['probe_b'],
        'reason': 'certificate_not_anchored',
    } for cert_id, _, joint in pending]

    # Union-find the unanchored probes so each free component gets one symbol.
    probes = {probe for _, probe, _, _, _ in readings}
    probes.update(anchor)
    for _, _, joint in edges:
        probes.add(joint['probe_a'])
        probes.add(joint['probe_b'])
    unanchored = sorted(probe for probe in probes if anchor.get(probe) is None)
    union = {probe: probe for probe in unanchored}

    def find(x):
        while union[x] != x:
            union[x] = union[union[x]]
            x = union[x]
        return x

    for _, _, joint in edges:
        a, b = joint['probe_a'], joint['probe_b']
        if a in union and b in union:
            ra, rb = find(a), find(b)
            if ra != rb:
                union[rb] = ra
    component_of = {probe: find(probe) for probe in unanchored}
    free_symbols = {f'{FREE_PREFIX}{root}' for root in set(component_of.values())}

    # Within a free component a single anchor symbol represents the unknown
    # absolute drift; certificate rows still bind the relative differences.
    for probe in unanchored:
        nodes.setdefault(probe, {})
    for cert_id, symbol, joint in edges:
        at = joint['at_s']
        a, b = joint['probe_a'], joint['probe_b']
        if a in union and b in union and find(a) == find(b):
            free = f'{FREE_PREFIX}{find(a)}'
            gap = joint['observed_a_mc'] - joint['observed_b_mc']
            nodes[a].setdefault(at, Affine(0, {free: 1}))
            nodes[b].setdefault(
                at, Affine(0, {free: 1}) - Affine(gap) - Affine(0, {symbol: 1}))
            # The free anchor cancels; keep the relative error equation.
            relative = nodes[a][at] - nodes[b][at] - Affine(0, {symbol: 1})
            constraints.append(_as_equation(relative, gap))

    corrected, rejected = [], []
    for row, probe, at, depth, observed in readings:
        if depth not in planned_depths:
            rejected.append(_rejection(row, probe, at, depth, observed, [], 'unplanned_depth'))
            continue
        node, error, evidence = _reading_node(probe, at, tracks, nodes, max_span)
        if error is not None:
            rejected.append(_rejection(row, probe, at, depth, observed, evidence, error))
            continue
        free = {s for s in node.terms if str(s).startswith(FREE_PREFIX)}
        corrected.append({
            'reading_row': row, 'probe': probe, 'at_s': at, 'depth_mm': depth,
            'observed_mc': observed, 'value': Affine(observed) - node,
            'component': anchor.get(probe) or f'{FREE_PREFIX}{component_of.get(probe, probe)}',
            'anchored': anchor.get(probe) is not None,
            'reference_rows': evidence,
            'free_symbols': sorted(str(symbol) for symbol in free),
        })

    return {
        'suspended': sorted(suspended),
        'variables': variables, 'bounded': bounded, 'free_symbols': free_symbols,
        'constraints': constraints, 'corrected': corrected, 'rejected': rejected,
        'certificate_rejections': certificate_rejections,
        'anchored_components': sorted({v for v in anchor.values() if v}),
        'nodes': nodes, 'anchor': anchor, 'component_of': component_of,
    }


def _reading_node(probe, at, tracks, nodes, max_span):
    if probe in tracks:
        node, error, evidence = tracks[probe].node(at)
        if error is None:
            return node, None, evidence
        if error != 'no_probe_reference':
            return None, error, evidence
    timeline = nodes.get(probe)
    if not timeline:
        return None, 'no_probe_reference', []
    times = sorted(timeline)
    i = bisect_left(times, at)
    if i < len(times) and times[i] == at:
        return timeline[at], None, []
    if i == 0 or i == len(times):
        return None, 'outside_reference_range', []
    start, end = times[i - 1], times[i]
    if end - start > max_span:
        return None, 'reference_span_exceeded', []
    weight = Fraction(at - start, end - start)
    return timeline[start] * (1 - weight) + timeline[end] * weight, None, []


def _rejection(row, probe, at, depth, observed, evidence, reason):
    return {'reading_row': row, 'probe': probe, 'at_s': at, 'depth_mm': depth,
            'observed_mc': observed, 'reference_rows': evidence, 'reason': reason}
