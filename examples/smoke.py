from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from borecal import publish, read_profile

with TemporaryDirectory() as temp:
    db = Path(temp) / 'profiles.sqlite'
    source = json.loads(Path(__file__).with_name('boring.json').read_text(encoding='utf-8'))
    assert publish(db, source)['status'] == 'published'
    assert publish(db, source)['status'] == 'replay'
    initial = read_profile(db, 'basalt-17', 'winter-c01')
    assert [r['median_mc'] for r in initial['depths']] == ['21999/2', '9003', None]
    assert initial['depths'][0]['observations'][0]['reference_rows'] == [2, 1]
    assert [r['reason'] for r in initial['rejected']] == [
        'reference_span_exceeded', 'outside_reference_range', 'no_probe_reference', 'unplanned_depth']
    updated = deepcopy(source)
    updated['references'][1]['observed_mc'] += 3
    try:
        publish(db, updated)
    except ValueError as exc:
        assert 'immutable' in str(exc)
    else:
        raise AssertionError('frozen calibration was overwritten')
    updated['version'] = 'winter-c02'
    publish(db, updated)
    result = read_profile(db, 'basalt-17', 'winter-c02')
    assert result['depths'][0]['median_mc'] == '10998'
    assert result['depths'][1:] == initial['depths'][1:]
    assert read_profile(db, 'basalt-17', 'winter-c01') == initial
    try:
        read_profile(db, 'basalt-17', 'unknown')
    except ValueError as exc:
        assert 'unknown' in str(exc)
    else:
        raise AssertionError('unknown calibration returned facts')
    print(json.dumps(result, sort_keys=True))
