"""Purged + embargoed K-fold cross-validation splits.

Time-series CV leaks when a test fold sits adjacent to training samples whose
labels overlap in time. Purging removes training samples too close to the test
fold; an embargo drops a few more right after it. This is what makes the
out-of-sample evaluation (and therefore the DSR trial count) honest.

Pure stdlib. Yields (train_indices, test_indices) tuples.
"""

from __future__ import annotations

from collections.abc import Iterator


def purged_kfold(n_samples: int, k: int = 5, embargo: int = 0) -> Iterator[tuple[list[int], list[int]]]:
    if k < 2:
        raise ValueError("k must be >= 2")
    if n_samples < k:
        raise ValueError("n_samples must be >= k")

    fold_sizes = [n_samples // k + (1 if i < n_samples % k else 0) for i in range(k)]
    bounds = []
    start = 0
    for size in fold_sizes:
        bounds.append((start, start + size))
        start += size

    for test_start, test_end in bounds:
        test_idx = list(range(test_start, test_end))
        purge_lo = test_start
        purge_hi = min(n_samples, test_end + embargo)   # embargo after the test fold
        train_idx = [i for i in range(n_samples) if i < purge_lo or i >= purge_hi]
        yield train_idx, test_idx
