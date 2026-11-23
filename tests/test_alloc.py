# -*- coding: utf-8 -*-
"""점수 해상도 스위치 검증 (수정사항 #13) — python -m pytest tests/test_alloc.py -q"""
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
P = ROOT / "data" / "processed"


def _cells():
    return pd.read_csv(P / "cells.csv", encoding="utf-8-sig")


def test_default_is_current():
    """기본값(uniform)은 현행 점수 첫 항(pop_night)과 값이 똑같아야 한다 — 문서 · 보고서 수치 불변."""
    import alloc as AL
    import params as PM
    c = _cells()
    assert PM.POP_ALLOC.value == "uniform"
    assert np.array_equal(AL.flow(c), c["pop_night"].to_numpy(dtype=float))


def test_exp_params_outside_core():
    """실험 스위치는 본체 근거 대장(P)에 들어가지 않는다 — 본체 15개 · A2/B8/C1/X4 그대로."""
    import params as PM
    exp = {p.name for p in PM.EXP}
    assert {"POP_ALLOC", "HOME_W", "RES_SHUFFLE_SEED"} <= exp
    assert not exp & {p.name for p in PM.P}
    assert len(PM.P) == 15 and PM.summary() == {"A": 2, "B": 8, "C": 1, "X": 4}


def test_homes_keeps_block_totals():
    """homes 는 1km 안 합계를 그대로 두고 1km 안 분포만 바꾼다."""
    import alloc as AL
    c = _cells()
    b = AL.blocks(c)
    h = AL.homes(c)
    s0 = pd.Series(c["pop_night"].to_numpy(dtype=float)).groupby(b).sum()
    s1 = pd.Series(h).groupby(b).sum()
    assert np.allclose(s0.to_numpy(), s1.loc[s0.index].to_numpy())
    assert (h >= 0).all()


def test_shuffled_keeps_block_values():
    """대조군은 1km 안 값의 분포를 그대로 두고 자리만 바꾼다."""
    import alloc as AL
    c = _cells()
    b = AL.blocks(c)
    w = AL.home_weight(c, "size")
    ws = AL.shuffled(w, b, 13)
    for k in np.unique(b):
        m = b == k
        assert np.array_equal(np.sort(w[m]), np.sort(ws[m]))
    assert not np.array_equal(w, ws)


def test_act_lex_breaks_ties():
    """사전식 순위 — min 이 같으면 max 가 큰 쪽이 밝다(시연판 ACT_TIEBREAK 와 같은 규칙)."""
    import alloc as AL
    f = np.array([.2, .2, .2, .9])
    a = np.array([.5, .9, .3, .1])
    assert list(np.argsort(AL.act_lex(f, a))) == [3, 2, 0, 1]
