"""End-to-end checks for the certificate-aware calibration semantics.

Every rule from the metrology narrative is asserted here, while the legacy
``examples/smoke.py`` keeps the direct-standard baseline frozen.
"""
import json
from pathlib import Path
import sys
import tempfile

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from borecal import publish, read_delivery, read_profile
from borecal.linsolve import Infeasible, feasible, solve
from borecal.ranges import NotSignable, difference_range, median_range
from borecal.affineexpr import Affine
from fractions import Fraction
from borecal.supplement import supplement

ROOT = Path(__file__).resolve().parents[1]
CERTIFIED = json.loads((ROOT / 'examples' / 'certified.json').read_text(encoding='utf-8'))
SUPPLEMENT = json.loads((ROOT / 'examples' / 'supplement.json').read_text(encoding='utf-8'))


def test_exact_lp_basics():
    assert solve([('x', 0, 3)], [], {'x': 1}, maximize=True)[1] == 3
    assert solve([('x', 0, 3)], [], {'x': 1})[1] == 0
    assert not feasible([('x', 0, 3)], [({'x': 1}, '>=', 5)])
    coupled = [('e', -1, 1), ('k', -2, 2)]
    value, optimum = solve(coupled, [({'e': 1, 'k': -1}, '==', 0)],
                           {'e': 1}, maximize=True)
    assert optimum == 1 and value['k'] == 1
    try:
        solve([('x', 0, 1)], [({'x': 1}, '>=', 2)], {})
    except Infeasible:
        pass
    else:
        raise AssertionError('infeasible system was accepted')


def test_joint_range_is_not_marginal_concatenation():
    model = {'variables': [('err:c', -10, 10)], 'bounded': {'err:c'},
             'constraints': [], 'free_symbols': set()}
    a = [Affine(100, {'err:c': 1})]
    b = [Affine(50, {'err:c': 1})]
    assert median_range(model, a) == (Fraction(90), Fraction(110))
    # Shared same-sign error cancels exactly; independent marginal extrema
    # would have produced a spurious width of 40.
    assert difference_range(model, a, b) == (Fraction(50), Fraction(50))
    opposite = [Affine(50, {'err:c': -1})]
    assert difference_range(model, a, opposite) == (Fraction(30), Fraction(70))


def test_unanchored_components_yield_relative_only():
    model = {'variables': [('err:c', -10, 10)], 'bounded': {'err:c'},
             'constraints': [], 'free_symbols': {'free:root'}}
    absolute = [Affine(200, {'free:root': 1, 'err:c': 1})]
    relative = [Affine(180, {'free:root': 1, 'err:c': 1})]
    try:
        median_range(model, absolute)
    except NotSignable:
        pass
    else:
        raise AssertionError('free anchor produced an absolute median')
    assert difference_range(model, absolute, relative) == (Fraction(20), Fraction(20))
    foreign = [Affine(200, {'free:other': 1})]
    try:
        difference_range(model, absolute, foreign)
    except NotSignable:
        pass
    else:
        raise AssertionError('different free anchors shared a difference')


def test_contradictory_certificates_give_distinct_self_consistent_profiles():
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / 'cert.sqlite'
        outcome = publish(db, CERTIFIED)
        assert outcome == {'status': 'published', 'kind': 'certified',
                           'sha256': outcome['sha256']}
        assert publish(db, CERTIFIED)['status'] == 'replay'
        profile = read_profile(db, 'basalt-17', 'winter-c03')
        assert profile['kind'] == 'certified'
        by_h = {item['hypothesis']: item for item in profile['hypotheses']}
        assert set(by_h) == {'trust-alpha', 'trust-beta'}
        assert all(item['feasible'] for item in by_h.values())
        alpha = by_h['trust-alpha']['depth_facts'][1]
        beta = by_h['trust-beta']['depth_facts'][1]
        assert alpha['depth_mm'] == 300 and beta['depth_mm'] == 300
        # Self-consistent but different conditional profiles at the same depth.
        assert alpha['median_range_mc'] == ['11499', '11515']
        assert beta['median_range_mc'] == ['10479', '10495']
        assert alpha['median_range_mc'] != beta['median_range_mc']


def test_unconditional_profile_intersects_all_hypotheses():
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / 'cert.sqlite'
        publish(db, CERTIFIED)
        profile = read_profile(db, 'basalt-17', 'winter-c03')
        unconditional = profile['unconditional']
        depth_100 = next(f for f in unconditional['depth_facts'] if f['depth_mm'] == 100)
        assert depth_100['signable'] and depth_100['median_range_mc'] == ['11997', '11997']
        depth_300 = next(f for f in unconditional['depth_facts'] if f['depth_mm'] == 300)
        # The two conditional ranges are disjoint, so no unconditional range.
        assert not depth_300['signable']
        assert depth_300['blocked_reason'] == 'hypotheses_disjoint'


def test_delivery_ledger_separates_conditional_and_unconditional():
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / 'cert.sqlite'
        publish(db, CERTIFIED)
        ledger = {item['request']: item for item in
                  read_delivery(db, 'basalt-17', 'winter-c03')}
        assert ledger['unconditional-100']['status'] == 'delivered_unconditional'
        alpha = ledger['conditional-alpha-300']
        beta = ledger['conditional-beta-300']
        assert alpha['status'] == beta['status'] == 'delivered_conditional'
        assert alpha['median_range_mc'] != beta['median_range_mc']
        assert alpha['coverage_window_s'] == {'from_s': 2, 'to_s': 4}
        joint = ledger['joint-diff-100-300-alpha']
        assert joint['status'] == 'delivered_conditional'
        assert joint['difference_range_mc'] == ['482', '498']
        # Restricted conditional values are never handed out as ordinary temps.
        pending = ledger['unanchored-900']
        assert pending['status'] == 'pending'
        assert pending['reason'] == 'no_feasible_hypothesis'
        assert ledger['unknown-window']['status'] == 'pending'


def test_different_hypotheses_cannot_share_one_joint_difference():
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / 'cert.sqlite'
        publish(db, CERTIFIED)
        profile = read_profile(db, 'basalt-17', 'winter-c03')
        alpha = next(h for h in profile['hypotheses'] if h['hypothesis'] == 'trust-alpha')
        beta = next(h for h in profile['hypotheses'] if h['hypothesis'] == 'trust-beta')
        diff_alpha = next(f for f in alpha['difference_facts']
                          if (f['shallow_mm'], f['deep_mm']) == (100, 300))
        diff_beta = next(f for f in beta['difference_facts']
                         if (f['shallow_mm'], f['deep_mm']) == (100, 300))
        # Even though both layers are marginally signed, each joint difference
        # exists only inside its own hypothesis; there is no cross-hypothesis
        # combined difference in the unconditional profile.
        assert diff_alpha['signable'] and diff_beta['signable']
        assert diff_alpha['difference_range_mc'] != diff_beta['difference_range_mc']
        unconditional = next(f for f in profile['unconditional']['difference_facts']
                             if (f['shallow_mm'], f['deep_mm']) == (100, 300))
        assert not unconditional['signable']


def test_width_limit_flags_oversize_conditional_ranges():
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / 'cert.sqlite'
        publish(db, CERTIFIED)
        profile = read_profile(db, 'basalt-17', 'winter-c03')
        for hypothesis in profile['hypotheses']:
            for fact in hypothesis['depth_facts']:
                if fact['signable']:
                    assert fact['within_width_limit'] in (True, False)
        narrow = next(f for h in profile['hypotheses']
                      for f in h['depth_facts'] if f['depth_mm'] == 300)
        assert narrow['within_width_limit'] is True


def test_supplementary_certificate_does_not_rewrite_original_scope():
    report = supplement(CERTIFIED, SUPPLEMENT)
    assert report['scope_rewritten'] is False
    assert report['original_version'] == 'winter-c03'
    coverage = {item['depth_mm']: item for item in report['coverage'].values()}
    # The later certificate window only covers t=2; every depth also reads at
    # t=4, so no depth is fully covered by the supplement alone.
    assert all(not item['fully_covered'] for item in coverage.values())
    for response in report['delivery']:
        if response['status'] == 'delivered_conditional':
            assert response['supplementary_alone_signed'] is False


def test_immutability_is_preserved():
    modified = json.loads(json.dumps(CERTIFIED))
    modified['references'][0]['observed_mc'] += 5
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / 'immutable.sqlite'
        publish(db, CERTIFIED)
        try:
            publish(db, modified)
        except ValueError as exc:
            assert 'immutable' in str(exc)
        else:
            raise AssertionError('a certified release was overwritten')
        frozen = read_profile(db, 'basalt-17', 'winter-c03')
        alpha = next(h for h in frozen['hypotheses'] if h['hypothesis'] == 'trust-alpha')
        assert next(f for f in alpha['depth_facts'] if f['depth_mm'] == 300)[
            'median_range_mc'] == ['11499', '11515']


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items())
             if name.startswith('test_') and callable(value)]
    for test in tests:
        test()
        print(f'passed {test.__name__}')
    print(f'all {len(tests)} certificate semantics tests passed')
