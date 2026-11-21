"""Interpolate drift within a probe's own reference brackets."""
from bisect import bisect_left, bisect_right
from fractions import Fraction


class DriftIndex:
    def __init__(self, references, max_span):
        self._tracks = {}
        self._max_span = max_span
        for probe, rows in references.items():
            track = sorted(rows)
            self._tracks[probe] = ([row[0] for row in track], track)

    def track(self, probe):
        """Sorted ``(at_s, offset, source_row)`` reference rows of a probe."""
        return self._tracks[probe][1] if probe in self._tracks else []

    def correct(self, probe, at, observed, view_until=None):
        """Correct one reading.

        When ``view_until`` is given, only references received at or before
        that instant are admissible: late references cannot substantiate a
        window that had already been signed.
        """
        if probe not in self._tracks:
            return None, 'no_probe_reference', []
        all_times, track = self._tracks[probe]
        if view_until is None:
            times, visible = all_times, track
        else:
            cutoff = bisect_right(all_times, view_until)
            times, visible = all_times[:cutoff], track[:cutoff]
        if not visible:
            return None, 'no_probe_reference', []
        i = bisect_left(times, at)
        if i < len(times) and times[i] == at:
            _, offset, row = visible[i]
            return Fraction(observed - offset), None, [row]
        if i == 0 or i == len(times):
            nearest = visible[0] if i == 0 else visible[-1]
            return None, 'outside_reference_range', [nearest[2]]
        start, left, left_row = visible[i - 1]
        end, right, right_row = visible[i]
        if end - start > self._max_span:
            return None, 'reference_span_exceeded', [left_row, right_row]
        offset = Fraction(left * (end - at) + right * (at - start), end - start)
        return observed - offset, None, [left_row, right_row]
