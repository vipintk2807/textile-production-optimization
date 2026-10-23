"""Performance smoke tests (run with:  python -m pytest -m performance).

They assert only that validated schedules are obtained and the time limit is respected; they
do not assert speed targets because none has been measured on representative hardware.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_benchmarks  # noqa: E402

pytestmark = pytest.mark.performance


def test_small_benchmark_instances_produce_validated_schedules():
    rows = run_benchmarks.run(limit=5.0, workers=1)
    assert all(r["validated"] for r in rows if r["orders"] <= 10)
    assert all(r["solve_s"] <= 5.0 + 5.0 for r in rows)  # limit respected within generous variation
