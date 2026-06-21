"""Minimal stdlib linear algebra for OLS regression — no numpy.

Just enough to run the regressions the cointegration test needs: solve a small
k x k normal-equations system and return coefficients with their standard errors.
Educational and dependency-free; not optimized for large matrices.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _matmul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    n, m, p = len(A), len(B), len(B[0])
    out = [[0.0] * p for _ in range(n)]
    for i in range(n):
        Ai = A[i]
        for k in range(m):
            a = Ai[k]
            if a == 0.0:
                continue
            Bk = B[k]
            oi = out[i]
            for j in range(p):
                oi[j] += a * Bk[j]
    return out


def _transpose(A: list[list[float]]) -> list[list[float]]:
    return [list(col) for col in zip(*A)]


def _inverse(A: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan inverse of a small square matrix."""
    n = len(A)
    M = [list(row) + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(A)]
    for col in range(n):
        # partial pivot
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            raise ValueError("singular matrix (regressors collinear)")
        M[col], M[piv] = M[piv], M[col]
        pivval = M[col][col]
        M[col] = [x / pivval for x in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0.0:
                factor = M[r][col]
                M[r] = [a - factor * b for a, b in zip(M[r], M[col])]
    return [row[n:] for row in M]


class OLSResult:
    def __init__(self, coef: list[float], se: list[float], resid: list[float], dof: int):
        self.coef = coef
        self.se = se
        self.resid = resid
        self.dof = dof

    def tstat(self, i: int) -> float:
        return self.coef[i] / self.se[i] if self.se[i] > 0 else 0.0


def ols(X: Sequence[Sequence[float]], y: Sequence[float]) -> OLSResult:
    """Ordinary least squares via normal equations: beta = (X'X)^-1 X'y.

    X: n rows of k regressors (include a constant column yourself if you want one).
    Returns coefficients, their standard errors, residuals, and residual dof.
    """
    Xl = [list(r) for r in X]
    yl = list(y)
    n, k = len(Xl), len(Xl[0])
    if n <= k:
        raise ValueError("need more observations than regressors")
    Xt = _transpose(Xl)
    XtX = _matmul(Xt, Xl)
    XtX_inv = _inverse(XtX)
    Xty = [[sum(Xt[i][r] * yl[r] for r in range(n))] for i in range(k)]
    beta = [row[0] for row in _matmul(XtX_inv, Xty)]

    resid = [yl[r] - sum(Xl[r][j] * beta[j] for j in range(k)) for r in range(n)]
    rss = sum(e * e for e in resid)
    dof = n - k
    sigma2 = rss / dof if dof > 0 else 0.0
    se = [math.sqrt(max(sigma2 * XtX_inv[j][j], 0.0)) for j in range(k)]
    return OLSResult(beta, se, resid, dof)
