"""Supplementary certificates cover only part of a borehole's timeline.

A later certificate may confirm only some observation windows.  It never
widens an existing release: depths or differences whose windows are not fully
covered stay unreadable as signed, the original credentials keep their scope,
and the response states exactly which parts became available.
"""
from .assess import assess, unconditional_profile
from .delivery import deliver
from .contract import decode


def supplement(original_doc, supplementary_doc):
    """Evaluate a later, partial certificate against an immutable release.

    The supplementary document adds certificates and its own delivery
    requests, but reuses the original references and readings.  Each original
    hypothesis is replayed with the extra certificates active, so the new
    evidence can only refine an assumption that was already permitted.  The
    original document is never rewritten.
    """
    original = _overlay(original_doc)
    extra = _overlay(supplementary_doc)

    merged_certificates = original['certificates'] + extra['certificates']
    # Reuse the original permitted hypotheses; an empty suspension list in
    # the supplementary document is not allowed to resurrect contradictory
    # original certificates at once.
    hypotheses = original['hypotheses'] or extra['hypotheses']
    assessments = assess(
        merged_certificates, original['references'], original['readings'],
        original['max_span'], hypotheses, original['depths'],
        extra['width_limit'])
    unconditional = unconditional_profile(assessments, extra['width_limit'])
    coverage = _coverage_report(extra['certificates'], original['depths'],
                                original['readings'])
    responses = deliver(extra['requests'], assessments, unconditional,
                        merged_certificates, extra['width_limit'])
    return {
        'supplementary_certificates': [c['certificate'] for c in extra['certificates']],
        'original_version': original['version'],
        'scope_rewritten': False,
        'coverage': coverage,
        'hypotheses': [_compact(model) for model in assessments],
        'unconditional': unconditional,
        'delivery': _annotate_coverage(responses, coverage),
    }


def _coverage_report(supplementary, depths, readings):
    windows = [(cert['valid_from_s'], cert['valid_to_s']) for cert in supplementary]
    reading_times = {}
    for row, probe, at, depth, observed in readings:
        reading_times.setdefault(depth, set()).add(at)
    report = {}
    for depth in depths:
        times = reading_times.get(depth, set())
        covered = bool(times) and all(
            any(start <= at <= end for start, end in windows) for at in times)
        report[depth] = {
            'depth_mm': depth,
            'observation_times_s': sorted(times),
            'fully_covered': covered,
            'readable_as_signed': covered,
        }
    return report


def _annotate_coverage(responses, coverage):
    annotated = []
    for response in responses:
        if response['kind'] == 'depth':
            response = dict(response)
            marker = coverage.get(response['depth_mm'])
            response['supplementary_coverage'] = marker
            # A conditional value may rest on the original credentials even
            # when the later certificate alone cannot cover the whole window;
            # surface that distinction instead of silently widening scope.
            if response['status'] == 'delivered_conditional':
                response['supplementary_alone_signed'] = (
                    marker is not None and marker['fully_covered'])
        annotated.append(response)
    return annotated


def _compact(model):
    return {
        'hypothesis': model['hypothesis'],
        'feasible': model['feasible'],
        'suspended_certificates': model['suspended'],
        'depth_facts': model['depth_facts'],
        'difference_facts': model['difference_facts'],
    }


def _overlay(doc):
    (_, version, max_span, depths, references, readings,
     certificates, hypotheses, width_limit, requests) = decode(doc)
    return {
        'version': version, 'max_span': max_span, 'depths': depths,
        'references': references, 'readings': readings,
        'certificates': certificates, 'hypotheses': hypotheses,
        'width_limit': width_limit, 'requests': requests,
    }
