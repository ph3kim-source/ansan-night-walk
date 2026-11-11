# -*- coding: utf-8 -*-
"""시연 프로토타입 검증 — python -m pytest tests/test_proto.py -q
준비: python src/synth_inventory.py → python src/ingest_inventory.py
"""
import pathlib
import re
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

PROTO_FILES = [SRC / "proto_app.py", SRC / "proto_ui.py"] + sorted((SRC / "proto_pages").glob("*.py"))
PAGES = ["proto_pages/route.py", "proto_pages/bus.py", "proto_pages/lights.py",
         "proto_pages/priority.py", "proto_pages/sources.py"]


def test_no_forbidden_words():
    """CLAUDE.md 0절 — 화면 코드에 '안전'·'안심'이 없어야 한다."""
    hits = [(f.name, m) for f in PROTO_FILES for m in re.findall("안전|안심", f.read_text(encoding="utf-8"))]
    assert hits == []


def test_core_params_unchanged():
    import params as PM
    assert len(PM.P) == 15 and PM.summary() == {"A": 2, "B": 8, "C": 1, "X": 4}


def test_slot_night_of():
    import night_core as NC
    assert NC.slot_label(NC.slot_index(4, 1), long=True).startswith("금요일 밤 1시 (달력상 토요일")


@pytest.mark.parametrize("page", PAGES)
def test_pages_render(page):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(SRC / "proto_app.py"), default_timeout=600)
    at.run()
    if page != PAGES[0]:
        at.switch_page(page).run()
    assert len(at.exception) == 0, [e.value for e in at.exception]
    if page == PAGES[0]:
        assert len(at.metric) >= 4                     # 경로 계산까지 성공


def test_route_slot_changes():
    """요일·시각을 바꿔도 깨지지 않고, 다른 시각 비교가 돈다."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(SRC / "proto_app.py"), default_timeout=600)
    at.run()
    at.button_group(key="dow").set_value("화").run()
    at.button_group(key="hour").set_value("새벽 1시").run()
    at.toggle(key="cmp_on").set_value(True).run()
    assert len(at.exception) == 0, [e.value for e in at.exception]
    assert len(at.metric) >= 7


def test_alpha_grid_matches_bisection():
    """α 격자(night_core) vs 이분탐색(route.plan) — 본체 데이터 30쌍에서 저활성 노출이 비슷해야 한다."""
    import night_core as NC, params as PM, route as RT, score as SC
    P = ROOT / "data" / "processed"
    c = pd.read_csv(P / "cells.csv", encoding="utf-8-sig")
    n = pd.read_csv(P / "nodes.csv", encoding="utf-8-sig")
    e = pd.read_csv(P / "edges.csv")
    act = SC.cell_score(c)[0][n["cell"].to_numpy()]
    ee = SC.edge_score(n, e, act)
    thr = SC.dark_threshold(ee, PM.DARK_Q.value)
    Gx, G = RT.build(n, ee), NC.NightGraph(n, e)
    rng = np.random.default_rng(7)
    D0 = D1 = D2 = 0.0
    k = 0
    while k < 30:
        s, t = (int(x) for x in rng.choice(len(n), 2, replace=False))
        if not 800 < np.hypot(n.x[s] - n.x[t], n.y[s] - n.y[t]) < 4000:
            continue
        r = RT.plan(Gx, s, t, PM.DETOUR.value, thr)
        b = G.choose(G.frontier(s, t, ee["act"].to_numpy(), thr), PM.DETOUR.value)
        assert b["len_m"] <= r["base"]["len_m"] * (1 + PM.DETOUR.value) + 1e-6
        D0, D1, D2, k = D0 + r["base"]["dark_m"], D1 + r["best"]["dark_m"], D2 + b["dark_m"], k + 1
    assert abs((D0 - D2) - (D0 - D1)) <= 0.15 * max(D0 - D1, 1)   # 감소량 차이 15% 이내
