"""Normalize survey plans, instrument references, certificates, hypotheses.

The baseline schema (references + readings) is fully preserved.  When a
dataset carries co-location certificates, each certificate contributes one
*shared* common-error variable whose bounds couple every one of its rows, and
each permitted hypothesis names the certificates that are suspended because
the two certificates contradict one another.
"""
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
    certificates = decode_certificates(doc)
    hypotheses = decode_hypotheses(doc, certificates)
    width_limit = doc.get('temperature_width_limit_mc')
    if width_limit is not None:
        width_limit = integer(width_limit, 'temperature width limit', 1)
    requests = decode_requests(doc)
    return (site, version, gap, depth_set, references, readings,
            certificates, hypotheses, width_limit, requests)


def decode_certificates(doc):
    raw = doc.get('certificates', [])
    if not isinstance(raw, list):
        raise ValueError('certificates must be an array')
    certificates, identities = [], set()
    for row, item in enumerate(raw, 1):
        cert_id = key(item['certificate'])
        if cert_id in identities:
            raise ValueError('duplicate certificate identifier')
        identities.add(cert_id)
        low = temperature(item['common_error_mc_min'])
        high = temperature(item['common_error_mc_max'])
        if low > high:
            raise ValueError('certificate common-error bounds are reversed')
        valid_from = integer(item['valid_from_s'], 'certificate valid_from')
        valid_to = integer(item['valid_to_s'], 'certificate valid_to')
        if valid_from > valid_to:
            raise ValueError('certificate validity window is reversed')
        rows = item.get('rows', [])
        if not isinstance(rows, list) or not rows:
            raise ValueError('certificate must carry at least one joint row')
        decoded_rows, joints = [], set()
        for joint_row, joint in enumerate(rows, 1):
            probe_a = key(joint['probe_a'])
            probe_b = key(joint['probe_b'])
            if probe_a == probe_b:
                raise ValueError('a joint row must link two distinct probes')
            at = integer(joint['at_s'], 'joint observation time')
            if (probe_a, probe_b, at) in joints:
                raise ValueError('duplicate certificate joint row')
            joints.add((probe_a, probe_b, at))
            observed_a = temperature(joint['observed_a_mc'])
            observed_b = temperature(joint['observed_b_mc'])
            if not valid_from <= at <= valid_to:
                raise ValueError('joint row falls outside its certificate validity window')
            decoded_rows.append({
                'joint_row': joint_row, 'certificate': cert_id, 'at_s': at,
                'probe_a': probe_a, 'probe_b': probe_b,
                'observed_a_mc': observed_a, 'observed_b_mc': observed_b,
            })
        certificates.append({
            'certificate_row': row, 'certificate': cert_id,
            'error_min_mc': low, 'error_max_mc': high,
            'valid_from_s': valid_from, 'valid_to_s': valid_to,
            'rows': decoded_rows,
        })
    return certificates


def decode_hypotheses(doc, certificates):
    known = {cert['certificate'] for cert in certificates}
    raw = doc.get('hypotheses', [])
    if not isinstance(raw, list):
        raise ValueError('hypotheses must be an array')
    if certificates and not raw:
        raise ValueError('certificates require at least one permitted hypothesis')
    hypotheses, identities = [], set()
    for item in raw:
        hypothesis_id = key(item['hypothesis'])
        if hypothesis_id in identities:
            raise ValueError('duplicate hypothesis identifier')
        identities.add(hypothesis_id)
        suspended = item.get('suspended_certificates', [])
        if not isinstance(suspended, list):
            raise ValueError('suspended_certificates must be an array')
        suspended_set = set()
        for cert_id in suspended:
            cert_id = key(cert_id)
            if cert_id not in known:
                raise ValueError('hypothesis suspends an unknown certificate')
            if cert_id in suspended_set:
                raise ValueError('certificate suspended twice in one hypothesis')
            suspended_set.add(cert_id)
        hypotheses.append({'hypothesis': hypothesis_id,
                           'suspended_certificates': suspended_set})
    return hypotheses


def decode_requests(doc):
    raw = doc.get('delivery_requests', [])
    if not isinstance(raw, list):
        raise ValueError('delivery_requests must be an array')
    requests = []
    for item in raw:
        request_id = key(item['request'])
        kind = item.get('kind', 'depth')
        if kind not in ('depth', 'difference'):
            raise ValueError('delivery request must be depth or difference')
        hypothesis = item.get('hypothesis')
        if hypothesis is not None:
            hypothesis = key(hypothesis)
        entry = {'request': request_id, 'kind': kind, 'hypothesis': hypothesis}
        if kind == 'depth':
            entry['depth_mm'] = integer(item['depth_mm'], 'requested depth')
        else:
            entry['shallow_mm'] = integer(item['shallow_mm'], 'shallow depth')
            entry['deep_mm'] = integer(item['deep_mm'], 'deep depth')
            if entry['shallow_mm'] == entry['deep_mm']:
                raise ValueError('difference request needs two distinct depths')
        requests.append(entry)
    identities = [entry['request'] for entry in requests]
    if len(set(identities)) != len(identities):
        raise ValueError('duplicate delivery request identifier')
    return requests
