# -*- coding: utf-8 -*-
"""
전처리: 기초 데이터(data/base)를 3안 스키마로 변환
실행:  python src/prep.py
출력:  data/processed/{dong.geojson, cells.csv, anchors.csv, nodes.csv, edges.csv}

입력은 전부 data/base 에 있다 (3안 독립 사본 — 수정사항 #11).
  dong_sgis.geojson  안산 행정동 25개 경계            (SGIS 2025 2Q)
  grid_1km.geojson   안산 1km 격자 176개 + 인구        (SGIS 2024)
  poi.csv            안산 상가 34,489개 + 좌표·업종     (소상공인시장진흥공단 2026.06)

★ 여기서 만드는 cells.csv 의 스키마는 실데이터(DS-032·054·048)가 들어와도 바뀌지 않는다.
  로더 함수만 갈아끼우면 되도록 컬럼명을 실데이터 기준으로 미리 맞춰뒀다.
"""
import pathlib, sys
import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = ROOT / "data" / "base"          # 기초 데이터 (SGIS 경계·1km 인구 · 소상공인 상가)
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "src"))
import params as PM
import osm

# ── 심야 앵커 업종 정의 ──────────────────────────────────────
# '밤에 불이 켜져 있고 위급할 때 뛰어들 수 있는 곳'만 센다.
# 유흥 계열은 심야 결제가 가장 많지만 안전의 대리지표가 아니므로 분리한다.
ANCHOR = {"편의점", "주유소", "PC방"}
NIGHTLIFE = {"요리 주점", "일반 유흥 주점", "생맥주 전문", "무도 유흥 주점", "노래방"}


def log(m):
    print(m, flush=True)


def step1_dong():
    log("\n[1] 행정동 경계")
    g = gpd.read_file(BASE / "dong_sgis.geojson")
    g = g[~g["ADM_NM"].isin(PM.EXCLUDE_DONG.value)].copy()
    g.to_file(OUT / "dong.geojson", driver="GeoJSON")
    log(f"    [v] dong.geojson  {len(g)}개 동 (제외: {', '.join(PM.EXCLUDE_DONG.value)})")
    return g


def step2_cells(dong):
    """인구>0 인 1km 격자 안을 100m 격자로 쪼갠다."""
    log("\n[2] 100m 격자")
    g1 = gpd.read_file(BASE / "grid_1km.geojson")
    g1.columns = ["GRID_CD", "ADM_CD", "ADM_NM", "인구", "제조업종사자", "geometry"]
    g1 = g1[(g1["인구"] > 0) & (~g1["ADM_NM"].isin(PM.EXCLUDE_DONG.value))].to_crs(5179)
    log(f"    1km 격자 {len(g1)}개 · 인구 {int(g1['인구'].sum()):,}명")

    step = PM.CELL_M.value
    rows = []
    for r in g1.itertuples():
        x0, y0, x1, y1 = r.geometry.bounds
        n = int(round((x1 - x0) / step))
        # 1km 격자 인구를 100m 칸 n*n 개에 균등 안분 (프로토타입 대체. 실데이터는 DS-032)
        per = r.인구 / (n * n)
        for i in range(n):
            for j in range(n):
                rows.append((f"{r.GRID_CD}_{i}{j}", x0 + (i + .5) * step,
                             y0 + (j + .5) * step, r.ADM_NM, per))
    c = pd.DataFrame(rows, columns=["cell_id", "x", "y", "dong", "pop_night"])

    # 동 경계 밖(바다·인접시)은 버린다
    gc = gpd.GeoDataFrame(c, geometry=gpd.points_from_xy(c.x, c.y), crs=5179)
    gc = gpd.sjoin(gc, dong.to_crs(5179)[["ADM_NM", "geometry"]], predicate="within")
    c = pd.DataFrame(gc.drop(columns=["geometry", "index_right", "dong"]))
    c = c.rename(columns={"ADM_NM": "dong"}).reset_index(drop=True)
    log(f"    [v] 100m 셀 {len(c):,}개 (동 경계 내부만)")
    return c


def step3_anchors(dong):
    """상가 POI를 심야 앵커 / 유흥으로 분류."""
    log("\n[3] 심야 앵커 분류")
    p = pd.read_csv(BASE / "poi.csv", encoding="utf-8-sig")
    p = p[~p["행정동명"].isin(PM.EXCLUDE_DONG.value)].copy()
    sub = p["상권업종소분류명"].astype(str)
    p["유형"] = np.where(sub.isin(ANCHOR), "앵커",
                np.where(sub.isin(NIGHTLIFE), "유흥", "기타"))
    a = p[p["유형"] != "기타"][["상호명", "상권업종소분류명", "행정동명", "경도", "위도", "유형"]]
    a.columns = ["name", "biz", "dong", "lon", "lat", "kind"]
    a.to_csv(OUT / "anchors.csv", index=False, encoding="utf-8-sig")
    t = a.groupby(["kind", "biz"]).size().sort_values(ascending=False)
    log(f"    [v] anchors.csv  앵커 {(a.kind=='앵커').sum():,} / 유흥 {(a.kind=='유흥').sum():,}")
    for (k, b), v in t.items():
        log(f"        {k}  {b:<12s} {v:>5,}")
    return a


def step4_join(c, a):
    """셀 반경 100m 내 앵커·유흥 개수."""
    log("\n[4] 셀 × 앵커 공간조인")
    ga = gpd.GeoDataFrame(a, geometry=gpd.points_from_xy(a.lon, a.lat), crs=4326).to_crs(5179)
    a = a.assign(x=ga.geometry.x.values, y=ga.geometry.y.values)
    tree = cKDTree(c[["x", "y"]].values)
    r = PM.ANCHOR_R_M.value
    for kind, cn, dn in [("앵커", "anchor_n", "anchor_d"), ("유흥", "nightlife_n", "nightlife_d")]:
        sub = a[a.kind == kind]
        cnt = np.zeros(len(c), dtype=int)
        for idx in tree.query_ball_point(sub[["x", "y"]].values, r):
            cnt[idx] += 1
        c[cn] = cnt
        # 최근접 거리 — 개수는 83%가 0이라 계단이 되므로, 점수에는 연속인 거리를 쓴다
        c[dn] = cKDTree(sub[["x", "y"]].values).query(c[["x", "y"]].values)[0]
        log(f"    {kind:4s} 반경 {r}m 내 1개 이상인 셀 {(cnt>0).sum():,}개 "
            f"({(cnt>0).mean():.1%}) · 최근접거리 중앙값 {np.median(c[dn]):.0f}m")
    c.to_csv(OUT / "cells.csv", index=False, encoding="utf-8-sig")
    log(f"    [v] cells.csv {len(c):,}행")
    return c


def step5_graph(c, dong):
    """보행 그래프 — 실제 OSM 보행망. 노드는 길 위의 점이고 점수는 셀에서 온다.

    ★ 종전에는 100m 격자를 8-근접으로 이어 길을 흉내냈다(GRAPH_STEP_M, C등급).
      연결요소가 1,406개로 쪼개져 80.6%만 서로 오갔고 건물·하천을 통과했다.
      OSM 보행망으로 교체해 105개(94.3%)가 됐다. (#04)
    """
    log("")
    log("[5] 보행 그래프 (OSM 보행망)")
    src = ROOT / "data" / "raw" / "ansan_walk.geojson"
    if not src.exists():
        raise SystemExit(
            f"[X] {src} 가 없습니다. overpass-turbo.eu 에서 "
            "data/raw/overpass_쿼리.txt 를 실행해 GeoJSON 으로 내려받으십시오. "
            "(사양: '데이터 수집 요청서.md' 1번)")

    w = osm.load_ways(src, dong, log=log)
    n, e = osm.build_graph(w, log=log)
    n = osm.attach_cells(n, c, log=log)
    n, e, ncomp = osm.largest_component(n, e, log=log)

    g = gpd.GeoDataFrame(n, geometry=gpd.points_from_xy(n.x, n.y), crs=5179).to_crs(4326)
    n["lon"], n["lat"] = g.geometry.x.values, g.geometry.y.values

    n.to_csv(OUT / "nodes.csv", index=False, encoding="utf-8-sig")
    e.to_csv(OUT / "edges.csv", index=False)
    log(f"    [v] nodes.csv {len(n):,}행 · edges.csv {len(e):,}행 "
        f"(버린 연결요소 {ncomp - 1:,}개)")
    return n, e


if __name__ == "__main__":
    d = step1_dong()
    c = step2_cells(d)
    a = step3_anchors(d)
    c = step4_join(c, a)
    step5_graph(c, d)
    log("")
    log("완료.")
