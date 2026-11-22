"""Joint feasible ranges for depth medians and paired temperature differences.

Every range is optimized over the *same* feasible region of the bounded
certificate-error variables.  Per-layer extrema computed independently cannot
be combined into a difference, because the error assignments that attain the
two extremes generally differ; the difference is optimized jointly.
"""
from collections import defaultdict
from fractions import Fraction

from .linsolve import Infeasible, solve

LP_BOUND = 10**9


class NotSignable(Exception):
    """Raised when an expression cannot be bounded under the hypothesis."""


def _expression_constraint(name, affine, bounded_names):
    coeffs = {str(symbol): coef for symbol, coef in affine.terms.items()
              if str(symbol) in bounded_names}
    return ({name: 1, **{symbol: -coef for symbol, coef in coeffs.items()}},
            '==', affine.constant)


def _order_constraints(names):
    return [({lower: 1, upper: -1}, '<=', 0)
            for lower, upper in zip(names, names[1:])]


def _median_builder(model, values, tag):
    """Build helper variables equalling the ordered values plus a median.

    Returns ``(variables, constraints, median_name)``.  For an odd sample the
    median helper equals the central order statistic; for an even sample it is
    the exact midpoint of the two central order statistics.  The median
    helper is unbounded so it can follow every feasible assignment.
    """
    bounded_names = {name for name, _, _ in model['variables']}
    n = len(values)
    helpers = [f'{tag}:ord:{k}' for k in range(n)]
    median_name = f'{tag}:median'
    variables = list(model['variables']) + [
        (name, -LP_BOUND, LP_BOUND) for name in helpers] + [
        (median_name, -LP_BOUND, LP_BOUND)]
    constraints = list(model['constraints'])
    for name, affine in zip(helpers, values):
        constraints.append(_expression_constraint(name, affine, bounded_names))
    constraints.extend(_order_constraints(helpers))
    if n % 2:
        constraints.append(({median_name: 1, helpers[n // 2]: -1}, '==', 0))
    else:
        left, right = n // 2 - 1, n // 2
        constraints.append(
            ({median_name: 2, helpers[left]: -1, helpers[right]: -1}, '==', 0))
    return variables, constraints, median_name


def _has_free_symbol(values):
    return any(str(symbol).startswith('free:')
               for affine in values for symbol in affine.terms)


def median_range(model, values):
    """Exact min/max of the median of corrected values at one planned depth."""
    if not values:
        return None
    if _has_free_symbol(values):
        raise NotSignable('depth belongs to an unanchored component')
    variables, constraints, median_name = _median_builder(model, values, 'depth')
    return _extrema(variables, constraints, {median_name: 1})


def difference_range(model, shallow_values, deep_values):
    """Joint feasible range of median(shallow) minus median(deep)."""
    if not shallow_values or not deep_values:
        raise NotSignable('a difference needs signed readings at both depths')
    shallow_free = {str(s) for affine in shallow_values for s in affine.terms
                    if str(s).startswith('free:')}
    deep_free = {str(s) for affine in deep_values for s in affine.terms
                 if str(s).startswith('free:')}
    if shallow_free != deep_free:
        raise NotSignable('depths sit in different anchor components')

    shallow_vars, shallow_rows, shallow_median = _median_builder(
        model, shallow_values, 'shallow')
    deep_vars, deep_rows, deep_median = _median_builder(
        model, deep_values, 'deep')
    known = {name for name, _, _ in shallow_vars}
    variables = shallow_vars + [item for item in deep_vars if item[0] not in known]
    constraints = shallow_rows + deep_rows
    objective = {shallow_median: 1, deep_median: -1}
    if shallow_free:
        # Free anchors are not LP variables; they cancel only when the same
        # single anchor appears on both medians with opposite net coefficient
        # once the deep median is subtracted from the shallow median.
        combined = defaultdict(Fraction)
        for affine in shallow_values:
            for symbol, coef in affine.terms.items():
                symbol = str(symbol)
                if symbol.startswith('free:'):
                    combined[symbol] += coef
        for affine in deep_values:
            for symbol, coef in affine.terms.items():
                symbol = str(symbol)
                if symbol.startswith('free:'):
                    combined[symbol] -= coef
        if len(combined) != 1 or any(coef != 0 for coef in combined.values()):
            raise NotSignable('free anchor does not cancel across the pair')
    return _extrema(variables, constraints, objective)


def _extrema(variables, constraints, objective):
    _, maximum = solve(variables, constraints, objective, maximize=True)
    _, minimum = solve(variables, constraints, objective)
    return minimum, maximum


def width(interval):
    return interval[1] - interval[0]
