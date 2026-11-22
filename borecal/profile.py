"""Build depth facts and a rejection dataset without discarding provenance."""
from statistics import median

from .assess import assess, unconditional_profile
from .delivery import deliver
from .drift import DriftIndex


def build(depths, references, readings, max_span):
    """Baseline direct-standard profile, unchanged for legacy inputs."""
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


def build_certified(depths, references, readings, max_span, certificates,
                    hypotheses, width_limit, requests):
    """Assumption-aware profile over contradictory co-location certificates."""
    assessments = assess(certificates, references, readings, max_span,
                         hypotheses, depths, width_limit)
    unconditional = unconditional_profile(assessments, width_limit)
    delivery_responses = deliver(requests, assessments, unconditional,
                                 certificates, width_limit)
    return {
        'hypotheses': [_serialize_assessment(model) for model in assessments],
        'unconditional': unconditional,
        'delivery': delivery_responses,
    }


def _serialize_assessment(model):
    return {
        'hypothesis': model['hypothesis'],
        'feasible': model['feasible'],
        'suspended_certificates': model['suspended'],
        'depth_facts': model['depth_facts'],
        'difference_facts': model['difference_facts'],
        'rejected': model['rejected'],
        'certificate_rejections': model['certificate_rejections'],
        'anchored_components': model['anchored_components'],
        'free_components': sorted(model['free_symbols']),
    }
