# -*- coding: utf-8 -*-
"""
시연 앱 공통 — 데이터 적재(캐시) · 시간대 상태 · 지도/배지 도우미.
계산은 night_core 에만 있다. 이 파일과 화면 파일은 숫자를 만들지 않는다.
표현 규칙: CLAUDE.md 0절 — '사람이 많은 길 · 불 켜진 길' 로만 쓴다.
"""
import json
import pathlib
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st
from pyproj import Transformer
from scipy.sparse import load_npz

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import params as PM
import night_core as NC

PROC = ROOT / "data" / "processed"
PROTO = ROOT / "data" / "proto"
TO5179 = Transformer.from_crs(4326, 5179, always_xy=True)

SYN = ":orange-badge[임의값]"
REAL = ":green-badge[실데이터]"
DOWS = list(NC.DOW_KR)
# 사람이 말하는 시간. '토요일 새벽 1시'는 금요일 밤 시간대로 계산한다(SLOT_NIGHT_OF)
HOUR_CHIPS = {"밤 10시": 22, "밤 11시": 23, "밤 12시": 0, "새벽 1시": 1}
HOUR_LABEL = {v: k for k, v in HOUR_CHIPS.items()}


# ══ 적재 ═══════════════════════════════════════════════════════════
@st.cache_resource(show_spinner="밤 활성도 지도를 준비하는 중…")
def world():
    if not (PROTO / "terms.npz").exists():
        st.error("data/proto 가 없습니다. 먼저 `python src/synth_inventory.py` → `python src/ingest_inventory.py`")
        st.stop()
    cells = pd.read_csv(PROC / "cells.csv", encoding="utf-8-sig")
    nodes = pd.read_csv(PROC / "nodes.csv", encoding="utf-8-sig")
    edges = pd.read_csv(PROC / "edges.csv")
    t = np.load(PROTO / "terms.npz")
    A = NC.activity(t["R"], t["V"], t["A_d"])
    G = NC.NightGraph(nodes, edges)
    eact = NC.edge_activity(A["act"], G.cell, G.u, G.v)
    thr = NC.dark_threshold(eact, G.length)
    ab = pd.read_csv(PROTO / "anchor_blocks.csv", encoding="utf-8-sig")
    share = ab[[f"s{i}" for i in range(len(NC.SLOTS))]].to_numpy()
    lights = pd.read_csv(PROTO / "lights.csv", encoding="utf-8-sig")
    cctv = pd.read_csv(PROTO / "cctv.csv", encoding="utf-8-sig")
    tr = np.load(PROTO / "trips.npz", allow_pickle=True)
    rep = json.loads((PROTO / "ingest_report.json").read_text(encoding="utf-8"))
    return SimpleNamespace(
        cells=cells, nodes=nodes, G=G, act=A["act"], eact=eact, thr=thr, ab=ab, share=share,
        active=share >= PM.ACTIVE_NIGHT_SHARE.value, abxy=ab[["x", "y"]].to_numpy(),
        lights=lights, cctv=cctv,
        lit=NC.near_count(G, lights[["x", "y"]].to_numpy(), PM.LIGHT_R_M.value),
        cam=NC.near_count(G, cctv[["x", "y"]].to_numpy(), PM.CCTV_R_M.value),
        curve=pd.read_csv(PROTO / "dong_curve.csv", encoding="utf-8-sig"),
        W=tr["W"], inc=load_npz(PROTO / "trips_inc.npz").tocsc(), o_node=tr["o_node"], d_node=tr["d_node"],
        rep=rep)


@st.cache_resource
def bus():
    """TAGO 노선·정류장 (실데이터, 2026-09-16 수집 · data/bus). 안산 24개 동 안 · 미정차 제외."""
    import geopandas as gpd
    r = pd.read_csv(ROOT / "data" / "bus" / "tago_routes.csv", encoding="utf-8-sig", dtype=str)
    s = pd.read_csv(ROOT / "data" / "bus" / "tago_route_stops.csv", encoding="utf-8-sig", dtype=str)
    s = s[~s["nodenm"].str.contains("미정차", na=False)].copy()
    s["lon"], s["lat"] = s["gpslong"].astype(float), s["gpslati"].astype(float)
    s["nodeord"] = s["nodeord"].astype(int)
    d = gpd.read_file(PROC / "dong.geojson").to_crs(4326)
    g = gpd.sjoin(gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.lon, s.lat), crs=4326),
                  d[["ADM_NM", "geometry"]], predicate="within")
    s = pd.DataFrame(g.drop(columns=["geometry", "index_right"]))
    s["x"], s["y"] = TO5179.transform(s["lon"].to_numpy(), s["lat"].to_numpy())
    r = r[r["routeid"].isin(s["routeid"])].copy()
    r["label"] = r["routeno"] + "번 · 막차 " + r["막차"].fillna("?") + " (" + r["startnodenm"] + "→" + r["endnodenm"] + ")"
    r = r.sort_values("routeno", key=lambda x: pd.to_numeric(x.str.extract(r"(\d+)")[0], errors="coerce"))
    return r.reset_index(drop=True), s.reset_index(drop=True)


@st.cache_resource
def _geocoder():
    """오프라인 주소 검색(상가 8,979지점 색인 · 정류장 이름 · 동 중심) — src/geocode.py · data/geocode."""
    import geocode
    return geocode


@st.cache_data(show_spinner=False)
def locate(text):
    """주소·정류장·동 이름 → dict(node, x, y, lon, lat, 설명, 정확도, off_m). 실패 시 None."""
    if not str(text).strip():
        return None
    try:
        h = _geocoder().geocode(text)
    except Exception:
        h = None
    if not h:
        return None
    W = world()
    x, y = TO5179.transform(h["경도"], h["위도"])
    node = W.G.snap(x, y)
    off = float(np.hypot(*(W.G.xy[node] - [x, y])))
    return {"node": node, "x": x, "y": y, "lon": h["경도"], "lat": h["위도"],
            "설명": h.get("설명", ""), "정확도": h.get("정확도", ""), "off_m": off}


# ══ 시간대 ═════════════════════════════════════════════════════════
def slot_picker():
    """사이드바 — 요일·시간. 모든 화면이 같은 값을 쓴다."""
    st.sidebar.markdown("**언제 걸으세요?**")
    st.sidebar.segmented_control("요일", DOWS, default="금", key="dow", label_visibility="collapsed")
    st.sidebar.segmented_control("시간", list(HOUR_CHIPS), default="밤 11시", key="hour",
                                 label_visibility="collapsed")


def current_slot():
    d = DOWS.index(st.session_state.get("dow") or "금")
    h = HOUR_CHIPS[st.session_state.get("hour") or "밤 11시"]
    night = (d - 1) % 7 if h == 1 else d                      # 토요일 새벽 1시 = 금요일 밤
    return NC.slot_index(night, h)


def when(slot):
    """'금요일 밤 11시' · '토요일 새벽 1시' — 화면에 쓰는 시간 표기."""
    night, h = NC.SLOTS[slot]
    if h == 1:
        return f"{DOWS[(night + 1) % 7]}요일 새벽 1시"
    return f"{DOWS[night]}요일 밤 {12 if h == 0 else h - 12}시"


def place(h):
    """지오코더 설명 → 짧은 장소 이름 ('중앙역2번출구 정류장' · '석호로 110' · '와동 일대')."""
    import re
    s = str(h.get("설명", ""))
    for pat, fmt in ((r"^(.+?) 정류장 위치 기준", "{} 정류장"), (r"^(.+?)번지 기준", "{}"),
                     (r"^(.+?) 가운데 기준", "{} 일대")):
        m = re.match(pat, s)
        if m:
            return fmt.format(m.group(1))
    return s.split(" (")[0]


def km(m):
    return f"{m / 1000:.1f}km" if m >= 1000 else f"{round(m, -1):,.0f}m"


def dark_txt(m):
    return "없음" if m < 5 else km(m)


def mins(m):
    return int(round(minutes(m)))


def detour():
    return st.session_state.get("detour", PM.DETOUR.value)


# ══ 지도 ═══════════════════════════════════════════════════════════
DARK_RGB = [235, 64, 52]        # 사람 드문 구간
LIT_RGB = [255, 214, 102]       # 사람 많고 불 켜진 쪽
BASE_RGB = [150, 150, 160]


def act_rgb(a, thr):
    """활성도 → 색. 임계 미만은 빨강, 이상은 주황→밝은 노랑 (밤 지도에서 '불 켜진' 은유)."""
    a = np.asarray(a, float)
    t = np.clip((a - thr) / max(1 - thr, 1e-6), 0, 1)
    lo = np.array([255, 140, 40])
    hi = np.array([255, 240, 170])
    col = (lo[None, :] * (1 - t[:, None]) + hi[None, :] * t[:, None]).astype(int)
    col[a < thr] = DARK_RGB
    return col


def path_layer(G, edges_idx, colors, width=6, name="route"):
    data = [{"path": [G.lonlat[G.u[e]].tolist(), G.lonlat[G.v[e]].tolist()], "color": c.tolist() + [235]}
            for e, c in zip(edges_idx, colors)]
    return pdk.Layer("PathLayer", data, id=name, get_path="path", get_color="color",
                     width_min_pixels=width, width_units="pixels", cap_rounded=True, pickable=False)


def line_layer(G, path, rgb, width=4, name="base", alpha=200):
    return pdk.Layer("PathLayer", [{"path": G.lonlat[np.asarray(path)].tolist()}], id=name,
                     get_path="path", get_color=list(rgb) + [alpha], width_min_pixels=width, cap_rounded=True)


def dots(df, rgb, radius=20, name="dots", tooltip=True, lon="lon", lat="lat"):
    return pdk.Layer("ScatterplotLayer", df, id=name, get_position=[lon, lat], get_fill_color=list(rgb) + [220],
                     get_radius=radius, radius_min_pixels=3, pickable=tooltip, stroked=True,
                     get_line_color=[20, 20, 30, 255], line_width_min_pixels=1)


def deck(layers, lon, lat, zoom=14, tooltip=None, height=520):
    st.pydeck_chart(pdk.Deck(layers=layers, map_provider="carto", map_style="dark",
                             initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
                             tooltip=tooltip or {"text": "{tip}"}), height=height)


def notice(formal=False):
    """시연 데이터 표시 — 한 줄. 자세한 내용은 '데이터 출처' 화면."""
    st.caption(":orange-badge[시연 데이터] " + ("사람 수와 가게 영업 정보는 임의로 만든 값입니다."
                                             if formal else "사람 수와 가게 영업 정보는 임의로 만든 값이에요."))


def fmt_m(v):
    return f"{v:,.0f}m"


def minutes(m):
    return m / PM.WALK_MPS.value / 60
