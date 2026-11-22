"""Assess hypotheses and assemble conditional and unconditional profiles."""
from collections import defaultdict
from fractions import Fraction

from .certmodel import evaluate_hypothesis
from .linsolve import Infeasible, feasible
from .ranges import NotSignable, difference_range, median_range, width


def assess(certificates, references, readings, max_span, hypotheses, planned_depths,
           width_limit=None):
    results = []
    for hypothesis in hypotheses:
        model = evaluate_hypothesis(
            certificates, references, readings, max_span,
            hypothesis['suspended_certificates'], planned_depths)
        model['hypothesis'] = hypothesis['hypothesis']
        model['feasible'] = feasible(model['variables'], model['constraints'])
        if model['feasible']:
            model['depth_facts'] = _depth_facts(model, planned_depths, width_limit)
            model['difference_facts'] = _difference_facts(model, planned_depths)
        else:
            model['depth_facts'] = []
            model['difference_facts'] = []
        results.append(model)
    return results


def _grouped_values(model):
    grouped = defaultdict(list)
    for item in model['corrected']:
        grouped[item['depth_mm']].append(item)
    return grouped


def _depth_facts(model, planned_depths, width_limit):
    grouped = _grouped_values(model)
    facts = []
    for depth in sorted(planned_depths):
        items = grouped.get(depth, [])
        fact = {
            'depth_mm': depth,
            'hypothesis': model['hypothesis'],
            'observation_count': len(items),
            'time_window_s': _window(items),
            'components': sorted({item['component'] for item in items}),
            'anchored': bool(items) and all(item['anchored'] for item in items),
            'signable': False,
            'median_range_mc': None,
            'within_width_limit': None,
            'blocked_reason': None,
        }
        if not items:
            fact['blocked_reason'] = 'no_valid_reading'
        elif not fact['anchored']:
            fact['blocked_reason'] = 'relative_only_component'
        else:
            try:
                interval = median_range(model, [item['value'] for item in items])
            except NotSignable as exc:
                fact['blocked_reason'] = str(exc)
            except Infeasible:
                fact['blocked_reason'] = 'infeasible_median'
            else:
                fact['median_range_mc'] = [str(interval[0]), str(interval[1])]
                fact['signable'] = True
                if width_limit is not None:
                    fact['within_width_limit'] = width(interval) <= width_limit
        facts.append(fact)
    return facts


def _difference_facts(model, planned_depths):
    grouped = _grouped_values(model)
    facts = []
    for shallow in sorted(planned_depths):
        for deep in sorted(d for d in planned_depths if d > shallow):
            shallow_items = grouped.get(shallow, [])
            deep_items = grouped.get(deep, [])
            fact = {
                'shallow_mm': shallow, 'deep_mm': deep,
                'hypothesis': model['hypothesis'],
                'time_window_s': {
                    'shallow': _window(shallow_items),
                    'deep': _window(deep_items),
                },
                'signable': False,
                'difference_range_mc': None,
                'blocked_reason': None,
            }
            if not shallow_items or not deep_items:
                fact['blocked_reason'] = 'missing_signed_depth'
            else:
                try:
                    interval = difference_range(
                        model,
                        [item['value'] for item in shallow_items],
                        [item['value'] for item in deep_items])
                except NotSignable as exc:
                    fact['blocked_reason'] = str(exc)
                except Infeasible:
                    fact['blocked_reason'] = 'infeasible_difference'
                else:
                    fact['difference_range_mc'] = [str(interval[0]), str(interval[1])]
                    fact['signable'] = True
            facts.append(fact)
    return facts


def _window(items):
    if not items:
        return None
    times = [item['at_s'] for item in items]
    return {'from_s': min(times), 'to_s': max(times)}


def unconditional_profile(assessments, width_limit):
    """Intersect every feasible hypothesis; holds with no assumption."""
    feasible_models = [m for m in assessments if m['feasible']]
    depth_facts, difference_facts = [], []
    if not feasible_models:
        return {'feasible_hypotheses': [], 'depth_facts': [], 'difference_facts': []}
    depth_index = {fact['depth_mm']: fact for fact in feasible_models[0]['depth_facts']}
    for depth in sorted(depth_index):
        signed = [m for m in feasible_models
                  if _fact(m['depth_facts'], depth)['signable']]
        merged = _intersect_depth(depth, signed, width_limit)
        merged['supporting_hypotheses'] = [m['hypothesis'] for m in signed]
        depth_facts.append(merged)
    for fact in feasible_models[0]['difference_facts']:
        pair = (fact['shallow_mm'], fact['deep_mm'])
        signed = [m for m in feasible_models
                  if _diff_fact(m['difference_facts'], *pair)['signable']]
        merged = _intersect_difference(pair, signed)
        merged['supporting_hypotheses'] = [m['hypothesis'] for m in signed]
        difference_facts.append(merged)
    return {
        'feasible_hypotheses': [m['hypothesis'] for m in feasible_models],
        'depth_facts': depth_facts,
        'difference_facts': difference_facts,
    }


def _intersect_depth(depth, models, width_limit):
    if not models:
        return {'depth_mm': depth, 'signable': False, 'median_range_mc': None,
                'within_width_limit': None, 'blocked_reason': 'no_feasible_hypothesis'}
    lows = [Fraction(_fact(m['depth_facts'], depth)['median_range_mc'][0]) for m in models]
    highs = [Fraction(_fact(m['depth_facts'], depth)['median_range_mc'][1]) for m in models]
    low, high = max(lows), min(highs)
    if low > high:
        return {'depth_mm': depth, 'signable': False, 'median_range_mc': None,
                'within_width_limit': None, 'blocked_reason': 'hypotheses_disjoint'}
    interval = [str(low), str(high)]
    return {
        'depth_mm': depth, 'signable': True, 'median_range_mc': interval,
        'within_width_limit': None if width_limit is None else (high - low) <= width_limit,
        'blocked_reason': None,
    }


def _intersect_difference(pair, models):
    if not models:
        return {'shallow_mm': pair[0], 'deep_mm': pair[1], 'signable': False,
                'difference_range_mc': None, 'blocked_reason': 'no_feasible_hypothesis'}
    lows, highs = [], []
    for model in models:
        interval = _diff_fact(model['difference_facts'], *pair)['difference_range_mc']
        lows.append(Fraction(interval[0]))
        highs.append(Fraction(interval[1]))
    low, high = max(lows), min(highs)
    if low > high:
        return {'shallow_mm': pair[0], 'deep_mm': pair[1], 'signable': False,
                'difference_range_mc': None, 'blocked_reason': 'hypotheses_disjoint'}
    return {'shallow_mm': pair[0], 'deep_mm': pair[1], 'signable': True,
            'difference_range_mc': [str(low), str(high)], 'blocked_reason': None}


def _fact(facts, depth):
    return next(fact for fact in facts if fact['depth_mm'] == depth)


def _diff_fact(facts, shallow, deep):
    return next(fact for fact in facts
                if fact['shallow_mm'] == shallow and fact['deep_mm'] == deep)
