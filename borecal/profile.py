"""Build depth facts and a rejection dataset without discarding provenance."""
from statistics import median

from .drift import DriftIndex


def build(depths, references, readings, max_span):
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
