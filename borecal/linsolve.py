"""Exact rational linear programming used for joint feasibility regions.

The shared common error of a certificate couples all of its rows: feasibility
and every signed range must come from one joint assignment of the bounded
error variables, never from per-layer extremes.  A standard two-phase simplex
over :class:`fractions.Fraction` keeps all results exact.

Tableau convention (minimization, reduced costs ``c_j - z_j``)
---------------------------------------------------------------
* Variables are shifted to non-negative columns; each high box becomes a
  ``y_j <= cap`` slack row so it remains active through every pivot.
* Functional rows carry slack (``<=``), surplus plus artificial (``>=``) or
  artificial (``==``) columns and are reoriented to a non-negative right
  hand side.
* A column enters when its reduced cost is strictly negative; the right hand
  side always equals the current objective value.  Bland's rule (smallest
  entering index, smallest basis index on ratio ties) prevents cycling.
"""
from fractions import Fraction


class Infeasible(Exception):
    """Raised when no assignment satisfies the constraints."""


def solve(variables, constraints, objective=None, maximize=False):
    """Optimize ``objective`` subject to variable boxes and constraints.

    ``variables`` is a list of ``(name, low, high)`` triples with finite
    boxes; ``constraints`` is a list of ``(coeffs, sense, rhs)`` with sense
    in ``{'<=', '>=', '=='}`` and coeffs mapping names to numbers.
    Returns ``(values, optimum)`` with exact Fractions, or raises
    :class:`Infeasible`.
    """
    shifted = [(name, Fraction(lo), Fraction(hi)) for name, lo, hi in variables]
    n = len(shifted)
    index = {name: j for j, (name, _, _) in enumerate(shifted)}
    # Caller objective coefficients c; internal tableau minimizes d, where
    # d = -c for maximization.  The constant shift always uses c, never d.
    external = {index[name]: Fraction(coef) for name, coef in (objective or {}).items()}
    internal = {j: (coef * -1 if maximize else coef) for j, coef in external.items()}

    prepared = []
    for j, (_, lo, hi) in enumerate(shifted):
        prepared.append(({j: Fraction(1)}, '<=', hi - lo))
    for coeffs, sense, rhs in constraints:
        terms = {index[name]: Fraction(coef) for name, coef in coeffs.items()}
        bound = Fraction(rhs) - sum(coef * shifted[j][1] for j, coef in terms.items())
        if bound < 0:
            # Every row needs a non-negative right hand side; flipping an
            # equality negates both sides without changing its meaning.
            terms = {j: -coef for j, coef in terms.items()}
            bound = -bound
            if sense == '<=':
                sense = '>='
            elif sense == '>=':
                sense = '<='
        prepared.append((terms, sense, bound))

    layout, cursor = [], n
    surplus = set()
    for terms, sense, bound in prepared:
        if sense == '<=':
            layout.append(('slack', cursor))
            cursor += 1
        elif sense == '>=':
            layout.append(('surplus_artificial', cursor))
            surplus.add(cursor)
            cursor += 2
        else:
            layout.append(('artificial', cursor))
            cursor += 1
    width = cursor + 1

    matrix, basis, artificial = [], [], set()
    for r, (terms, sense, bound) in enumerate(prepared):
        row = [Fraction(0)] * width
        for j, coef in terms.items():
            row[j] = coef
        kind, col = layout[r]
        if kind == 'slack':
            row[col] = Fraction(1)
            basis.append(col)
        elif kind == 'surplus_artificial':
            row[col] = Fraction(-1)
            row[col + 1] = Fraction(1)
            artificial.add(col + 1)
            basis.append(col + 1)
        else:
            row[col] = Fraction(1)
            artificial.add(col)
            basis.append(col)
        row[-1] = bound
        matrix.append(row)

    def pivot(enter, leave, cost):
        element = matrix[leave][enter]
        matrix[leave] = [value / element for value in matrix[leave]]
        for i, row in enumerate(matrix):
            if i != leave and row[enter]:
                factor = row[enter]
                matrix[i] = [value - factor * matrix[leave][k] for k, value in enumerate(row)]
        factor = cost[enter]
        cost = [value - factor * matrix[leave][k] for k, value in enumerate(cost)]
        basis[leave] = enter
        return cost

    def minimize(cost, blocked=()):
        blocked = set(blocked)
        while True:
            candidates = [j for j in range(cursor) if cost[j] < 0 and j not in blocked]
            if not candidates:
                return cost
            enter = min(candidates)
            leave, ratio = None, None
            for i, row in enumerate(matrix):
                if row[enter] > 0:
                    candidate = row[-1] / row[enter]
                    if (leave is None or candidate < ratio
                            or (candidate == ratio and basis[i] < basis[leave])):
                        leave, ratio = i, candidate
            if leave is None:
                raise Infeasible('simplex column is unbounded')
            cost = pivot(enter, leave, cost)

    if artificial:
        # Phase I objective w = sum of artificials, expressed via the
        # artificial rows.  The reduced cost of a non-basic column is the
        # negative of its coefficient in that expression, so the canonical
        # cost row is the negated row sum with every artificial column
        # zeroed.  Surplus and artificial columns never enter in phase I.
        row_sum = [Fraction(0)] * width
        for i, row in enumerate(matrix):
            if basis[i] in artificial:
                row_sum = [a + b for a, b in zip(row_sum, row)]
        phase_one = [-value for value in row_sum]
        for col in artificial:
            phase_one[col] = Fraction(0)
        # Only artificial columns are blocked from re-entering; surplus
        # columns are ordinary variables and must stay available, otherwise
        # degenerate pivots needed to clear a redundant row are impossible.
        phase_one = minimize(phase_one, artificial)
        residual = sum(matrix[i][-1] for i, basic in enumerate(basis) if basic in artificial)
        if residual != 0:
            raise Infeasible('phase I residual is positive')
        for i in reversed(range(len(matrix))):
            if basis[i] not in artificial:
                continue
            candidates = [j for j, value in enumerate(matrix[i][:-1])
                          if value != 0 and j not in artificial]
            if candidates:
                phase_one = pivot(candidates[0], i, phase_one)
            else:
                del matrix[i]
                del basis[i]
        for row in matrix:
            for col in artificial:
                row[col] = Fraction(0)

    # Phase II rebuilds a canonical reduced-cost row for the real objective.
    phase_two = [Fraction(0)] * width
    for j, coef in internal.items():
        phase_two[j] = coef
    for i, basic in enumerate(basis):
        factor = phase_two[basic]
        if factor:
            phase_two = [a - factor * b for a, b in zip(phase_two, matrix[i])]
    phase_two = minimize(phase_two)

    values = {name: Fraction(lo) for name, lo, _ in shifted}
    for i, basic in enumerate(basis):
        if basic < n:
            values[shifted[basic][0]] = shifted[basic][1] + matrix[i][-1]
    # RHS is the minimum of d . y in shifted coordinates.  Convert to the
    # caller's objective c . x via c . x = c . (y + l) = c . y + c . l,
    # restoring the maximization sign through d = sign * c.
    sign = -1 if maximize else 1
    # Empirically the cost-row RHS holds minus the attained minimum of
    # d . y; negate it before mapping back to the caller's coordinates.
    shifted_minimum = -phase_two[-1]
    caller_in_shifted = sign * shifted_minimum
    constant = sum(coef * shifted[j][1] for j, coef in external.items())
    return values, caller_in_shifted + constant


def feasible(variables, constraints):
    """Return True only when the whole constraint system is satisfiable."""
    try:
        solve(variables, constraints, {})
    except Infeasible:
        return False
    return True
