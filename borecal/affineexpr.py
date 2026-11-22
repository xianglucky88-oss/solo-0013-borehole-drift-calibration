"""Affine expressions over bounded certificate-error and free anchor symbols."""
from fractions import Fraction


class Affine:
    """``constant + sum(coefficient * symbol)`` with exact Fraction terms."""

    __slots__ = ('constant', 'terms')

    def __init__(self, constant=0, terms=None):
        self.constant = Fraction(constant)
        self.terms = {symbol: Fraction(coef) for symbol, coef in (terms or {}).items()
                      if coef != 0}

    @classmethod
    def number(cls, value):
        return cls(value)

    def symbols(self):
        return set(self.terms)

    def free_symbols(self, bounded):
        return {symbol for symbol in self.terms if symbol not in bounded}

    def __add__(self, other):
        if isinstance(other, Affine):
            terms = dict(self.terms)
            for symbol, coef in other.terms.items():
                terms[symbol] = terms.get(symbol, 0) + coef
            return Affine(self.constant + other.constant, terms)
        return Affine(self.constant + other, dict(self.terms))

    __radd__ = __add__

    def __sub__(self, other):
        if isinstance(other, Affine):
            terms = dict(self.terms)
            for symbol, coef in other.terms.items():
                terms[symbol] = terms.get(symbol, 0) - coef
            return Affine(self.constant - other.constant, terms)
        return Affine(self.constant - other, dict(self.terms))

    def __rsub__(self, other):
        return Affine(other) - self

    def __mul__(self, scalar):
        scalar = Fraction(scalar)
        return Affine(self.constant * scalar,
                      {symbol: coef * scalar for symbol, coef in self.terms.items()})

    __rmul__ = __mul__

    def __neg__(self):
        return self * -1

    def __eq__(self, other):
        other = other if isinstance(other, Affine) else Affine(other)
        return self.constant == other.constant and self.terms == other.terms

    def __hash__(self):
        return hash((self.constant, tuple(sorted(self.terms.items()))))

    def __repr__(self):
        return f'Affine({self.constant}, {self.terms})'

    def as_dict(self):
        return {'constant': str(self.constant),
                'terms': {str(symbol): str(coef) for symbol, coef in sorted(self.terms.items())}}
