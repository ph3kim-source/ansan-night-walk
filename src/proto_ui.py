# -*- coding: utf-8 -*-
"""
시연 앱 공통 — 데이터 적재(캐시) · 시간대 상태 · 지도/배지 도우미.
계산은 night_core 에만 있다. 이 파일과 화면 파일은 숫자를 만들지 않는다.
표현 규칙: CLAUDE.md 0절 — '사람이 많은 길 · 불 켜진 길' 로만 쓴다.
"""
import json
import os
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
PROTO = ROOT / "data" / "proto"                 # 임의값 + 공개 실데이터 — 공유본 · 드라이브 앱에 실린다
REAL_PROTO = ROOT / "data" / "real" / "proto"   # 민간 실데이터(#19) — 이 PC에서만. NIGHT_DATA=real 로 띄운다
PRIV_TXT = ("사람이 다니는 정도는 통신 · 신용 실데이터({months})로 계산해 3단계로만 보여 줍니다. "
            "사는 사람이 적은 곳은 '자료 부족'으로 가립니다. 가게는 상가정보의 심야 업종 위치이고, 영업 여부는 확인하지 못했습니다.")
TO5179 = Transformer.from_crs(4326, 5179, always_xy=True)

SYN = ":orange-badge[임의값]"
REAL = ":green-badge[실데이터]"
DOWS = list(NC.DOW_KR)
# 사람이 말하는 시간. '토요일 새벽 1시'는 금요일 밤 시간대로 계산한다(SLOT_NIGHT_OF)
HOUR_CHIPS = {"밤 10시": 22, "밤 11시": 23, "밤 12시": 0, "새벽 1시": 1}
HOUR_LABEL = {v: k for k, v in HOUR_CHIPS.items()}


# ══ 적재 ═══════════════════════════════════════════════════════════
def proto_dir():
    """화면이 읽을 폴더. 환경변수 NIGHT_DATA=real 이면 민간 실데이터 판(내부 검토용 — `시연_실데이터.bat`, #19)."""
    return REAL_PROTO if os.environ.get("NIGHT_DATA", "").strip().lower() == "real" else PROTO


def world():
    return _world(str(proto_dir()))


@st.cache_resource(show_spinner="밤 활성도 지도를 준비하는 중…")
def _world(proto):
    P = pathlib.Path(proto)
    if not (P / "terms.npz").exists():
        st.error("data/real/proto 가 없습니다. 먼저 `py -3.12 src/stage_real.py` → "
                 "`py -3.12 src/ingest_inventory.py data/real/raw`" if P == REAL_PROTO else
                 "data/proto 가 없습니다. 먼저 `python src/synth_inventory.py` → `python src/ingest_inventory.py`")
        st.stop()
    cells = pd.read_csv(PROC / "cells.csv", encoding="utf-8-sig")
    nodes = pd.read_csv(PROC / "nodes.csv", encoding="utf-8-sig")
    edges = pd.read_csv(PROC / "edges.csv")
    t = np.load(P / "terms.npz")
    A = NC.activity(t["R"], t["V"], t["A_d"], t["P"] if "P" in t.files else None)
    G = NC.NightGraph(nodes, edges)
    eact = NC.edge_activity(A["act"], G.cell, G.u, G.v)
    thr = NC.dark_threshold(eact, G.length)
    ab = pd.read_csv(P / "anchor_blocks.csv", encoding="utf-8-sig")
    share = ab[[f"s{i}" for i in range(len(NC.SLOTS))]].to_numpy(float)
    lights = pd.read_csv(P / "lights.csv", encoding="utf-8-sig")
    cctv = pd.read_csv(P / "cctv.csv", encoding="utf-8-sig")
    tr = np.load(P / "trips.npz", allow_pickle=True)
    rep = json.loads((P / "ingest_report.json").read_text(encoding="utf-8"))
    priv = not rep.get("_meta", {}).get("synthetic", True)      # 민간 실데이터로 적재됐는가
    if priv and P != REAL_PROTO:
        st.error("data/proto 에 민간 실데이터가 들어 있습니다 — 공유본 · 드라이브 앱으로 나가는 폴더입니다. "
                 "`py -3.12 src/ingest_inventory.py` 로 임의값을 다시 적재하십시오")
        st.stop()
    # 화면 마스킹(#19) — 실데이터 판만. 계산(경로 탐색)에는 eact 를 그대로 쓰고, 보이는 것만 등급 · '자료 부족'
    if priv:
        cm = np.asarray(t["masked"], bool) if "masked" in t.files else np.zeros(len(cells), bool)
        nm = cm[G.cell]
        emask = nm[G.u] | nm[G.v]                                  # 양 끝 중 하나라도 가린 칸이면 가린다
        thr_hi = NC.dark_threshold(eact, G.length, PM.GRADE_HI_Q.value)
    else:
        emask, thr_hi = np.zeros(G.m, bool), None
    hours_known = bool(np.isfinite(share).any())                 # 카드 블록 좌표가 없으면 영업 여부를 모른다
    active = share >= PM.ACTIVE_NIGHT_SHARE.value if hours_known else np.ones(share.shape, bool)

    def opt(name):
        p = P / name
        return pd.read_csv(p, encoding="utf-8-sig") if p.exists() else pd.DataFrame()

    ep = opt("edge_public.csv")
    real = len(ep) == G.m                                       # 공개 실데이터(수정사항 #15)가 적재됐는가
    if real:
        lit = ep["lights_n"].to_numpy()                         # 간선(선분) LIGHT_R_M 안 보안등 수
        major = ep["major"].to_numpy(bool)                      # 큰길 = 가로등 구간(MAJOR_ROAD)
        flow_st = ep[["f22", "f23", "f24"]].to_numpy().T        # 밤 역 귀갓길 흐름 (3, 간선) 사람/밤
    else:                                                       # 예전 임의값 방식
        lit = NC.near_count(G, lights[["x", "y"]].to_numpy(), PM.LIGHT_R_M.value)
        major = np.zeros(G.m, bool)
        flow_st = np.zeros((3, G.m))
    police = opt("police.csv")
    police = police[police["night_open"].astype(bool)].reset_index(drop=True) if len(police) else police
    pub = P / "public_report.json"
    hrs = np.array([h for _, h in NC.SLOTS])                    # 0시 ÷ 23시(안산 합계) — 자정 주의 문구의 수치는 코드에 적지 않고 자료에서 잰다(#22)
    mid = float(t["P"][hrs == 0].sum() / max(float(t["P"][hrs == 23].sum()), 1e-9)) if "P" in t.files else None
    return SimpleNamespace(
        cells=cells, nodes=nodes, G=G, act=A["act"], eact=eact, thr=thr, ab=ab, share=share,
        active=active, abxy=ab[["x", "y"]].to_numpy(),
        lights=lights, cctv=cctv, lit=lit, major=major, flow_st=flow_st, real=real, links=G.links(),
        cam=NC.near_count(G, cctv[["x", "y"]].to_numpy(), PM.CCTV_R_M.value),
        bells=opt("bells.csv"), police=police, stations=opt("stations.csv"),
        pub=json.loads(pub.read_text(encoding="utf-8")) if pub.exists() else {},
        curve=pd.read_csv(P / "dong_curve.csv", encoding="utf-8-sig"),
        W=tr["W"], inc=load_npz(P / "trips_inc.npz").tocsc(), o_node=tr["o_node"], d_node=tr["d_node"],
        rep=rep, priv=priv, emask=emask, thr_hi=thr_hi, hours_known=hours_known, has_P="P" in t.files, mid_ratio=mid,
        months=rep.get("_meta", {}).get("months", []))


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


GRADE_RGB = np.array([[105, 105, 115], DARK_RGB, [255, 165, 60], [255, 240, 170]])  # 0 자료 부족 · 1 드묾 · 2 보통 · 3 많음
GRADE_TXT = ["자료 부족", "사람 드묾", "보통", "사람 많음"]


def route_rgb(edges, ea):
    """경로 색 — 임의값 판은 연속색(act_rgb), 민간 실데이터 판은 3단계 등급 + 가린 칸 회색(#19)."""
    W = world()
    e = np.asarray(edges, dtype=np.int64)
    if not W.priv:
        return act_rgb(ea[e], W.thr)
    return GRADE_RGB[NC.grades(ea[e], W.thr, W.thr_hi, W.emask[e])]


def dark_mask(slot):
    """목록 · 집계용 '사람 드문 길' 간선. 민간 실데이터 판에서는 가린 칸(자료 부족)을 뺀다."""
    W = world()
    return (W.eact[slot] < W.thr) & ~W.emask


def months_txt():
    m = world().months
    return f"{m[0][:4]}.{m[0][4:]}~{m[-1][:4]}.{m[-1][4:]}" if m else "기간 미상"


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
    W = world()
    if W.priv:
        st.caption(":red-badge[내부 검토용 · 외부 공유 금지] " + PRIV_TXT.format(months=months_txt()))
        return
    real = W.real
    if formal:
        txt = "사람 수와 가게 영업 정보는 임의로 만든 값입니다." + (" 보안등 · 역 하차 인원 · 지구대 위치는 실데이터입니다." if real else "")
    else:
        txt = "사람 수와 가게 영업 정보는 임의로 만든 값이에요." + (" 보안등과 지구대 위치는 실제 자료예요." if real else "")
    st.caption(":orange-badge[시연 데이터] " + txt)


def lamps_near(path, extra=10.0):
    """경로 노드 근처(LIGHT_R_M + extra) 보안등 — 지도 표시용."""
    W = world()
    if not len(W.lights) or len(path) < 2:
        return W.lights.iloc[0:0]
    from scipy.spatial import cKDTree
    hit = cKDTree(W.lights[["x", "y"]].to_numpy()).query_ball_point(W.G.xy[np.asarray(path)], PM.LIGHT_R_M.value + extra)
    idx = sorted({i for h in hit for i in h})
    return W.lights.iloc[idx]


def fmt_m(v):
    return f"{v:,.0f}m"


def minutes(m):
    return m / PM.WALK_MPS.value / 60
