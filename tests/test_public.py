# -*- coding: utf-8 -*-
"""공개 실데이터 검증 (수정사항 #15) — python -m pytest tests/test_public.py -q
준비: python src/collect_public.py → python src/public_data.py → python src/ingest_inventory.py
원본(data/public/raw)이 없으면 원본이 필요한 시험은 건너뛴다."""
import datetime
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import public_data as PD  # noqa: E402

DER = ROOT / "data" / "public" / "derived"
need_raw = pytest.mark.skipif(not PD.available(), reason="data/public/raw 없음 — python src/collect_public.py")
need_der = pytest.mark.skipif(not (DER / "edge_public.csv").exists(), reason="python src/public_data.py 먼저")


def _hm(h):
    return h * 60


@pytest.mark.parametrize("day,sunset,dusk", [
    (datetime.date(2026, 12, 15), "17:14", "17:43"),
    (datetime.date(2026, 6, 15), "19:54", "20:26"),
])
def test_sun_times_vs_reference(day, sunset, dusk):
    """서울(37.5665, 126.978) — timeanddate.com 표와 2분 안. 식이 맞으면 안산 값도 맞다."""
    ref = lambda s: int(s[:2]) * 60 + int(s[3:])
    _, s = PD.sun_times(day, 37.5665, 126.978)
    _, d = PD.sun_times(day, 37.5665, 126.978, zenith=96.0)
    assert abs(_hm(s) - ref(sunset)) <= 2 and abs(_hm(d) - ref(dusk)) <= 2


def test_station_walk_toy():
    """최단경로 나무를 거슬러 올라가며 흐름을 더하는 논리 — 일직선 그래프 0-1-2-3, 역은 0, 집은 2(1)·3(3)."""
    nodes = pd.DataFrame({"x": [0.0, 100, 200, 300], "y": 0.0, "lon": 0.0, "lat": 0.0, "dong": "가", "cell": [0, 1, 2, 3]})
    edges = pd.DataFrame({"u": [0, 1, 2], "v": [1, 2, 3], "len_m": [100.0, 100, 100]})
    cells = pd.DataFrame({"x": [0.0, 100, 200, 300], "y": 0.0})
    st = pd.DataFrame({"station": ["역"], "line": ["선"], "x": [0.0], "y": [0.0], "a22": [10.0], "a23": [0.0],
                       "a24": [0.0], "industrial": [False]})
    F, use = PD.station_walk(nodes, edges, cells, st, max_m=1500, w=np.array([0, 0, 1.0, 3.0]))
    assert np.allclose(F[0], [10, 10, 7.5]) and np.allclose(F[1:], 0)
    # 산업단지역이면 흐름이 없어야 한다
    F2, _ = PD.station_walk(nodes, edges, cells, st.assign(industrial=True), max_m=1500, w=np.array([0, 0, 1.0, 3.0]))
    assert np.allclose(F2, 0)


def test_links_toy():
    """블록 = 교차로 사이 사슬. T자 0-1-2 · 1-3-4: 노드 1 은 교차로(차수 3), 노드 3 은 차수 2 → 간선 1-3 과 3-4 가 한 블록."""
    import night_core as NC
    nodes = pd.DataFrame({"x": [0.0, 100, 200, 100, 100], "y": [0.0, 0, 0, 100, 200], "lon": 0.0, "lat": 0.0,
                          "dong": "가", "cell": 0})
    edges = pd.DataFrame({"u": [0, 1, 1, 3], "v": [1, 2, 3, 4], "len_m": [100.0, 100, 100, 100]})
    lab = NC.NightGraph(nodes, edges).links()
    assert lab[2] == lab[3] and len({lab[0], lab[1], lab[2]}) == 3


@need_raw
def test_korail_parser_matches_line_totals():
    """역별 하차 합 = 노선 합계. 노선 소계 행이 마지막 역(서해선 → 원시)으로 붙으면 깨진다(#15 에서 실제로 틀렸던 것)."""
    path = sorted(PD.RAW.glob("korail_시간대별승하차_*.xlsx"))[-1]
    k, ym, by_line = PD.korail_hourly(path)
    assert ym is not None
    assert k["station"].notna().all()
    for ln, g in k[k["kind"] == "하차"].groupby("line"):
        lt = by_line[(by_line["line"] == ln) & (by_line["kind"] == "하차")]
        assert int(pd.to_numeric(g["합계"]).sum()) == int(lt["합계"].iloc[0]), ln
    assert not k.duplicated(["line", "station", "kind"]).any()


@need_der
def test_derived_tables():
    e = pd.read_csv(ROOT / "data" / "processed" / "edges.csv")
    ep = pd.read_csv(DER / "edge_public.csv", encoding="utf-8-sig")
    assert len(ep) == len(e) and (ep["highway"] != "unknown").all()
    big = e["len_m"][ep["major"]].sum() / e["len_m"].sum()
    assert 0.2 < big < 0.5                                       # 큰길 길이 비중(실측 32.8%)
    L = pd.read_csv(DER / "lights.csv", encoding="utf-8-sig")
    assert "대부동" not in set(L["dong"]) and L["dong"].nunique() <= 24
    st = pd.read_csv(DER / "stations.csv", encoding="utf-8-sig")
    assert not st.duplicated(["line", "station"]).any()
    assert st["a_day"].max() < 30000                             # 노선 소계(하루 6만)가 역으로 섞이지 않았다
    rep = json.loads((DER / "report.json").read_text(encoding="utf-8"))
    assert rep["korail_check"]["불일치"] == []


@need_der
def test_sidewalk_and_accidents():
    """#26 — 차도 옆 보도(OSM footway=sidewalk)는 footway 간선의 일부 · 사고 다발지역은 안산 · 4유형 · 범위 고리가 중심을 감싼다."""
    ep = pd.read_csv(DER / "edge_public.csv", encoding="utf-8-sig")
    side = ep["sidewalk"].astype(str).str.lower().eq("true")
    assert side.sum() > 0 and (ep.loc[side, "highway"] == "footway").all()
    p = DER / "accidents.csv"
    if not p.exists():
        pytest.skip("교통사고 다발지역 원본 없음 — python src/collect_public.py accidents")
    a = pd.read_csv(p, encoding="utf-8-sig")
    assert set(a["type"]) <= {"보행노인", "보행어린이", "스쿨존어린이", "자전거"}
    assert a["name"].str.contains("구 ").all() and a["lat"].between(37.1, 37.5).all()
    for _, r in a.iterrows():
        ring = np.array(json.loads(r["ring"]))
        assert ring[:, 0].min() < r["lat"] < ring[:, 0].max() and ring[:, 1].min() < r["lon"] < ring[:, 1].max()


@need_der
def test_lights_page_real_tabs():
    """보안등 점검 화면 — 두 탭(① 4개 지표 ② 3개 지표)이 실데이터로 렌더된다."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "src" / "proto_app.py"), default_timeout=600)
    at.run()
    at.switch_page("proto_pages/lights.py").run()
    assert len(at.exception) == 0, [x.value for x in at.exception]
    assert len(at.tabs) == 2 and len(at.metric) >= 7
