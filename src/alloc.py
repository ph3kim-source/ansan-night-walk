# -*- coding: utf-8 -*-
"""
야간 유동인구 대체값의 100m 안분 방식 — 점수 해상도 가설 검증 (수정사항 #13)

본체 점수의 첫 항(야간 유동인구)은 실데이터(DS-032 · 014)가 없어 SGIS 1km 격자 인구로 대신한다.
prep.py 는 그 1km 인구를 100m 칸에 균등하게 나눈다 → 1km 안의 칸이 전부 같은 값이다.
CLAUDE.md §7 의 미검증 가설 '점수 해상도(1km 균등 안분)가 지금의 병목이다'를 재려고
1km 합계는 그대로 두고 1km 안의 분포만 바꾸는 방식을 둔다. 고르는 값은 params.POP_ALLOC (기본 uniform = 현행).

  uniform         현행. cells.csv 의 pop_night 그대로
  homes           같은 1km 안에서 OSM 주거건물 규모(HOME_W)에 비례해 나눈다. 주거건물이 없는 1km 는 균등 그대로
  homes_or_shops  max(분위(homes), 분위(상가 수)) — '주민이 산다 OR 가게가 있다'(선언 → max, 가중치 없음).
                  homes 만 쓰면 상가만 있는 셀이 0 이 되는 문제(#09 실측 27.6%)를 시연판 FLOW_FORM 과 같은 방식으로 보정한다.
                  상가 수 = 반경 ANCHOR_R_M 안의 상가 중 심야 앵커 · 유흥을 뺀 것(앵커는 둘째 항, 유흥은 점수에서 뺀다)

cells.csv 는 바꾸지 않는다 — synth_inventory.py 가 pop_night 를 '1km 균등'으로 전제하고 다시 읽기 때문이다.
점수에 쓰는 값만 flow(cells) 로 따로 만든다.
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = ROOT / "data" / "base"
sys.path.insert(0, str(ROOT / "src"))
import params as PM  # noqa: E402

MODES = ("uniform", "homes", "homes_or_shops")
# 셀 중심에서 이 거리 안이면 그 셀의 건물로 본다 — 100m 칸의 반대각선(70.7m). synth_inventory 의 71 과 같은 값
MATCH_M = round(PM.CELL_M.value / 2 ** 0.5)


def blocks(cells):
    """셀이 속한 1km 격자 코드 (cell_id = '<1km 코드>_<ij>')."""
    return cells["cell_id"].astype(str).str.split("_").str[0].to_numpy()


def home_weight(cells, rule=None):
    """셀별 주거건물 규모의 합. rule 이 없으면 params.HOME_W.
    'size'  = 건물마다 세대수(building:flats) > 층수(building:levels) > 1 (synth_inventory 와 같은 규칙)
    'count' = 건물마다 1 (태그 편차의 영향을 보는 대조용)"""
    import geopandas as gpd
    rule = PM.HOME_W.value if rule is None else rule
    el = json.loads((BASE / "osm_homes.json").read_text(encoding="utf-8"))["elements"]
    el = [e for e in el if "center" in e]
    if rule == "count":
        w = np.ones(len(el))
    elif rule == "size":
        tags = pd.DataFrame([e.get("tags", {}) for e in el])
        flats = pd.to_numeric(tags.get("building:flats"), errors="coerce").to_numpy(dtype=float)
        lv = pd.to_numeric(tags.get("building:levels"), errors="coerce").to_numpy(dtype=float)
        w = np.where(~np.isnan(flats), flats, np.where(~np.isnan(lv), lv, 1.0))
    else:
        raise ValueError(f"HOME_W 는 'size' 또는 'count': {rule!r}")
    g = gpd.GeoSeries(gpd.points_from_xy([e["center"]["lon"] for e in el],
                                         [e["center"]["lat"] for e in el]), crs=4326).to_crs(5179)
    d, i = cKDTree(cells[["x", "y"]].to_numpy()).query(np.c_[g.x.to_numpy(), g.y.to_numpy()])
    ok = d <= MATCH_M
    return np.bincount(i[ok], weights=w[ok], minlength=len(cells))


def shop_count(cells):
    """셀 중심 반경 ANCHOR_R_M 안의 상가 수 — 심야 앵커 · 유흥은 뺀다(prep.ANCHOR · prep.NIGHTLIFE)."""
    import geopandas as gpd
    import prep
    p = pd.read_csv(BASE / "poi.csv", encoding="utf-8-sig")
    p = p[~p["행정동명"].isin(PM.EXCLUDE_DONG.value)]
    sub = p["상권업종소분류명"].astype(str)
    p = p[~sub.isin(prep.ANCHOR | prep.NIGHTLIFE)]
    g = gpd.GeoSeries(gpd.points_from_xy(p["경도"], p["위도"]), crs=4326).to_crs(5179)
    t = cKDTree(np.c_[g.x.to_numpy(), g.y.to_numpy()])
    hits = t.query_ball_point(cells[["x", "y"]].to_numpy(), PM.ANCHOR_R_M.value)
    return np.array([len(h) for h in hits], dtype=float)


def homes(cells, w=None):
    """1km 안 합계(현행 균등 값의 합)를 같은 1km 안의 주거건물 규모에 비례해 다시 나눈다."""
    w = home_weight(cells) if w is None else w
    b = blocks(cells)
    cur = cells["pop_night"].to_numpy(dtype=float)
    tot_w = pd.Series(w).groupby(b).transform("sum").to_numpy()
    tot_p = pd.Series(cur).groupby(b).transform("sum").to_numpy()
    return np.where(tot_w > 0, tot_p * w / np.where(tot_w > 0, tot_w, 1.0), cur)


def pct_min(x):
    """0 이 많은 항의 분위 — 동점은 최솟값 순위(시연판 FLOW_FORM 과 같은 규칙). 0 인 셀이 평균 순위로 올라가지 않게."""
    return pd.Series(x).rank(method="min", pct=True).to_numpy()


def shuffled(w, b, seed):
    """대조군 — 같은 1km 안에서 셀별 주거건물 규모를 무작위로 섞는다(1km 안 값의 분포는 그대로, 자리만 임의).
    homes 의 개선이 '주거건물이 실제로 있는 자리' 덕인지, '1km 안에 높낮이가 생긴 것' 자체 덕인지 가른다(#13)."""
    rng = np.random.default_rng(seed)
    out = np.asarray(w, dtype=float).copy()
    for idx in pd.Series(np.arange(len(out))).groupby(b).indices.values():
        out[idx] = out[rng.permutation(idx)]
    return out


def act_lex(f, a):
    """사전식 활성도 순위(min → max) — 시연판 ACT_TIEBREAK(night_core.activity)와 같은 규칙.
    min(f, a) 이 같으면 다른 항이 큰 쪽을 밝게 본다. 가중치 없는 순서 규칙이다.
    homes 처럼 0 이 많은 유동 값은 min 이 한 값에 몰려 저활성 임계가 그 동점 값에 걸린다 — 그때 비교용으로 쓴다(#13)."""
    lo, hi = np.minimum(f, a), np.maximum(f, a)
    order = np.lexsort((hi, lo))
    act = np.empty(order.size)
    act[order] = (np.arange(order.size) + 1) / order.size
    return act


def flow(cells, mode=None, w=None, shops=None):
    """점수 첫 항에 넣을 셀별 값. mode 가 없으면 params.POP_ALLOC."""
    mode = PM.POP_ALLOC.value if mode is None else mode
    if mode == "uniform":
        return cells["pop_night"].to_numpy(dtype=float)
    if mode == "homes":
        return homes(cells, w)
    if mode == "homes_or_shops":
        s = shop_count(cells) if shops is None else shops
        return np.maximum(pct_min(homes(cells, w)), pct_min(s))
    raise ValueError(f"POP_ALLOC 은 {MODES} 중 하나: {mode!r}")
