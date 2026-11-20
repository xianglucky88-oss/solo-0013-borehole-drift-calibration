"""Interpolate drift within a probe's own reference brackets."""
from bisect import bisect_left
from fractions import Fraction


class DriftIndex:
    def __init__(self, references, max_span):
        self._tracks = {}
        self._max_span = max_span
        for probe, rows in references.items():
            track = sorted(rows)
            self._tracks[probe] = ([row[0] for row in track], track)

    def correct(self, probe, at, observed):
        if probe not in self._tracks:
            return None, 'no_probe_reference', []
        times, track = self._tracks[probe]
        i = bisect_left(times, at)
        if i < len(times) and times[i] == at:
            _, offset, row = track[i]
            return Fraction(observed - offset), None, [row]
        if i == 0 or i == len(times):
            nearest = track[0] if i == 0 else track[-1]
            return None, 'outside_reference_range', [nearest[2]]
        start, left, left_row = track[i - 1]
        end, right, right_row = track[i]
        if end - start > self._max_span:
            return None, 'reference_span_exceeded', [left_row, right_row]
        offset = Fraction(left * (end - at) + right * (at - start), end - start)
        return observed - offset, None, [left_row, right_row]
