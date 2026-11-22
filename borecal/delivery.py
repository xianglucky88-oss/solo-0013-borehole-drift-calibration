"""Read-back delivery with hypothesis coverage and pending-reason audit.

A conditional read-back must present the same single hypothesis covering the
observation windows of every depth it touches.  A restricted conditional
result is never delivered as an ordinary temperature: requests that cannot
produce a signed value come back as ``pending`` with an explicit reason, and
the original conditional credentials keep their scope unchanged.
"""


def deliver(requests, assessments, unconditional, certificates, width_limit):
    by_hypothesis = {model['hypothesis']: model for model in assessments}
    responses = []
    for request in requests:
        if request['kind'] == 'depth':
            responses.append(_deliver_depth(request, by_hypothesis, unconditional))
        else:
            responses.append(_deliver_difference(request, by_hypothesis, unconditional))
    return responses


def _deliver_depth(request, by_hypothesis, unconditional):
    depth = request['depth_mm']
    base = {'request': request['request'], 'kind': 'depth', 'depth_mm': depth}
    if request['hypothesis'] is None:
        fact = _find_depth(unconditional['depth_facts'], depth)
        if fact is None or not fact['signable']:
            return {**base, 'status': 'pending',
                    'reason': (fact or {}).get('blocked_reason') or 'not_unconditionally_signable',
                    'median_range_mc': None, 'hypothesis': None}
        return {**base, 'status': 'delivered_unconditional',
                'median_range_mc': fact['median_range_mc'],
                'within_width_limit': fact['within_width_limit'],
                'hypothesis': None,
                'supporting_hypotheses': fact['supporting_hypotheses']}

    model = by_hypothesis.get(request['hypothesis'])
    if model is None:
        return {**base, 'status': 'pending', 'reason': 'unknown_hypothesis',
                'median_range_mc': None, 'hypothesis': request['hypothesis']}
    if not model['feasible']:
        return {**base, 'status': 'pending', 'reason': 'hypothesis_infeasible',
                'median_range_mc': None, 'hypothesis': request['hypothesis']}
    fact = _find_depth(model['depth_facts'], depth)
    if fact is None or not fact['signable']:
        return {**base, 'status': 'pending',
                'reason': (fact or {}).get('blocked_reason') or 'not_signable_under_hypothesis',
                'median_range_mc': None, 'hypothesis': request['hypothesis'],
                'coverage_window_s': None}
    return {
        **base, 'status': 'delivered_conditional',
        'median_range_mc': fact['median_range_mc'],
        'within_width_limit': fact['within_width_limit'],
        'hypothesis': request['hypothesis'],
        'coverage_window_s': fact['time_window_s'],
        'certificate_scope': _certificate_scope(model),
    }


def _deliver_difference(request, by_hypothesis, unconditional):
    shallow, deep = request['shallow_mm'], request['deep_mm']
    base = {'request': request['request'], 'kind': 'difference',
            'shallow_mm': shallow, 'deep_mm': deep}
    if request['hypothesis'] is None:
        fact = _find_difference(unconditional['difference_facts'], shallow, deep)
        if fact is None or not fact['signable']:
            return {**base, 'status': 'pending',
                    'reason': (fact or {}).get('blocked_reason') or 'not_unconditionally_signable',
                    'difference_range_mc': None, 'hypothesis': None}
        return {**base, 'status': 'delivered_unconditional',
                'difference_range_mc': fact['difference_range_mc'],
                'hypothesis': None,
                'supporting_hypotheses': fact['supporting_hypotheses']}

    model = by_hypothesis.get(request['hypothesis'])
    if model is None:
        return {**base, 'status': 'pending', 'reason': 'unknown_hypothesis',
                'difference_range_mc': None, 'hypothesis': request['hypothesis']}
    if not model['feasible']:
        return {**base, 'status': 'pending', 'reason': 'hypothesis_infeasible',
                'difference_range_mc': None, 'hypothesis': request['hypothesis']}
    # One joint difference needs one hypothesis covering both layers; holding
    # separate per-layer verifications under different assumptions never works.
    fact = _find_difference(model['difference_facts'], shallow, deep)
    if fact is None or not fact['signable']:
        return {**base, 'status': 'pending',
                'reason': (fact or {}).get('blocked_reason') or 'no_common_hypothesis_for_pair',
                'difference_range_mc': None, 'hypothesis': request['hypothesis'],
                'coverage_window_s': None}
    return {
        **base, 'status': 'delivered_conditional',
        'difference_range_mc': fact['difference_range_mc'],
        'hypothesis': request['hypothesis'],
        'coverage_window_s': fact['time_window_s'],
        'certificate_scope': _certificate_scope(model),
    }


def _certificate_scope(model):
    return {
        'active_certificates': sorted(name[4:] for name in model['bounded']),
        'suspended_certificates': model['suspended'],
        'anchored_components': model['anchored_components'],
        'free_components': sorted(model['free_symbols']),
    }


def _find_depth(facts, depth):
    for fact in facts:
        if fact['depth_mm'] == depth:
            return fact
    return None


def _find_difference(facts, shallow, deep):
    for fact in facts:
        if fact['shallow_mm'] == shallow and fact['deep_mm'] == deep:
            return fact
    return None
