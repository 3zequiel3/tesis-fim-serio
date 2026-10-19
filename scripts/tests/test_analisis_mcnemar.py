"""Reproduce the paired comparison of Table 19 (v5.1-tesis) from its 2x2 tables."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("analisis_mcnemar", Path(__file__).parents[1] / "analisis_mcnemar.py")
assert SPEC and SPEC.loader
mcn = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(mcn)

# a: both; b: FIM only; c: control only; d: neither (Table 19 and Annex L.3).
REPLICAS = {1: (72, 428, 0, 0), 2: (98, 397, 0, 5), 3: (94, 405, 0, 1)}

# (lower, upper) rounded to four decimals, as Table 19 and its note report them.
CON_PHI = {1: (0.8217, 0.8841), 2: (0.7550, 0.8268), 3: (0.7723, 0.8419)}
SIN_PHI = {1: (0.8217, 0.8841), 2: (0.7553, 0.8266), 3: (0.7725, 0.8418)}
MCNEMAR = {1: 426.00, 2: 395.00, 3: 403.00}


@pytest.mark.parametrize("replica", sorted(REPLICAS))
def test_interval_with_phi_correction_matches_table_19(replica: int) -> None:
    _, lo, hi = mcn.newcombe_paired(*REPLICAS[replica])
    assert (round(lo, 4), round(hi, 4)) == CON_PHI[replica]


@pytest.mark.parametrize("replica", sorted(REPLICAS))
def test_interval_without_phi_correction_reproduces_entrega_tesis(replica: int) -> None:
    _, lo, hi = mcn.newcombe_paired(*REPLICAS[replica], corregir_phi=False)
    assert (round(lo, 4), round(hi, 4)) == SIN_PHI[replica]


@pytest.mark.parametrize("replica", sorted(REPLICAS))
def test_mcnemar_statistic_matches_table_19(replica: int) -> None:
    _, b, c, _ = REPLICAS[replica]
    chi2, p = mcn.mcnemar(b, c)
    assert round(chi2, 2) == MCNEMAR[replica]
    assert p < 0.001


def test_empty_margin_sets_phi_to_zero_in_both_modes() -> None:
    # Replica 1 has d = 0, so a margin is empty and the correction cannot apply.
    assert mcn.newcombe_paired(*REPLICAS[1]) == mcn.newcombe_paired(*REPLICAS[1], corregir_phi=False)
