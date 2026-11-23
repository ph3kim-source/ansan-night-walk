# -*- coding: utf-8 -*-
"""
시민용 웹 지도 앱 '안산 밤길' 만들기 (수정사항 #24)
실행:  py -3.12 src/build_app.py
출력:  html/app/  (index.html · app.css · app.js · data.js)  +  html/밤길앱_열기.bat (이 PC 127.0.0.1:8787)

- 화면 코드는 src/app/ 에 있다. html/app 은 만들 때마다 새로 쓴다 — 직접 고치지 않는다.
- 자료는 data/proto(임의값 — 공유본과 같은 판)와 공개 자료만 싣는다. 민간 실데이터(data/real)는 읽지 않는다.
  이 앱은 공개 웹(GitHub)에 올라갈 수 있는 판이다.
- 경로 계산은 브라우저가 한다 — night_core.NightGraph.frontier · choose 를 그대로 옮겼다(app.js).
  간선 활성도는 등급만(드묾 · 보통 · 많음, 2비트) 싣고 등급 대표값 3개로 길을 고른다(#38 — 측정 #37: 길이 나빠지지 않음). 임계 · 위 경계도 같이 싣는다.
- 러닝 코스는 src/build_runs.py 가 만든 data/processed/run_courses.json(OSM 보행망 · 공개 자료)을 싣는다(노드 열 → 간선 번호).
- #26: 간선 길 종류에 '차도 옆 보도'(OSM)를 더하고, 산길 · 농로 표시 · 보행 사고가 잦았던 곳(도로교통공단 다발지역, PED_ACC) ·
  해 뜨고 지는 시각(낮 · 밤 기준, RUN_DAYNIGHT)을 싣는다.
- 담당자 화면(보안등 대조 · 개선 우선 구간)은 넣지 않는다 — Streamlit(src/proto_app.py)에 따로 있다.
- #32 실데이터 판:  py -3.12 src/build_app.py --real  →  real_app/app/ + real_app/밤길앱_실데이터.bat(127.0.0.1:8788)
  · 밤길앱_실데이터_휴대폰으로_보기.bat(같은 와이파이). data/real/proto(통신 50m 유동 DS-032 · 100m 거주 DS-082 · 도보 DS-008)를 읽는다.
  html/ 밖에만 쓴다(공유본 KEEP 에 없음). 화면은 등급만.
- #34 실데이터 판의 가린 칸(MASK_MIN_POP): 그 칸 유동(DS-032)은 쓰지 않고 가리지 않은 이웃 칸 유동을 가우스로 빌린다(MASK_BORROW_SIGMA_M).
  화면 등급 · 경로 계산이 같은 빌린 값을 쓰므로 가린 칸의 원래 유동은 data.js 에도 없다. '자료 부족' 간선은 없다.
"""
import base64
import datetime
import json
import os
import pathlib
import shutil
import stat
import sys

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix, diags
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import params as PM  # noqa: E402
import night_core as NC  # noqa: E402

PROC = ROOT / "data" / "processed"
PROTO = ROOT / "data" / "proto"
SRC_APP = ROOT / "src" / "app"
OUT = ROOT / "html" / "app"
PORT = 8787                     # 밤길지도(#21)와 같은 주소 — 카카오 · 브이월드에 등록할 주소가 하나로 끝난다
CAR_FREE = set(PM.RUN_CAR_FREE_HW.value)   # 러닝 코스 생성기(build_runs.py)와 같은 '차 없는 길' 정의
TRAIL = set(PM.RUN_TRAIL_NOTE.value["classes"])   # 산길 · 오솔길 · 농로 · 임도 — 밤 기준(RUN_DAYNIGHT)에 쓴다
STATIC = ("index.html", "app.css", "app.js", "manifest.webmanifest")   # + sw.js(판 번호를 넣어 쓴다) · icons/(그려서 만든다) — #31


def _writable(func, path, exc):
    """이 PC는 새 폴더에 Windows '읽기 전용' 표시가 붙는다(#23 · #24) — 표시를 풀고 다시 지운다."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def make_icons(d):
    """앱 아이콘(#31) — 초승달 + 굽은 길 + 불빛 점(시안 앱 아이콘과 같은 도안, 96 단위). 4배로 그려 줄여 매끄럽게.
    일반(둥근 모서리 · 투명 바깥) · maskable(가장자리까지 배경, 도안은 안쪽 80%) · 애플 터치(네모 · iOS 가 모서리를 깎는다)."""
    from PIL import Image, ImageDraw
    d.mkdir(parents=True, exist_ok=True)

    def bez(p0, p1, p2, p3, n=48):
        t = np.linspace(0, 1, n)[:, None]
        return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3

    def draw(size, rounded, inset):
        S = size * 4
        g = np.linspace(0, 1, S)
        t = ((g[None, :] + g[:, None]) / 2)[..., None]                       # 왼쪽 위 → 오른쪽 아래
        bg = (np.array([44, 85, 168]) * (1 - t) + np.array([11, 24, 56]) * t).astype(np.uint8)
        im = Image.fromarray(bg, "RGB").convert("RGBA")
        dr = ImageDraw.Draw(im)
        k = S / 96 * inset
        o = (S - 96 * k) / 2
        P = lambda x, y: (o + x * k, o + y * k)                              # noqa: E731
        moon = Image.new("L", (S, S), 0)
        md = ImageDraw.Draw(moon)
        for (x, y, r), f in (((65, 29, 14), 255), ((74, 22, 12), 0)):       # 노란 원에서 다른 원을 빼 초승달
            cx, cy = P(x, y)
            md.ellipse([cx - r * k, cy - r * k, cx + r * k, cy + r * k], fill=f)
        im.paste((255, 214, 102, 255), (0, 0), moon)
        A = np.array
        pts = np.vstack([bez(A([14, 84]), A([30, 72]), A([24, 62]), A([40, 57])),
                         bez(A([40, 57]), A([56, 52]), A([64, 52]), A([76, 40]))])
        xy = np.array([P(x, y) for x, y in pts])
        seg = np.hypot(*np.diff(xy, axis=0).T)                               # 굵은 선은 둥근 붓으로 촘촘히 찍는다
        s_ = np.r_[0, np.cumsum(seg)]                                        # (선분 이음매에 가는 틈이 생기지 않게)
        ss = np.arange(0, s_[-1], max(1.0, 0.75 * k))
        r = 7.5 * k / 2
        for x, y in zip(np.interp(ss, s_, xy[:, 0]), np.interp(ss, s_, xy[:, 1])):
            dr.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 255))
        for (x, y), col in (((23, 64), (255, 214, 102)), ((52, 44), (255, 214, 102)), ((58, 70), (226, 190, 92))):
            cx, cy = P(x, y)
            dr.ellipse([cx - 3.6 * k, cy - 3.6 * k, cx + 3.6 * k, cy + 3.6 * k], fill=col + (255,))
        if rounded:
            mask = Image.new("L", (S, S), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 22 / 96), fill=255)
            im.putalpha(mask)
        return im.resize((size, size), Image.LANCZOS)

    draw(192, True, 1.0).save(d / "icon-192.png")
    draw(512, True, 1.0).save(d / "icon-512.png")
    draw(512, False, 0.8).save(d / "icon-maskable-512.png")
    draw(180, False, 0.9).convert("RGB").save(d / "apple-touch-icon.png")


def grade_codes(eact, thr, thr_hi, length):
    """앱 파일의 활성도 — 등급만(#38, 측정 #37). 0 사람 드묾(< thr) · 1 보통 · 2 사람 많음(≥ thr_hi) — NC.grades 와 같은 경계.
    길 찾기 비용에 쓸 등급 대표값 = 그 등급에 든 (시간대 × 간선) 활성도의 길이 가중 평균(28 시간대를 합쳐서).
    대표값이 경계 안에 있어 '사람 드묾' 판정(act < thr)은 줄이기 전과 하나도 다르지 않다. 반환: (codes uint8 (시간대, 간선), 대표값 3개)."""
    eact = np.asarray(eact, float)
    b = np.searchsorted(np.array([thr, thr_hi]), eact, side="right").astype(np.uint8)
    w = np.broadcast_to(np.asarray(length, float), eact.shape)
    s = np.bincount(b.ravel(), weights=(eact * w).ravel(), minlength=3)
    n = np.bincount(b.ravel(), weights=w.ravel(), minlength=3)
    if (n <= 0).any():
        raise SystemExit("[X] 빈 등급이 있습니다 — 임계 · 위 경계를 확인하십시오")
    rep = s / n
    if not (rep[0] < thr <= rep[1] < thr_hi <= rep[2]):
        raise SystemExit("[X] 등급 대표값이 경계 밖입니다")
    return b, rep


def shipped_act(eact, thr, thr_hi, length):
    """앱이 길 찾기에 쓰는 활성도(#38) = 등급 대표값. 브라우저 = Python 대조(tools/app_parity_ref*.py)도 이 값으로 기준 경로를 만든다."""
    b, rep = grade_codes(eact, thr, thr_hi, length)
    return rep[b]


def pack2(codes):
    """0~3 코드를 한 바이트에 넷씩(앞 값이 아래 비트) — app.js unpack2 가 푼다."""
    c = np.ascontiguousarray(codes, np.uint8).ravel()
    c = np.r_[c, np.zeros((-len(c)) % 4, np.uint8)].reshape(-1, 4)
    return (c[:, 0] | (c[:, 1] << 2) | (c[:, 2] << 4) | (c[:, 3] << 6)).astype(np.uint8)


def unpack2(p, n):
    """pack2 의 역 — 시험 · 점검용."""
    p = np.asarray(p, np.uint8)
    return np.stack([(p >> s) & 3 for s in (0, 2, 4, 6)], axis=1).ravel()[:n]


def b64(a):
    """numpy 배열 → base64 (little-endian 바이트 그대로 — 브라우저가 TypedArray 로 읽는다)."""
    return base64.b64encode(np.ascontiguousarray(a).astype(a.dtype.newbyteorder("<")).tobytes()).decode("ascii")


REAL_PROTO = ROOT / "data" / "real" / "proto"   # 민간 실데이터 적재 결과(#19 · #20) — 이 PC 에만
REAL_OUT = ROOT / "real_app" / "app"             # 실데이터 판 앱(#32) — html/ 밖(공유본 KEEP 에 없다). 이 PC · 같은 와이파이에서만
REAL_PORT = 8788


def borrow_masked(P, masked, xy, sigma):
    """가린 칸 유동 빌리기(#34 · MASK_BORROW_SIGMA_M). P(시간대, 칸) 중 가린 칸 열만, 가리지 않은 칸 값의 가우스 가중 평균으로 바꾼다.
    가중치 exp(−d²/2σ²), 거리 3σ 안. 행은 가린 칸만 · 열은 가리지 않은 칸만이라 자기 칸 · 다른 가린 칸 값은 섞이지 않는다
    (가린 칸 원래 값을 아무리 바꿔도 결과가 같다 — tests/test_app.py). 3σ 안에 가리지 않은 칸이 없으면 0(사람 없음)으로 본다.
    참고 구현: data/real/bench/scripts/bench_lib.py gauss_op · drop_self. 반환: (새 P, 가린 칸마다 이웃 가중치 합 — 0 이면 빌릴 이웃 없음)."""
    P = np.asarray(P, float)
    masked = np.asarray(masked, bool)
    out = P.copy()
    if not masked.any():
        return out, np.zeros(0)
    xy = np.asarray(xy, float)
    don = ~masked
    D = cKDTree(xy[masked]).sparse_distance_matrix(cKDTree(xy[don]), 3 * sigma, output_type="coo_matrix")
    W = coo_matrix((np.exp(-(D.data ** 2) / (2 * sigma ** 2)), (D.row, D.col)), shape=(int(masked.sum()), int(don.sum()))).tocsr()
    s = np.asarray(W.sum(axis=1)).ravel()
    W = diags(np.where(s > 0, 1 / np.where(s > 0, s, 1), 0)) @ W
    out[:, masked] = np.asarray(W @ P[:, don].T).T
    return out, s


def world(src=PROTO, real=False, borrow=None):
    """시연 앱(proto_ui.world)과 같은 계산. 기본은 임의값 판(data/proto — 공개 웹에 올라갈 수 있는 판).
    real=True 면 data/real/proto(민간 실데이터 적재 결과)를 읽는다 — 결과는 REAL_OUT 에만 쓴다(#32).
    borrow(실데이터 판 기본 True, #34) — 가린 칸 유동을 이웃에서 빌린 값으로 계산한다(앱 · 경로 대조 기준).
    borrow=False 는 원래 값 — 기법 비교(data/real/bench)가 채점 기준으로 쓴다. 앱에 싣지 않는다."""
    rep = json.loads((src / "ingest_report.json").read_text(encoding="utf-8"))
    synth = rep.get("_meta", {}).get("synthetic") is True
    if not real and not synth:
        raise SystemExit("[X] data/proto 가 임의값이 아닙니다 — 공개 웹 앱에 실을 수 없습니다(build_share.public_safe 와 같은 규칙)")
    if real and synth:
        raise SystemExit("[X] data/real/proto 가 임의값입니다 — 실데이터 판을 만들 수 없습니다(py -3.12 src/ingest_inventory.py data/real/raw)")
    borrow = real if borrow is None else bool(borrow)
    nodes = pd.read_csv(PROC / "nodes.csv", encoding="utf-8-sig")
    edges = pd.read_csv(PROC / "edges.csv")
    t = np.load(src / "terms.npz")
    P = t["P"] if "P" in t.files else None
    wsum = None
    if real and borrow:
        if P is None:
            raise SystemExit("[X] 실데이터 적재 결과에 DS-032 유동(P)이 없습니다 — 가린 칸 값을 빌릴 수 없어 실데이터 판을 만들지 않습니다"
                             "(py -3.12 src/stage_real.py 202601 202606 DS-032 → ingest_inventory.py)")
        cells = pd.read_csv(PROC / "cells.csv", encoding="utf-8-sig")
        if len(cells) != P.shape[1]:
            raise SystemExit("[X] cells.csv 칸 수와 terms.npz 칸 수가 다릅니다 — 다시 적재하십시오")
        P, wsum = borrow_masked(P, t["masked"], cells[["x", "y"]].to_numpy(float), float(PM.MASK_BORROW_SIGMA_M.value))
    A = NC.activity(t["R"], t["V"], t["A_d"], P)
    G = NC.NightGraph(nodes, edges)
    eact = NC.edge_activity(A["act"], G.cell, G.u, G.v)                    # (28, 간선)
    thr = NC.dark_threshold(eact, G.length)
    thr_hi = NC.dark_threshold(eact, G.length, PM.GRADE_HI_Q.value)
    if real:
        world.real = {"t": t, "act": A["act"], "rep": rep, "borrow": borrow, "wsum": wsum}   # act — borrow 에 따라 빌린 값 / 원래 값
    return nodes, edges, G, eact, thr, thr_hi


def real_grades(G, eact, thr, thr_hi):
    """실데이터 판 화면 등급 — 1 사람 드묾 · 2 보통 · 3 사람 많음 (NC.grades, #19 와 같은 규칙).
    #34 부터 가린 칸(MASK_MIN_POP)도 이웃에서 빌린 유동으로 계산한 값(world borrow)이라 따로 가리지 않는다 — 0 '자료 부족'은 없다.
    경로 계산과 같은 eact · thr 로 만든다(보이는 등급 = 길을 고른 값)."""
    w = world.real
    if not w.get("borrow"):
        raise SystemExit("[X] 실데이터 판은 가린 칸 값을 빌린 world(borrow=True)로만 만든다")
    masked = np.asarray(w["t"]["masked"], bool)
    gr = NC.grades(eact, thr, thr_hi).astype(np.uint8)
    nm = masked[G.cell]
    ws = w["wsum"]
    stats = {"가린칸": int(masked.sum()), "그중_보행망칸": int(np.unique(G.cell[masked[G.cell]]).size),
             "가린칸에_닿는_간선": int((nm[G.u] | nm[G.v]).sum()), "빌릴_이웃_없는_가린칸": int((ws <= 0).sum()) if ws is not None else 0,
             "자료부족_간선": int((gr == 0).any(axis=0).sum()), "간선": int(G.m)}
    return gr, stats


def run_band_grades(G):
    """러닝 새벽 · 저녁 등급(#35 · RUN_BANDS) — data/real/proto/run_terms.npz(적재기가 DS-032 에서 따로 접은 시각)가 있을 때만.
    가린 칸은 #34 와 같이 이웃 값을 빌리고, 시간대 안에서 칸 유동 분위 → 간선(양 끝 평균) → 길이 가중 DARK_Q · GRADE_HI_Q 로
    1 사람 드묾 · 2 보통 · 3 사람 많음. 앵커 항은 쓰지 않는다(실데이터에 영업 시간이 없다). 앱에는 등급만 싣는다.
    반환: ({시간대: [시각 …]}, {시간대: uint8 (간선,)}) — 자료가 없으면 (None, {})."""
    p = REAL_PROTO / "run_terms.npz"
    if not p.exists():
        print("[!] data/real/proto/run_terms.npz 없음 — 러닝은 낮 · 밤 기준만(py -3.12 src/ingest_inventory.py data/real/raw 로 다시 적재)")
        return None, {}
    r = np.load(p)
    bands = [str(b) for b in r["bands"]]
    hours = json.loads(str(r["hours"]))
    cells = pd.read_csv(PROC / "cells.csv", encoding="utf-8-sig")
    Pb, _ = borrow_masked(r["P"], world.real["t"]["masked"], cells[["x", "y"]].to_numpy(float), float(PM.MASK_BORROW_SIGMA_M.value))
    out = {}
    for i, k in enumerate(bands):
        ea = NC.edge_activity(NC._pct_avg(Pb[i])[None, :], G.cell, G.u, G.v)     # (1, 간선)
        th = NC.dark_threshold(ea, G.length)
        hi = NC.dark_threshold(ea, G.length, PM.GRADE_HI_Q.value)
        out[k] = NC.grades(ea[0], th, hi).astype(np.uint8)
    return {k: hours[k] for k in bands}, out


def giant(G):
    """가장 큰 연결요소의 노드 — 지도에서 찍은 점은 여기로만 붙인다(섬처럼 떨어진 길에서 경로가 안 나오지 않게)."""
    m = coo_matrix((np.ones(G.m), (G.u, G.v)), shape=(G.n, G.n))
    _, lab = connected_components(m, directed=False)
    return (lab == np.bincount(lab).argmax()).astype(np.uint8)


def road_class(edges):
    """간선 길 종류 — 0 차 없는 길(보행로 · 산책로 · 계단 등) · 1 차가 같이 다니는 골목 · 단지 길 · 2 큰 찻길(MAJOR_ROAD)
    · 3 차도 옆 보도(OSM 에 따로 그린 것만, #26). + 산길 · 농로 표시(밤 기준)."""
    ep = pd.read_csv(PROTO / "edge_public.csv", encoding="utf-8-sig")
    if len(ep) != len(edges):
        raise SystemExit("[X] edge_public.csv 행 수가 edges.csv 와 다릅니다 — py -3.12 src/public_data.py 후 다시 적재")
    hw = ep["highway"].astype(str).to_numpy()
    tf = lambda col: ep[col].astype(str).str.lower().eq("true").to_numpy() if col in ep.columns else np.zeros(len(ep), bool)  # noqa: E731
    side, major = tf("sidewalk"), tf("major")
    cls = np.where(side, 3, np.where(np.isin(hw, list(CAR_FREE)), 0, np.where(major, 2, 1)))
    trail = np.isin(hw, list(TRAIL)) & ~side
    return cls.astype(np.uint8), trail.astype(np.uint8)


def ped_accidents(G, nodes):
    """보행 사고가 잦았던 곳(PED_ACC, #26) — 공개 자료(도로교통공단 다발지역). 같은 위치 이름은 한 곳으로 묶고
    (가장 최근 해의 범위), 그 범위와 겹치는 간선에 곳 번호(1부터)를 붙인다. 경로 계산에는 쓰지 않는다(표시 · 셈)."""
    acc_e = np.zeros(G.m, np.uint8)
    p = PROTO / "accidents.csv"
    if not p.exists():
        return [], acc_e, None
    import shapely
    a = pd.read_csv(p, encoding="utf-8-sig")
    cfg = PM.PED_ACC.value
    y1 = int(a["year"].max())
    y0 = y1 - int(cfg["years"]) + 1
    a = a[a["type"].isin(cfg["types"]) & a["year"].between(y0, y1)].sort_values(["name", "year"], kind="stable")
    places = []
    for name, g in a.groupby("name", sort=True):
        r = g.iloc[-1]
        ring = json.loads(r["ring"]) if isinstance(r["ring"], str) and r["ring"].startswith("[") else None
        places.append({"name": str(name), "lat": round(float(r["lat"]), 6), "lng": round(float(r["lon"]), 6),
                       "types": sorted(set(g["type"])), "years": sorted({int(y) for y in g["year"]}),
                       "n": int(g["n_acc"].sum()), "ring": ring})
    if len(places) > 254:
        raise SystemExit("[X] 사고 다발 위치가 254곳을 넘습니다 — acc_edge 를 Uint16 으로 바꾸십시오")
    lat, lon = nodes["lat"].to_numpy(), nodes["lon"].to_numpy()
    lines = shapely.linestrings(np.stack([np.c_[lon[G.u], lat[G.u]], np.c_[lon[G.v], lat[G.v]]], axis=1))
    tree = shapely.STRtree(lines)
    for k, pl in enumerate(places):
        if not pl["ring"]:
            continue
        hit = tree.query(shapely.Polygon([(q[1], q[0]) for q in pl["ring"]]), predicate="intersects")
        hit = hit[acc_e[hit] == 0]
        acc_e[hit] = k + 1
    return places, acc_e, [y0, y1]


def sun_table(year):
    """해 뜨는 · 지는 시각(분) — 1월 1일부터 하루씩. public_data.sun_times(NOAA 식, 안산 중심)와 같은 계산."""
    import public_data as PD
    lat, lon = PD.center_latlon()
    rise, sset, d = [], [], datetime.date(year, 1, 1)
    while d.year == year:
        r, s = PD.sun_times(d, lat, lon)
        rise.append(int(round(r * 60)))
        sset.append(int(round(s * 60)))
        d += datetime.timedelta(days=1)
    return {"year": year, "rise": rise, "set": sset}


def course_edges(G, courses):
    """코스 노드 열 → 간선 번호 열(같은 두 노드 사이 간선이 여럿이면 가장 짧은 것 — build_runs.edge_ids 와 같은 규칙)."""
    key = {}
    for e, (u, v, ln) in enumerate(zip(G.u.tolist(), G.v.tolist(), G.length.tolist())):
        k = (u, v) if u < v else (v, u)
        if k not in key or ln < G.length[key[k]]:
            key[k] = e
    for c in courses:
        n = c.pop("nodes", None) or []
        c["e"] = [key[(a, b) if a < b else (b, a)] for a, b in zip(n[:-1], n[1:])]


def shops(src=PROTO):
    """심야 업종 가게 블록(상가정보 이름 · 위치 — 공개)과 시간대별 '문 열었음'(임의값 결제의 과반 밤 규칙 ACTIVE_NIGHT_SHARE).
    실데이터 판은 카드 블록 위치가 없어 영업 여부를 모른다(hours_known False — 화면이 '영업 여부 모름'으로 쓴다)."""
    ab = pd.read_csv(src / "anchor_blocks.csv", encoding="utf-8-sig")
    share = ab[[f"s{i}" for i in range(len(NC.SLOTS))]].to_numpy(float)
    known = bool(np.isfinite(share).any())
    openm = (share >= PM.ACTIVE_NIGHT_SHARE.value) if known else np.ones(share.shape, bool)
    bits = (openm.astype(np.int64) << np.arange(len(NC.SLOTS))).sum(axis=1)
    out = []
    for r, b in zip(ab.itertuples(), bits):
        names = [s.strip() for s in str(r.names).split(" · ")] if isinstance(r.names, str) and r.names.strip() else []
        out.append([round(r.lat, 6), round(r.lon, 6), names[:3], int(b)])
    return out, known


def places(nodes):
    """검색 목록 — 역 · 행정동 · 지구대(공개 자료)."""
    out = []
    st = pd.read_csv(PROTO / "stations.csv", encoding="utf-8-sig")
    for r in st.itertuples():
        out.append({"t": f"{r.station}역", "s": f"{r.line}", "lat": round(r.lat, 6), "lng": round(r.lon, 6), "k": "역"})
    g = nodes.groupby("dong")[["lat", "lon"]].median()
    for d, r in g.iterrows():
        out.append({"t": str(d), "s": "행정동", "lat": round(r.lat, 6), "lng": round(r.lon, 6), "k": "동"})
    pol = pd.read_csv(PROTO / "police.csv", encoding="utf-8-sig")
    for r in pol[pol["night_open"].astype(bool)].itertuples():
        out.append({"t": str(r.name), "s": f"{r.kind} · {r.dong}", "lat": round(r.lat, 6), "lng": round(r.lon, 6), "k": "지구대"})
    return out


def police():
    pol = pd.read_csv(PROTO / "police.csv", encoding="utf-8-sig")
    pol = pol[pol["night_open"].astype(bool)]
    return [[round(r.lat, 6), round(r.lon, 6), str(r.name), str(r.kind)] for r in pol.itertuples()]


def courses():
    p = PROC / "run_courses.json"
    if not p.exists():
        print("[!] data/processed/run_courses.json 없음 — 러닝 코스 없이 만든다(py -3.12 src/build_runs.py)")
        return {"courses": []}
    return json.loads(p.read_text(encoding="utf-8"))                    # 노드 열은 build() 에서 간선 번호로 바꾼다


def build(out=OUT, real=False):
    """real=False — 공개 판(임의값 · html/app). real=True — 실데이터 판(data/real/proto · real_app/app, #32).
    공개 자료(보행망 길 종류 · 지구대 · 역 · 보행 사고 다발지 · 러닝 코스)는 두 판 모두 data/proto · data/processed 에서 읽는다."""
    if real:
        out = REAL_OUT if out == OUT else out
        if pathlib.Path(out).resolve().is_relative_to((ROOT / "html").resolve()):
            raise SystemExit("[X] 실데이터 판은 html/ 아래에 쓸 수 없습니다 — html 은 공유본(GitHub 공개)에 실립니다")
    nodes, edges, G, eact, thr, thr_hi = world(REAL_PROTO if real else PROTO, real)
    codes, levels = grade_codes(eact, thr, thr_hi, G.length)           # 시간대 × 간선, 행 우선 — 등급만(#38)
    lat = np.round(nodes["lat"].to_numpy() * 1e6).astype(np.int32)
    lng = np.round(nodes["lon"].to_numpy() * 1e6).astype(np.int32)
    sh, hours_known = shops(REAL_PROTO if real else PROTO)
    run = courses()
    course_edges(G, run.get("courses", []))
    road, trail = road_class(edges)
    acc, acc_e, acc_years = ped_accidents(G, nodes)
    hours = PM.NIGHT_HOURS.value
    data = {
        "meta": {
            "built": datetime.date.today().isoformat(), "synthetic": True,
            "slots": [list(s) for s in NC.SLOTS], "hours": hours,
            "thr": thr, "thr_hi": thr_hi, "act_levels": [float(x) for x in levels],
            "detour": PM.DETOUR.value, "alpha_grid": PM.ALPHA_GRID.value,
            "walk_mps": PM.WALK_MPS.value, "hours_known": hours_known, "anchor_r_m": PM.ANCHOR_R_M.value,
            "snap_max_m": PM.APP_SNAP_MAX_M.value, "route_options": PM.APP_ROUTE_OPTIONS.value, "run_pick": PM.RUN_PICK.value,
            "run_suggest": PM.RUN_SUGGEST.value,
            "run_pace": PM.RUN_PACE_MIN_KM.value, "run_done": PM.RUN_DONE.value, "trail_note": PM.RUN_TRAIL_NOTE.value["share"],
            "day_night": PM.RUN_DAYNIGHT.value, "sun": sun_table(datetime.date.today().year),
            "ped_acc": {"types": PM.PED_ACC.value["types"], "years": acc_years},
            "n": int(G.n), "m": int(G.m), "courses_built": run.get("built"),
        },
        "lat": b64(lat), "lng": b64(lng), "giant": b64(giant(G)),
        "u": b64(G.u.astype(np.int32)), "v": b64(G.v.astype(np.int32)), "len": b64(G.length.astype(np.float32)),
        "act2": b64(pack2(codes)), "road": b64(road), "trail": b64(trail), "acc_edge": b64(acc_e), "acc": acc,
        "shops": sh, "police": police(), "places": places(nodes), "courses": run.get("courses", []),
    }
    mstats = None
    if real:                                                            # 실데이터 판 — 화면 등급(가림 · 합침) · 출처 · 자정 주의
        gr, mstats = real_grades(G, eact, thr, thr_hi)
        if not np.array_equal(gr, codes + 1):                           # 화면 등급 = 길 찾기 등급(#38) — gr 은 따로 싣지 않는다
            raise SystemExit("[X] 화면 등급과 앱 파일 등급이 다릅니다")
        rp = world.real["rep"]
        tt = world.real["t"]
        hrs = np.array([h for _, h in NC.SLOTS])
        mid = float(tt["P"][hrs == 0].sum() / max(float(tt["P"][hrs == 23].sum()), 1e-9)) if "P" in tt.files else None
        data["meta"].update({"synthetic": False, "real": True, "months": rp.get("_meta", {}).get("months", []),
                             "mask_borrow_sigma_m": PM.MASK_BORROW_SIGMA_M.value, "mid_ratio": mid})
        rb, rung = run_band_grades(G)                                   # 러닝 새벽 · 저녁(#35) — 실데이터 판만
        if rung:
            data["rung"] = {k: b64(v) for k, v in rung.items()}
            data["meta"]["run_bands"] = rb
            mstats["러닝시간대"] = {k: f"드묾 {(v == 1).mean():.0%}" for k, v in rung.items()}
    if out.exists():
        shutil.rmtree(out, onexc=_writable)
    out.mkdir(parents=True)
    for f in STATIC:
        shutil.copy2(SRC_APP / f, out / f)
    js = "window.APP_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (out / "data.js").write_text(js, encoding="utf-8")
    make_icons(out / "icons")
    import hashlib                                                      # 판 번호 — 앱 파일 · 자료 · 아이콘이 바뀌면 바뀐다(설치된 앱이 새 판을 받게)
    hsh = hashlib.sha1()
    for f in (*STATIC, "data.js"):
        hsh.update((out / f).read_bytes())
    for p in sorted((out / "icons").glob("*.png")):
        hsh.update(p.read_bytes())
    ver = hsh.hexdigest()[:10]
    (out / "sw.js").write_text((SRC_APP / "sw.js").read_text(encoding="utf-8").replace("__VERSION__", ver), encoding="utf-8")
    serve = lambda port, host: (f"where py >nul 2>nul && (py -3 -m http.server {port} --bind {host}) || "   # noqa: E731
                                f"(python -m http.server {port} --bind {host})\r\n")
    head = "@echo off\r\nchcp 65001 >nul\r\ncd /d \"%~dp0\"\r\n"
    if not real:
        bat = (head + "rem 안산 밤길 앱 - 이 PC에서만 열린다(127.0.0.1). 시연판: 사람 수는 가상 데이터\r\n"
               f"start \"\" http://localhost:{PORT}/app/\r\n" + serve(PORT, "127.0.0.1"))
        (out.parent / "밤길앱_열기.bat").write_bytes(bat.encode("utf-8"))
    else:
        bat = (head + "rem 안산 밤길 앱 - 실데이터 판(내부 시연, #32). 이 PC에서만 열린다(127.0.0.1)\r\n"
               f"start \"\" http://localhost:{REAL_PORT}/app/\r\n" + serve(REAL_PORT, "127.0.0.1"))
        (out.parent / "밤길앱_실데이터.bat").write_bytes(bat.encode("utf-8"))
        lan = (head + "rem 실데이터 판을 같은 와이파이의 휴대폰으로 본다(#32). 집 · 사무실 와이파이에서만 쓰고 공용 와이파이에서는 열지 않는다.\r\n"
               "rem 처음에 Windows 방화벽 창이 뜨면 '개인 네트워크'만 허용한다. 휴대폰에서는 브라우저로 보기만 된다(설치는 https 주소가 있어야 한다).\r\n"
               "echo.\r\necho [!] 실데이터 판을 같은 와이파이에 엽니다 - 집/사무실 와이파이에서만 쓰십시오\r\n"
               f"echo 휴대폰 주소창에 아래 IPv4 주소 중 와이파이 쪽 주소 + :{REAL_PORT}/app/ (예: http://192.168.0.12:{REAL_PORT}/app/)\r\n"
               "ipconfig | findstr /i \"IPv4\"\r\necho.\r\n" + serve(REAL_PORT, "0.0.0.0"))
        (out.parent / "밤길앱_실데이터_휴대폰으로_보기.bat").write_bytes(lan.encode("utf-8"))
    mb = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 2**20
    if mstats:
        print(f"[i] 실데이터 판 가린 칸(MASK_MIN_POP) · 이웃 유동 빌리기 σ{PM.MASK_BORROW_SIGMA_M.value}m: {mstats}")
    print(f"[v] {out} · {mb:.2f} MB · 노드 {G.n:,} · 간선 {G.m:,} · 가게 블록 {len(sh):,} · 지구대 {len(data['police'])} · "
          f"검색 {len(data['places'])} · 러닝 코스 {len(data['courses'])} · 임계 {thr:.4f} / 위 경계 {thr_hi:.4f} · "
          f"보행 사고 잦았던 곳 {len(acc)}곳({acc_years}) · 간선 {int((acc_e > 0).sum())} · 보도 간선 {int((road == 3).sum())}")
    return data


if __name__ == "__main__":
    build(real="--real" in sys.argv[1:])
