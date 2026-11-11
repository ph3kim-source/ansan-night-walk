# -*- coding: utf-8 -*-
"""
OSM 보행 네트워크 로더 — 격자 8-근접 그래프(GRAPH_STEP_M, C등급)를 대체한다.

왜 필요했나
-----------
86종 인벤토리에 길 데이터가 하나도 없다. 통신·카드는 "어디에 사람이 있는가"만 알려줄 뿐
"거기서 저기로 어떻게 가는가"는 모른다. 그래서 프로토타입은 100m 격자를 8-근접으로 이어
길을 흉내냈고, 그 결과 연결요소가 1,406개로 쪼개져 81%만 서로 오갈 수 있었다.
우회 예산을 다 못 쓴 쌍이 81% — 그래프에 우회할 더 나은 길 자체가 없었다.

입력
----
data/raw/ansan_walk.geojson   OSM Overpass 추출 (highway=footway|path|…), WGS84

설계
----
· 점수는 여전히 100m 셀에서 매긴다. 노드는 길 위의 점일 뿐 점수 단위가 아니다.
  (노드로 분위를 매기면 교차로가 촘촘한 도심이 과대표집된다 — 분위의 의미가 달라진다)
· 각 노드는 최근접 100m 셀의 활성도를 물려받는다.
· 좌표 반올림(SNAP_M)으로 노드를 병합해야 끊긴 way 들이 교차로에서 실제로 이어진다.
"""
import pathlib
import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.spatial import cKDTree

import sys, pathlib as _pl
sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
import params as PM

SNAP_M = PM.SNAP_M.value            # 노드 병합 격자 (m)
MAX_CELL_M = PM.NODE_CELL_MAX_M.value   # 노드가 셀 점수를 물려받을 최대 거리

# 보행 불가로 명시된 것만 뺀다. 태그가 없으면 통행 가능으로 본다(OSM 관례)
DROP_FOOT = {"no", "private"}
DROP_ACCESS = {"private", "no"}


def load_ways(path, dong, log=print):
    """GeoJSON → 안산 24개 동으로 클립된 LineString GeoDataFrame (EPSG:5179)."""
    g = gpd.read_file(path)
    n0 = len(g)

    # 광장·보행데크는 Polygon 으로 들어온다. 외곽선을 길로 쓴다
    poly = g[g.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if len(poly):
        g.loc[poly.index, "geometry"] = poly.geometry.boundary

    g = g[g.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()
    g = g.explode(index_parts=False)

    for col, bad in (("foot", DROP_FOOT), ("access", DROP_ACCESS)):
        if col in g.columns:
            before = len(g)
            g = g[~g[col].isin(bad)]
            if before - len(g):
                log(f"    {col} 제외 {before - len(g):,}개")

    g = g.set_crs(4326, allow_override=True).to_crs(5179)
    area = dong.to_crs(5179).union_all()
    before = len(g)
    g = g[g.intersects(area)].copy()
    g["geometry"] = g.geometry.intersection(area)
    g = g.explode(index_parts=False)
    g = g[g.geometry.geom_type == "LineString"]
    g = g[g.geometry.length > 0]
    log(f"    way {n0:,} → 클립 후 {len(g):,} (동 경계 밖 {before - len(g):,} 제거)")
    return g


def build_graph(ways, log=print):
    """way 지오메트리 → (nodes, edges). 좌표 반올림으로 교차로를 병합한다."""
    seg_a, seg_b = [], []
    for geom in ways.geometry.values:
        c = np.asarray(geom.coords)
        if len(c) < 2:
            continue
        seg_a.append(c[:-1])
        seg_b.append(c[1:])
    A = np.vstack(seg_a)
    B = np.vstack(seg_b)

    key = np.vstack([A, B])
    q = np.round(key / SNAP_M).astype(np.int64)
    uniq, inv = np.unique(q, axis=0, return_inverse=True)
    n = len(A)
    u, v = inv[:n], inv[n:]

    xy = uniq * SNAP_M
    L = np.hypot(A[:, 0] - B[:, 0], A[:, 1] - B[:, 1])

    e = pd.DataFrame({"u": u, "v": v, "len_m": L})
    e = e[e["u"] != e["v"]]
    # 무향 중복 제거 — 같은 두 점을 잇는 way 가 여럿이면 짧은 쪽만 남긴다
    lo = np.minimum(e["u"], e["v"]); hi = np.maximum(e["u"], e["v"])
    e = (e.assign(_a=lo, _b=hi).sort_values("len_m")
           .drop_duplicates(["_a", "_b"]).drop(columns=["_a", "_b"])
           .reset_index(drop=True))

    nodes = pd.DataFrame({"x": xy[:, 0], "y": xy[:, 1]})
    log(f"    노드 {len(nodes):,} · 간선 {len(e):,} "
        f"(평균 차수 {2 * len(e) / len(nodes):.1f} · 평균 간선장 {e['len_m'].mean():.0f}m)")
    return nodes, e


def attach_cells(nodes, cells, log=print):
    """각 노드에 최근접 100m 셀을 붙인다. 점수는 셀에서 오고 노드는 위치만 제공한다."""
    t = cKDTree(cells[["x", "y"]].to_numpy())
    d, i = t.query(nodes[["x", "y"]].to_numpy(), k=1)
    nodes = nodes.copy()
    nodes["cell"] = i
    nodes["cell_d"] = d
    nodes["dong"] = cells["dong"].to_numpy()[i]
    far = int((d > MAX_CELL_M).sum())
    log(f"    셀 매칭 중앙값 {np.median(d):.0f}m · {MAX_CELL_M:.0f}m 초과 {far:,}개 "
        f"({far / len(nodes) * 100:.1f}%)")
    return nodes


def largest_component(nodes, edges, log=print):
    """최대 연결요소만 남긴다. 섬처럼 떨어진 조각은 경로 탐색에서 의미가 없다."""
    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(range(len(nodes)))
    g.add_edges_from(zip(edges["u"], edges["v"]))
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    big = comps[0]
    log(f"    연결요소 {len(comps):,}개 · 최대 {len(big):,}노드 "
        f"({len(big) / len(nodes) * 100:.1f}%)")
    keep = np.zeros(len(nodes), bool)
    keep[list(big)] = True
    remap = -np.ones(len(nodes), np.int64)
    remap[keep] = np.arange(keep.sum())
    n2 = nodes[keep].reset_index(drop=True)
    m = keep[edges["u"].to_numpy()] & keep[edges["v"].to_numpy()]
    e2 = edges[m].copy()
    e2["u"] = remap[e2["u"].to_numpy()]
    e2["v"] = remap[e2["v"].to_numpy()]
    return n2, e2.reset_index(drop=True), len(comps)
