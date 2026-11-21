"""End-to-end checks for dwell plans, signed windows, and late reviews."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from borecal import publish, read_profile
from borecal.contract import decode
from borecal.drift import DriftIndex
from borecal.dwell import (Dwell, correct_series, find_windows, overlapping,
                           time_weighted_median)

HERE = Path(__file__).with_name
dwell_doc = json.loads(HERE('dwell.json').read_text(encoding='utf-8'))
review_one = json.loads(HERE('review-1.json').read_text(encoding='utf-8'))
review_two = json.loads(HERE('review-2.json').read_text(encoding='utf-8'))

with TemporaryDirectory() as temp:
    db = Path(temp) / 'dwell.sqlite'

    # --- first-window policy: earliest provable window, idempotent replay ---
    assert publish(db, dwell_doc)['status'] == 'published'
    assert publish(db, dwell_doc)['status'] == 'replay'
    first = read_profile(db, 'basalt-18', 'dwell-c01')
    assert first['mode'] == 'dwell'
    signs = {sign['dwell_id']: sign for sign in first['signs']}

    d1 = signs['d1']
    # the t=6 reading needs the reference arriving at t=7: nothing can be
    # signed before that right-hand reference exists, so the first signable
    # instant is the evidence arrival time t=7, not the rejected t=8 tail.
    assert d1['status'] == 'signed'
    assert d1['signed_at_s'] == 7 and d1['first_signable_at_s'] == 7
    assert d1['extra_wait_s'] == 0
    window = d1['window']
    assert [point['at_s'] for point in window['points']] == [2, 4, 6]
    assert window['time_weighted_median_mc'] == '21977/2'
    assert window['reference_rows'] == [1, 2, 3]
    # the unconfirmed t=8 tail stays rejected and never enters the window
    assert [r['reason'] for r in d1['rejected']] == ['outside_reference_range']
    assert {8} <= {r['at_s'] for r in d1['rejected']}

    d2 = signs['d2']
    assert d2['status'] == 'signed' and d2['signed_at_s'] == 16
    assert d2['window']['time_weighted_median_mc'] == '9001'
    # the earliest provable window starts at the first reading; later denser
    # readings can never shrink or displace an already signed window
    assert [point['at_s'] for point in d2['window']['points']] == [12, 14, 16]
    assert d2['window']['start_s'] == 12

    # probe without references and conflicting overlapping dwells cannot sign
    assert signs['d3']['status'] == 'no_provable_window'
    assert signs['d4']['status'] == 'conflicting_dwell'
    assert signs['d5']['status'] == 'conflicting_dwell'
    assert first['conflicts'] == {'d4': ['d5'], 'd5': ['d4']}

    facts = {fact['depth_mm']: fact for fact in first['depths']}
    assert facts[500]['status'] == 'confirmed'
    assert facts[500]['median_mc'] == '21977/2'
    # planned depths without a trusted signature stay null, never delivered
    assert facts[700]['status'] == 'unconfirmed' and facts[700]['median_mc'] is None
    assert facts[800]['status'] == 'unconfirmed'
    assert facts[800]['reason'] == 'conflicting_dwell'
    # a planned depth with readings but no dwell plan cannot borrow them
    assert facts[100]['status'] == 'unconfirmed'
    assert facts[100]['reason'] == 'no_signed_window'

    unused = {row['reading_row']: row for row in first['unused_readings']}
    assert unused[15]['reason'] == 'unplanned_depth'
    assert all(unused[row]['reason'] == 'outside_dwell' for row in (11, 12, 13, 14))

    # --- dwell_end policy: same evidence later, waiting cost made explicit ---
    waiting = copy.deepcopy(dwell_doc)
    waiting['sign_policy'] = 'dwell_end'
    waiting['version'] = 'dwell-c01-wait'
    publish(db, waiting)
    waited = read_profile(db, 'basalt-18', 'dwell-c01-wait')
    waited_signs = {sign['dwell_id']: sign for sign in waited['signs']}
    w2 = waited_signs['d2']
    assert w2['first_signable_at_s'] == 16 and w2['signed_at_s'] == 18
    assert w2['wait_used_s'] == 8 and w2['extra_wait_s'] == 2
    # the first-window release is untouched
    assert read_profile(db, 'basalt-18', 'dwell-c01') == first

    # --- late references: falsification vs. alternative, old release frozen ---
    publish(db, review_one)
    initial = read_profile(db, 'basalt-19', 'dwell-r01')
    q1 = next(sign for sign in initial['signs'] if sign['dwell_id'] == 'q1')
    assert q1['status'] == 'signed' and q1['signed_at_s'] == 4
    assert {item['reference_row'] for item in q1['window']['reference_snapshot']} == {1, 2}
    publish(db, review_two)
    reviewed = read_profile(db, 'basalt-19', 'dwell-r02')
    review = reviewed['review']
    by_id = {item['dwell_id']: item for item in review['reviewed']}
    assert by_id['q1']['status'] == 'falsified'
    assert by_id['q1']['prior_window_holds'] is False
    assert by_id['q1']['replay_with_original_view_holds'] is True
    assert by_id['q2']['status'] == 'alternative_supported'
    assert by_id['q2']['alternative_window']['time_weighted_median_mc'] == '7002'
    assert review['affected_depths_mm'] == [400, 600]
    assert {fact['depth_mm'] for fact in review['affected_depth_facts']} == {400, 600}
    # the original signed profile still reads back byte-for-byte
    assert read_profile(db, 'basalt-19', 'dwell-r01') == initial

    # reference corrections must arrive under a new version
    tampered = copy.deepcopy(review_one)
    tampered['references'][0]['observed_mc'] += 5
    try:
        publish(db, tampered)
    except ValueError as exc:
        assert 'immutable' in str(exc)
    else:
        raise AssertionError('frozen dwell release was overwritten')

    # --- unit-level mechanics -------------------------------------------------
    parsed = decode(dwell_doc)
    (_, _, max_span, _, references, readings, stability, dwells, _, _) = parsed
    index = DriftIndex(references, max_span)
    d1_dwell = next(dwell for dwell in dwells if dwell.dwell_id == 'd1')
    points, rejected = correct_series(d1_dwell, readings, index, view_until=6)
    # at view t=6 the t=6 reading has no right-hand reference yet
    assert all(point['at_s'] != 6 for point in points)
    assert rejected and rejected[0]['reason'] == 'outside_reference_range'
    assert not find_windows(points, stability), 'tail must not be bridged'
    # at view t=7 the right reference has arrived and the window is provable
    points7, rejected7 = correct_series(d1_dwell, readings, index, view_until=7)
    assert find_windows(points7, stability)

    # a gap wider than the sampling interval breaks continuity
    gap_dwell = Dwell('g', 'garnet', 500, 1, 0, 10)
    gap_points = [
        {'at_s': 0, 'corrected_mc': 5, 'observed_mc': 5,
         'reading_row': 1, 'reference_rows': [1]},
        {'at_s': 2, 'corrected_mc': 6, 'observed_mc': 6,
         'reading_row': 2, 'reference_rows': [1]},
        {'at_s': 9, 'corrected_mc': 7, 'observed_mc': 7,
         'reading_row': 3, 'reference_rows': [1]},
    ]
    assert not find_windows(gap_points, stability)

    # median is weighted by time, not by row count
    weighted = time_weighted_median([
        {'at_s': 0, 'corrected_mc': 1},
        {'at_s': 2, 'corrected_mc': 100},
        {'at_s': 4, 'corrected_mc': 100},
    ])
    assert weighted == 100

    # overlap detection only applies within one probe
    other = [Dwell('a', 'p1', 1, 1, 0, 5), Dwell('b', 'p2', 1, 2, 1, 4),
             Dwell('c', 'p1', 1, 3, 5, 9)]
    assert all(not rivals for rivals in overlapping(other).values())

print('dwell smoke checks passed')
