# -*- coding: utf-8 -*-
"""
달리기 코스 생성기 — 드로잉 런(GPS 아트) 12종 + 차 없는 길 코스 (시민용 '안산 밤길' 지도)

실행 (3안 폴더에서, 약 6분)
    py -3.12 src/build_runs.py                    JSON 만
    py -3.12 src/build_runs.py --preview-dir 폴더  JSON + 코스별 미리보기 PNG (그 폴더에)
    → 다음에 py -3.12 src/build_app.py 로 앱에 싣는다

입력 — 공개 자료만, 읽기 전용
    data/processed/nodes.csv · edges.csv   OSM 보행망 (노드 번호 = nodes.csv 행 번호 · 좌표 EPSG:5179)
    data/proto/edge_public.csv            간선별 OSM highway · major (edges.csv 와 같은 행 순서)
    data/raw/ansan_walk.geojson           (있으면) OSM way 이름 — 차 없는 길 코스 이름에만 쓴다

출력
    data/processed/run_courses.json       코스 목록 (UTF-8, 1MB 미만)
    <preview-dir>/<코스 id>.png           코스마다 미리보기 한 장 (800×800, --preview-dir 를 줄 때만)

코스 고르는 기준(차 없는 길 종류 · 길이 범위 · 차 없는 길 비중 · 밤 불빛 안내)은 params.py(RUN_*)에 있다.
아래 '조정값' 블록은 그림 자리 찾기 · 흩어놓기의 탐색 손잡이다(CLAUDE.md 2절 예외 — 수정사항 #24).

드로잉 런 (그림 12종)
    그림마다 닫힌 외곽선을 단위 상자에 정의한다(손으로 찍은 점 · 원/타원 합성 · 매개변수 곡선).
    1단계  250m 격자 중심(보행망이 촘촘한 곳만) × 크기 3 × 회전 5 (× 좌우 반전)
           외곽선을 25m 간격으로 찍어 '같은 방향으로 뻗은 길'까지 거리의 제곱평균근(cKDTree)
           → 상위 중심 450곳 × 중심마다 상위 조합 3개
    2단계  외곽선을 ~100m 간격 경유점으로(뾰족한 꼭짓점은 반드시 포함) → 최근접 노드
           → 이웃 경유점끼리 최단경로(scipy dijkstra · limit, 그림 둘레 부분 그래프) → 되돌아가기 · 작은 고리 정리
           간선 비용 = 길이 × (1 + 2·큰길) × (1 + (그림까지 거리 / 60m)²)
           점수 = 경로 ↔ 그림 대칭 평균 거리(m, = fidelity_m)
                + 꼭짓점이 경로에서 먼 만큼(특징이 통째로 빠짐) + (1 − 면적 겹침 IoU) × 60m(가는 부분이 눌림)
                + 길이 비 1.35 초과 · 의도하지 않은 간선 재사용 · 3~7km 밖 벌점
           서로 떨어진 상위 30곳은 이동 · 회전 · 크기를 조금씩 바꿔 다듬는다(패턴 탐색).
    고르기 그림마다 서로 다른 자리 200곳 중 하나씩 — (점수 합 + 코스 쌍마다 자리 겹침 · 같은 동 벌점 합)이 작도록
           한 그림씩 다시 고르기를 되풀이한다. 그림이 한 동네에 몰리지 않게 하면서 좋은 자리는 지킨다.

차 없는 길 (4~8개)
    path · footway · pedestrian · steps · track (· cycleway · bridleway) 만 '차가 다니지 않는 길'로 친다.
    living_street · service · residential · unclassified 와 큰길은 아니다.
    OSM 에 차도 옆 보도로 따로 그린 길(footway=sidewalk — edge_public.csv sidewalk)도 아니다(#26).
    차 없는 길 덩어리마다 떨어진 두 점 → 서로 겹치지 않는 두 길로 한 바퀴(loop) — 안 되면 왕복(loop: false).
    길이 2~8km · 차 없는 길 비중 80% 이상만 남기고, 겹치거나 나란히 가는 코스는 뺀다(덩어리당 2개 · 같은 동 감점).
    이름은 코스 위 차 없는 길에 붙은 OSM 이름 중 가장 긴 것(코스의 20% 이상일 때), 없으면 '<동> 차 없는 길'.

무작위 요소가 없다 — 같은 입력이면 같은 결과(정렬은 모두 안정 정렬).
"""
import argparse
import datetime
import json
import math
import pathlib
import sys
import time

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree
import shapely
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import params as PM  # noqa: E402

PROC = ROOT / "data" / "processed"
PROTO = ROOT / "data" / "proto"
RAW = ROOT / "data" / "raw"
OUT_JSON = PROC / "run_courses.json"
SOURCE_NOTE = "OpenStreetMap 보행망 (data/processed) · 공개 자료만"

# ── 코스 고르는 기준 — params.py (시민에게 보이는 기준) ──
CAR_FREE_CLASSES = tuple(PM.RUN_CAR_FREE_HW.value)
TRAIL_CLASSES = tuple(PM.RUN_TRAIL_NOTE.value["classes"])     # 산길 · 오솔길 · 농로 · 임도 — 밤에 불빛이 적을 수 있는 길
RANGE_KM = tuple(PM.RUN_COURSE_KM.value["drawing"])           # 드로잉 런 길이 범위 — 벗어나면 1km 당 RANGE_PENALTY_M
CF_MIN_M, CF_MAX_M = (1000.0 * k for k in PM.RUN_COURSE_KM.value["carfree"])
CF_SHARE_MIN = PM.RUN_CF_SHARE_MIN.value

# ── 조정값 — 그림 자리 찾기 · 흩어놓기의 탐색 손잡이(CLAUDE.md 2절 예외 · 수정사항 #24). 바꾸면 결과 코스 모양이 바뀐다 ──
MAJOR_COST = 2.0                 # 간선 비용 = 길이 × (1 + 2·큰길) — 큰 찻길을 조금 피한다

# 드로잉 런 1단계 (값싼 거르기)
GRID_M = 250.0                   # 후보 중심 격자
DENSE_RADIUS_M = 400.0           # 보행망 밀도를 재는 반경
DENSE_MIN_KM_PER_KM2 = 15.0      # 이보다 성긴 곳은 중심 후보에서 뺀다
NET_SAMPLE_M = 8.0               # 보행망을 이 간격의 점으로 찍어 방향별 KD 트리를 만든다
ANGLE_BINS = 12                  # 방향 구간 15°
ANGLE_TOL_DEG = 22.5             # 구간 중심에서 이 각도 안의 길을 '같은 방향'으로 본다
STAGE1_STEP_M = 25.0
STAGE1_CAP_M = 80.0              # 1단계 거리 상한 — 제곱 평균이라 길이 없는 구간(그림이 빠질 곳)을 크게 친다
SCALE_FACTORS = (0.9, 1.0, 1.1)
ROUTE_TO_OUTLINE = 1.33          # 경로 길이 ÷ 외곽선 둘레 (1차 시험 실측 1.23~1.47) — 목표 길이를 그림 크기로
TOP_CENTERS = 450                # 1단계 최고점 순으로 이만큼의 중심을 2단계로 넘긴다
PER_CENTER = 3                   # 중심마다 1단계 상위 (크기 · 회전 · 반전) 조합 수
                                 # 1단계 순위와 2단계 점수의 순위상관이 0.13~0.23 뿐이라(시험 실측) 넓게 넘기고 2단계에서 가린다

# 드로잉 런 2단계 (실제 경로)
WAYPOINT_M = 100.0
PROX_D0_M = 60.0                 # 그림에서 60m 떨어진 간선은 비용 2배
PROX_CAP_M = 180.0
LOCAL_MARGIN_M = 300.0           # 경로는 그림 상자 + 이 여유 안의 부분 그래프에서 찾는다
FIDELITY_STEP_M = 20.0
LEN_RATIO_MAX = 1.35
LEN_PENALTY_M = 120.0            # 길이 비 1.35 초과 1.0 당 벌점(m)
REUSE_PENALTY_M = 150.0          # 의도하지 않은 간선 재사용 비율 1.0 당 벌점(m)
RANGE_PENALTY_M = 60.0           # 길이 범위(RUN_COURSE_KM drawing) 밖 1km 당 벌점(m)
KEY_FREE_M = 20.0                # 꼭짓점(별 끝 · 귀 끝 · 집게)이 경로에서 이만큼까지는 벌점 없음
KEY_WEIGHT = 0.5                 # 꼭짓점 거리 제곱평균근이 KEY_FREE_M 를 넘는 만큼 × 0.5 — 특징이 통째로 빠진 자리를 거른다
IOU_WEIGHT_M = 60.0              # (1 − 면적 겹침 IoU) × 60m — 가는 부분(날개 · 목)이 한 줄로 눌린 자리를 거른다
CYCLE_MAX_M = 260.0              # 이보다 짧은 군더더기 고리는 잘라낸다

# 2단계 다듬기 — 상위 후보를 조금씩 옮기고 돌리고 키워 본다(패턴 탐색)
POLISH_N = 30                    # 서로 500m 이상 떨어진 상위 자리 30곳을 다듬는다 — 다듬기 전후 점수 차가 크고(시험:
                                 # 94→47, 81→49) 순서도 뒤바뀌어, 다듬은 자리끼리 견줘야 덜 붐비는 동네의 좋은 자리가 보인다
POLISH_ROUNDS = 7
POLISH_STEP = (80.0, 6.0, 0.06)  # 이동 m · 회전 ° · 크기 비 — 나아지지 않으면 반으로
SCALE_LIMIT = (0.85, 1.15)       # 기준 크기 대비 허용 범위

# 그림끼리 흩어놓기
SPREAD_POOL = 200                # 그림마다 서로 다른 자리(150m 이상 떨어진)를 이만큼 남긴다
SPREAD_OPTIONS = 80              # 그중 점수 상위 80곳을 놓고 고른다
SPREAD_RESTARTS = 40             # 고정 시드 무작위 시작안 수
SPREAD_SEED = 20261120
OVERLAP_PENALTY_M = 40.0         # 두 그림 면이 완전히 겹치면(작은 면 기준) +40m — 겹친 비율만큼
OVERLAP_GAP_M = 100.0            # 두 그림이 이보다 가까우면 겹친 것으로 친다
SAME_DONG_PENALTY_M = 4.0        # 같은 동에 놓인 코스 쌍마다 +4m
REGRET_FREE, REGRET_WEIGHT = 8.0, 0.15   # 자기 최고 점수보다 8 넘게 나쁜 자리는 (초과분)² × 0.15 를 더 친다

# 차 없는 길 (길이 범위 · 차 없는 길 비중은 위 params)
NONCF_COST = 12.0               # 차 없는 길이 아닌 간선은 길이의 12배로 친다(이어 붙일 때만 잠깐)
CF_COMP_MIN_M = 1500.0           # 이보다 작은 차 없는 길 덩어리는 씨앗으로 안 쓴다
CF_SEED_SPACING_M = 1500.0
CF_TARGETS_M = (2600.0, 1900.0, 1300.0)   # 출발점에서 반환점까지 차 없는 길 거리 목표
CF_DISJOINT_MAX = 0.15           # 두 길이 이보다 많이 겹치면 한 바퀴가 아니라 왕복
CF_MAX_COURSES, CF_MIN_COURSES = 8, 4
CF_PER_COMPONENT = 2             # 같은 차 없는 길 덩어리에서 최대 2개
CF_SAME_DONG_PENALTY = 0.15      # 이미 고른 코스와 같은 동이면 품질 점수에서 뺀다
CF_DUP_M, CF_DUP_SHARE = 50.0, 0.35   # 한쪽 길이의 35% 이상이 다른 코스 50m 안 → 겹치는 코스로 보고 뺀다
GENERIC_WAY_NAMES = {"산책로", "보도", "휴게광장", "진입광장", "중심광장", "단풍광장", "맨발 산책로", "광장"}

# (key, 코스 이름, 목표 경로 길이 km, 좌우 반전 허용, 회전 한계 °)
# 동물은 많이 기울면 넘어진 것처럼 보여 ±12°, 별 · 하트 · 달은 ±20°
SHAPE_SPECS = [
    ("whale", "고래런", 6.2, True, 12),
    ("rabbit", "토끼런", 5.2, False, 12),
    ("cat", "고양이런", 5.4, False, 12),
    ("fish", "물고기런", 5.0, True, 12),
    ("turtle", "거북이런", 6.2, False, 12),
    ("dinosaur", "공룡런", 6.6, True, 12),
    ("crab", "꽃게런", 5.8, False, 12),
    ("grapes", "포도런", 6.4, True, 12),
    ("seagull", "갈매기런", 5.6, False, 12),
    ("moon", "초승달런", 3.8, True, 20),
    ("star", "별런", 4.6, False, 20),
    ("heart", "하트런", 3.4, False, 20),
]


def log(msg):
    print(msg, flush=True)


# ══ 폴리라인 도구 ═════════════════════════════════════════════════════
def arc_lengths(P):
    seg = np.hypot(*np.diff(P, axis=0).T)
    return np.r_[0.0, np.cumsum(seg)]


def resample_polyline(P, step, closed):
    """폴리라인을 step 간격 점으로. closed 면 마지막 → 처음 구간까지 포함(끝점 중복 없음)."""
    P = np.asarray(P, float)
    Q = np.vstack([P, P[:1]]) if closed else P
    s = arc_lengths(Q)
    total = s[-1]
    if total <= 0:
        return Q[:1].copy()
    n = max(2, int(round(total / step)))
    t = np.linspace(0.0, total, n, endpoint=not closed)
    return np.c_[np.interp(t, s, Q[:, 0]), np.interp(t, s, Q[:, 1])]


def resample_with_keys(P, key_idx, step):
    """닫힌 외곽선 → ~step 간격 경유점. key_idx(뾰족한 꼭짓점)는 반드시 경유점이 된다. → (점, 꼭짓점 여부)"""
    Q = np.vstack([P, P[:1]])
    s = arc_lengths(Q)
    total = s[-1]
    keys = np.sort(s[np.asarray(key_idx, int)]) if len(key_idx) else np.array([0.0])
    arcs, flags = [], []
    for j, a in enumerate(keys):
        b = keys[j + 1] if j + 1 < len(keys) else keys[0] + total
        n = max(1, int(round((b - a) / step)))
        for t in range(n):
            arcs.append((a + (b - a) * t / n) % total)
            flags.append(t == 0)
    arcs = np.asarray(arcs)
    pts = np.c_[np.interp(arcs, s, Q[:, 0]), np.interp(arcs, s, Q[:, 1])]
    return pts, np.asarray(flags)


def key_vertices(P, delta=0.05, min_turn_deg=45.0):
    """꺾임이 큰 꼭짓점(별 끝 · 귀 끝 · 꼬리 갈래 · 가지 끝 · 다리 끝). P 는 단위 크기(최대 변 1) 외곽선.
    앞뒤 delta 만큼 떨어진 점으로 방향을 재므로 작은 반원(거북이 다리 끝)도 잡힌다."""
    Q = np.vstack([P, P[:1]])
    s = arc_lengths(Q)
    total = s[-1]
    sv = s[:-1]

    def at(arc):
        arc = np.mod(arc, total)
        return np.c_[np.interp(arc, s, Q[:, 0]), np.interp(arc, s, Q[:, 1])]

    d_in = P - at(sv - delta)
    d_out = at(sv + delta) - P
    turn = np.abs(np.angle(np.exp(1j * (np.arctan2(d_out[:, 1], d_out[:, 0])
                                        - np.arctan2(d_in[:, 1], d_in[:, 0])))))
    cand = np.flatnonzero(turn > np.radians(min_turn_deg))
    keep = []
    for i in cand[np.argsort(-turn[cand], kind="stable")]:
        if all(min(abs(sv[i] - sv[j]), total - abs(sv[i] - sv[j])) > delta for j in keep):
            keep.append(int(i))
    return np.sort(np.asarray(keep, int))


def retrace_length(P):
    """외곽선 안에서 같은 선분을 되짚는 길이(가지 · 수염처럼 나갔다 돌아오는 부분)."""
    Q = np.vstack([P, P[:1]])
    a = np.round(Q[:-1], 6)
    b = np.round(Q[1:], 6)
    seen, total = set(), 0.0
    for p, q in zip(map(tuple, a), map(tuple, b)):
        if p == q:
            continue
        k = (min(p, q), max(p, q))
        if k in seen:
            total += math.hypot(p[0] - q[0], p[1] - q[1])
        else:
            seen.add(k)
    return total


# ══ 그림 외곽선 ═══════════════════════════════════════════════════════
def _circle(cx, cy, r):
    return Point(cx, cy).buffer(r, quad_segs=24)


def _ellipse(cx, cy, rx, ry, angle=0.0):
    e = affinity.scale(Point(0, 0).buffer(1.0, quad_segs=32), rx, ry, origin=(0, 0))
    return affinity.translate(affinity.rotate(e, angle, origin=(0, 0)), cx, cy)


def _outline(geom):
    """도형 합성 결과 → 바깥 테두리 점(반시계, 끝점 중복 없음)."""
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda g: g.area)
    return np.asarray(orient(geom, 1.0).exterior.coords)[:-1]


def _hand(points, n_iter=3):
    """손으로 찍은 [(x, y[, 뾰족]) …] → Chaikin 모서리 깎기. 뾰족 표시한 점은 그대로 둔다."""
    P = np.array([(p[0], p[1]) for p in points], float)
    S = np.array([len(p) > 2 and bool(p[2]) for p in points])
    for _ in range(n_iter):
        out, out_s = [], []
        n = len(P)
        for i in range(n):
            if S[i]:
                out.append(P[i])
                out_s.append(True)
            else:
                a, b, c = P[i - 1], P[i], P[(i + 1) % n]
                out += [0.25 * a + 0.75 * b, 0.75 * b + 0.25 * c]
                out_s += [False, False]
        P, S = np.array(out), np.array(out_s)
    return P


def _insert(ring, base, seq):
    """ring 에서 base 에 가장 가까운 꼭짓점 뒤에 seq(나갔다 돌아오는 점들)를 끼운다."""
    ring = np.asarray(ring, float)
    i = int(np.argmin(np.hypot(*(ring - np.asarray(base, float)).T)))
    return np.vstack([ring[: i + 1], np.asarray(seq, float), ring[i: i + 1], ring[i + 1:]])


def _out_back(*pts):
    pts = [np.asarray(p, float) for p in pts]
    return np.vstack(pts + pts[-2::-1])


def shape_whale():
    """옆에서 본 고래(왼쪽을 봄) — 크고 둥근 머리 · 들어 올린 꼬리 끝의 가로 꼬리지느러미 · 물 뿜는 가지."""
    pts = [(0, 16), (1, 27), (7, 38), (18, 46), (32, 49), (46, 47), (60, 42), (71, 35), (78, 29, True),
           (83, 31), (86, 36), (87, 41, True), (81, 47), (74, 54, True), (86, 55), (96, 51, True),
           (106, 55), (118, 54, True), (111, 47), (104, 41, True), (103, 32), (99, 22), (92, 14),
           (81, 8), (64, 3), (46, 0), (28, 0), (13, 2), (4, 8)]
    ring = _hand(pts)
    head = ring[np.argmin(np.hypot(ring[:, 0] - 30, ring[:, 1] - 50))]
    x, y = head
    spout = [(x, y + 13), (x - 9, y + 23), (x, y + 13), (x + 9, y + 23), (x, y + 13)]
    return _insert(ring, head, spout)


def shape_rabbit():
    """앞에서 본 토끼 얼굴 — 둥근 머리 + 긴 귀 둘."""
    return _outline(unary_union([_circle(0, 0, 30),
                                 _ellipse(-14, 50, 10.5, 30, 10), _ellipse(14, 50, 10.5, 30, -10)]))


def shape_cat():
    """고양이 얼굴 — 넓은 얼굴 · 뾰족한 귀 둘 · 양쪽 수염 둘씩(가지)."""
    ring = _outline(unary_union([_ellipse(0, 0, 38, 29),
                                 Polygon([(-36, 8), (-31, 54), (-5, 27)]),
                                 Polygon([(36, 8), (31, 54), (5, 27)])]))
    for side in (-1, 1):
        for yb, ang in ((-3, 8), (-13, -10)):
            tip = (side * 62, yb + math.tan(math.radians(ang)) * 25)
            ring = _insert(ring, (side * 37.2, yb), _out_back(tip))
    return ring


def shape_fish():
    """물고기(왼쪽을 봄) — 렌즈 몸통 · 등지느러미 · 갈라진 꼬리."""
    pts = [(0, 0, True), (4, 10), (14, 18), (26, 21), (32, 21, True), (48, 38, True), (56, 17, True), (63, 10),
           (70, 5, True), (102, 33, True), (88, 0, True), (102, -33, True), (70, -5, True), (63, -10), (52, -17),
           (38, -21), (24, -21), (12, -17), (4, -9)]
    return _hand(pts)


def shape_turtle():
    """위에서 본 거북이 — 타원 등딱지 · 머리 · 다리 넷 · 꼬리."""
    parts = [_ellipse(0, 0, 30, 36), _circle(0, 51, 12), Polygon([(-7, 30), (7, 30), (7, 44), (-7, 44)]),
             Polygon([(-8, -33), (8, -33), (0, -52)])]
    for sx in (-1, 1):
        parts += [_ellipse(sx * 32, 25, 10.5, 16, -sx * 40), _ellipse(sx * 32, -25, 10.5, 16, sx * 40)]
    return _outline(unary_union(parts))


def shape_dinosaur():
    """목이 긴 초식 공룡(옆모습, 왼쪽을 봄) — 몸통 · 긴 목과 작은 머리 · 긴 꼬리 · 기둥 다리 둘."""
    t = np.linspace(0, 1, 40)
    neck = unary_union([_circle(a, b, r) for a, b, r in
                        zip(-20 - 28 * t - 4 * np.sin(np.pi * t), 8 + 52 * t, 10 - 3 * t)])
    tail = unary_union([_circle(a, b, r) for a, b, r in
                        zip(26 + 64 * t, 4 - 10 * t + 3 * np.sin(np.pi * t), 11 * (1 - t) + 1.0)])
    legs = [Polygon([(-24, -6), (-10, -6), (-10, -42), (-24, -42)]),
            Polygon([(9, -6), (23, -6), (23, -42), (9, -42)])]
    return _outline(unary_union([_ellipse(0, 0, 32, 19), neck, _ellipse(-55, 62, 10, 6.5, 8), tail] + legs))


def shape_crab():
    """위에서 본 꽃게 — 넓은 등딱지 · 위로 든 집게발 둘(벌어진 집게) · 옆다리 한 쌍."""
    parts = [_ellipse(0, 0, 34, 21)]
    for s in (-1, 1):
        cx, cy = s * 34, 50
        parts.append(LineString([(s * 18, 12), (s * 31, 37)]).buffer(7.5))
        parts.append(_circle(cx, cy, 16).difference(Polygon([(cx, cy - 1), (cx - 11, cy + 23), (cx + 11, cy + 23)])))
        a = math.radians(-35)
        x0, yb = s * 28, -6
        parts.append(Polygon([(x0, yb + 8), (x0 + s * 28 * math.cos(a), yb + 28 * math.sin(a)), (x0, yb - 8)]))
    return _outline(unary_union(parts))


def shape_grapes():
    """포도송이 — 알이 3·2·1 줄로 달린 역삼각형(물결 테두리) · 꼭지 · 잎."""
    cs = []
    for k, n in enumerate([3, 2, 1]):                         # 알 사이를 띄워 오목한 홈을 깊게(물결이 길 위에서도 남게)
        for j in range(n):
            cs.append(_circle((j - (n - 1) / 2) * 2.3, -k * 2.0, 1.25))
    ring = _outline(unary_union(cs))
    top = ring[np.argmax(ring[:, 1] - 0.3 * np.abs(ring[:, 0]))]
    x, y = top
    stem = (x + 0.1, y + 0.9)
    leaf = [(x + 0.8, y + 1.9), (x + 2.1, y + 2.3), (x + 3.3, y + 1.6), (x + 2.2, y + 0.9), (x + 1.0, y + 0.8)]
    return _insert(ring, top, [stem] + leaf + [stem, (x - 0.5, y + 2.1), stem])


def shape_seagull():
    """날개를 편 갈매기(앞에서 본 굵은 M 자) — 손목에서 꺾인 날개 · 아래로 뾰족한 날개 끝 · 가운데 아래 뾰족한 몸.
    날개 위 · 아래 테두리를 나란히(모두 ±45°) 두었다 — 테두리가 벌어지면 어느 격자에도 안 맞아 계단이 엉킨다.
    45° 로 기운 길(월피동 · 부곡동 · 이동 등)에서는 그대로 길을 따라간다."""
    center = [(-60, 0), (-30, 30), (0, 0), (30, 30), (60, 0)]
    body = LineString(center).buffer(9.5, cap_style="flat", join_style="mitre", mitre_limit=4.0)
    tips = []
    for (ax, ay), (bx, by) in (((-30, 30), (-60, 0)), ((30, 30), (60, 0))):
        d = np.array([bx - ax, by - ay], float) / math.hypot(bx - ax, by - ay)
        n = np.array([-d[1], d[0]])
        base = np.array([bx, by]) - 3 * d                      # 날개 안쪽으로 겹쳐 붙여야 합친 테두리에 틈이 안 생긴다
        tips.append(Polygon([base + 9.5 * n, np.array([bx, by]) + 16 * d, base - 9.5 * n]))
    return _outline(unary_union([body] + tips))


def shape_moon():
    """초승달 — 큰 원에서 비켜 놓은 원을 뺀 모양."""
    g = _circle(0, 0, 1.0).difference(_circle(0.42, 0.22, 0.86))
    return _outline(affinity.rotate(g, -15, origin=(0, 0)))


def shape_star():
    """오각별 — 안쪽 반지름 0.5 (정오각별 0.38 보다 팔을 굵게 — 가는 팔은 길 위에서 한 줄로 눌린다)."""
    k = np.arange(10)
    r = np.where(k % 2 == 0, 1.0, 0.5)
    a = np.pi / 2 + k * np.pi / 5
    return np.c_[r * np.cos(a), r * np.sin(a)]


def shape_heart():
    t = np.linspace(0, 2 * np.pi, 240, endpoint=False)
    x = 16 * np.sin(t) ** 3
    y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    return np.c_[x, y][::-1]


SHAPE_BUILDERS = {"whale": shape_whale, "rabbit": shape_rabbit, "cat": shape_cat, "fish": shape_fish,
                  "turtle": shape_turtle, "dinosaur": shape_dinosaur, "crab": shape_crab, "grapes": shape_grapes,
                  "seagull": shape_seagull, "moon": shape_moon, "star": shape_star, "heart": shape_heart}


class Template:
    """단위 외곽선(가로 · 세로 중 긴 쪽 = 1, 상자 중심 = 원점) + 자리 탐색에 쓸 값."""

    def __init__(self, key, name, target_km, mirror, rot_limit):
        P = np.asarray(SHAPE_BUILDERS[key](), float)
        lo, hi = P.min(0), P.max(0)
        self.unit = (P - (lo + hi) / 2) / (hi - lo).max()
        self.key, self.name, self.target_km, self.mirror = key, name, target_km, mirror
        self.rot_limit = float(rot_limit)
        self.rotations = [float(r) for r in np.linspace(-rot_limit, rot_limit, 5)]
        self.perimeter = float(arc_lengths(np.vstack([self.unit, self.unit[:1]]))[-1])
        self.retrace = retrace_length(self.unit)
        self.key_idx = key_vertices(self.unit)
        base = target_km * 1000.0 / (ROUTE_TO_OUTLINE * self.perimeter)
        self.scales = [base * f for f in SCALE_FACTORS]
        self.scale_ref = base
        self.unit_region = filled_region(self.unit)

    def place(self, cx, cy, scale, rot_deg, mirror):
        P = self.unit * np.array([-1.0 if mirror else 1.0, 1.0]) * scale
        a = math.radians(rot_deg)
        R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        return P @ R.T + np.array([cx, cy])

    def region(self, cx, cy, scale, rot_deg, mirror):
        """place() 와 같은 변환을 그림의 면에 — 면적 겹침(IoU) 계산용."""
        g = affinity.scale(self.unit_region, xfact=-scale if mirror else scale, yfact=scale, origin=(0, 0))
        return affinity.translate(affinity.rotate(g, rot_deg, origin=(0, 0)), cx, cy)


# ══ 보행망 ══════════════════════════════════════════════════════════════
class RunGraph:
    """보행망 + 간선 속성. CSR 구조는 한 번 만들고 비용 벡터만 바꿔 끼운다(night_core.NightGraph 와 같은 방식)."""

    def __init__(self):
        nodes = pd.read_csv(PROC / "nodes.csv", encoding="utf-8-sig")
        edges = pd.read_csv(PROC / "edges.csv")
        attr = pd.read_csv(PROTO / "edge_public.csv", encoding="utf-8-sig")
        if len(attr) != len(edges):
            raise SystemExit(f"edge_public.csv 행 수({len(attr)})가 edges.csv({len(edges)})와 다르다")
        self.n, self.m = len(nodes), len(edges)
        self.u = edges["u"].to_numpy(np.int64)
        self.v = edges["v"].to_numpy(np.int64)
        self.length = edges["len_m"].to_numpy(float)
        self.xy = nodes[["x", "y"]].to_numpy(float)
        self.x_list, self.y_list = self.xy[:, 0].tolist(), self.xy[:, 1].tolist()   # 파이썬 반복문용
        self.latlon = nodes[["lat", "lon"]].to_numpy(float)
        self.dong = nodes["dong"].astype(str).to_numpy()
        self.dong_names, self.dong_code = np.unique(self.dong, return_inverse=True)
        self.highway = attr["highway"].fillna("unknown").astype(str).to_numpy()
        self.major = attr["major"].astype(str).str.lower().eq("true").to_numpy()
        # 차도 옆 보도로 따로 그린 길(OSM footway=sidewalk)은 차 없는 길이 아니다(#26 — 초지동 코스가 97% 보도였다)
        self.sidewalk = attr["sidewalk"].astype(str).str.lower().eq("true").to_numpy() if "sidewalk" in attr.columns \
            else np.zeros(self.m, bool)
        self.car_free = np.isin(self.highway, CAR_FREE_CLASSES) & ~self.sidewalk
        rows, cols = np.r_[self.u, self.v], np.r_[self.v, self.u]
        eid = np.r_[np.arange(self.m), np.arange(self.m)]
        o = np.lexsort((cols, rows))
        self._cols, self._eid = cols[o].astype(np.int32), eid[o]
        self._indptr = np.r_[0, np.cumsum(np.bincount(rows, minlength=self.n))].astype(np.int32)
        key = np.minimum(self.u, self.v) * self.n + np.maximum(self.u, self.v)
        self._ko = np.argsort(key, kind="stable")
        self._ks = key[self._ko]
        self.tree = cKDTree(self.xy)
        self.mid = (self.xy[self.u] + self.xy[self.v]) / 2
        self.base_cost = self.length * (1.0 + MAJOR_COST * self.major)

    def matrix(self, w):
        return csr_matrix((w[self._eid], self._cols, self._indptr), shape=(self.n, self.n))

    def edge_ids(self, path):
        path = np.asarray(path, np.int64)
        if len(path) < 2:
            return np.array([], np.int64)
        a, b = path[:-1], path[1:]
        key = np.minimum(a, b) * self.n + np.maximum(a, b)
        return self._ko[np.searchsorted(self._ks, key)]

    def path_length(self, path):
        return float(self.length[self.edge_ids(path)].sum())


def shortest_path(M, a, b, limit=np.inf):
    """a → b 최단경로 노드 목록. limit 안에서 못 찾으면 제한 없이 한 번 더."""
    if a == b:
        return [int(a)]
    for lim in ((limit, np.inf) if np.isfinite(limit) else (np.inf,)):
        dist, pred = dijkstra(M, directed=True, indices=int(a), return_predecessors=True, limit=lim)
        if np.isfinite(dist[b]):
            p = [int(b)]
            while p[-1] != a:
                p.append(int(pred[p[-1]]))
            return p[::-1]
    return None


# ══ 드로잉 런 ══════════════════════════════════════════════════════════
class NetSamples:
    """보행망을 NET_SAMPLE_M 간격 점으로 찍고, 길 방향(15° 구간)별 KD 트리를 만든다."""

    def __init__(self, G):
        a, b = G.xy[G.u], G.xy[G.v]
        n_per = np.maximum(1, np.ceil(G.length / NET_SAMPLE_M).astype(int))
        eidx = np.repeat(np.arange(G.m), n_per)
        k = np.arange(n_per.sum()) - np.repeat(np.cumsum(n_per) - n_per, n_per)
        t = (k + 0.5) / n_per[eidx]
        self.xy = a[eidx] + (b - a)[eidx] * t[:, None]
        self.weight = (G.length / n_per)[eidx]
        d = b - a
        ang = np.mod(np.arctan2(d[:, 1], d[:, 0]), np.pi)[eidx]
        self.tree_all = cKDTree(self.xy)
        width = np.pi / ANGLE_BINS
        tol = np.radians(ANGLE_TOL_DEG)
        self.trees = []
        for c in (np.arange(ANGLE_BINS) + 0.5) * width:
            diff = np.abs(np.mod(ang - c + np.pi / 2, np.pi) - np.pi / 2)
            self.trees.append(cKDTree(self.xy[diff <= tol]))

    def dense_centers(self, G):
        """GRID_M 격자 중 반경 DENSE_RADIUS_M 안 보행망 밀도가 DENSE_MIN 이상인 중심."""
        lo = np.floor(G.xy.min(0) / GRID_M) * GRID_M
        hi = G.xy.max(0)
        gx, gy = np.meshgrid(np.arange(lo[0], hi[0] + 1, GRID_M), np.arange(lo[1], hi[1] + 1, GRID_M))
        C = np.c_[gx.ravel(), gy.ravel()]
        idx = self.tree_all.query_ball_point(C, DENSE_RADIUS_M)
        km = np.array([self.weight[i].sum() / 1000.0 for i in idx])
        dens = km / (math.pi * (DENSE_RADIUS_M / 1000.0) ** 2)
        return C[dens >= DENSE_MIN_KM_PER_KM2]


def outline_bins(pts):
    """닫힌 점열의 접선 방향 → ANGLE_BINS 구간 번호."""
    d = np.roll(pts, -1, axis=0) - np.roll(pts, 1, axis=0)
    ang = np.mod(np.arctan2(d[:, 1], d[:, 0]), np.pi)
    return np.minimum((ang / (np.pi / ANGLE_BINS)).astype(int), ANGLE_BINS - 1)


def stage1(T, ns, centers):
    """값싼 거르기 — 외곽선 점마다 '같은 방향 길'까지 거리(상한 80m)의 제곱 평균근.
    중심마다 (크기 · 회전 · 반전) 조합 상위 PER_CENTER 개, 최고점 순 TOP_CENTERS 개 중심."""
    rows = []
    for si, scale in enumerate(T.scales):
        for mirror in ((False, True) if T.mirror else (False,)):
            for rot in T.rotations:
                rel = T.place(0.0, 0.0, scale, rot, mirror)
                pts = resample_polyline(rel, STAGE1_STEP_M, closed=True)
                bins = outline_bins(pts)
                D = np.empty((len(centers), len(pts)))
                for b in np.unique(bins):
                    j = np.flatnonzero(bins == b)
                    q = (centers[:, None, :] + pts[None, j, :]).reshape(-1, 2)
                    d, _ = ns.trees[b].query(q, distance_upper_bound=STAGE1_CAP_M, workers=-1)
                    D[:, j] = np.minimum(d, STAGE1_CAP_M).reshape(len(centers), len(j))
                score = np.sqrt((D ** 2).mean(axis=1))
                for ci in range(len(centers)):
                    rows.append((score[ci], ci, si, rot, mirror))
    rows.sort(key=lambda r: (round(r[0], 9), r[1], r[2], r[3], r[4]))
    per_center, order = {}, []
    for sc, ci, si, rot, mirror in rows:
        got = per_center.setdefault(ci, [])
        if not got:
            order.append(ci)
        if len(got) < PER_CENTER:
            got.append({"ci": ci, "cx": float(centers[ci][0]), "cy": float(centers[ci][1]), "scale": T.scales[si],
                        "rot": rot, "mirror": mirror, "s1": float(sc)})
    return [c for ci in order[:TOP_CENTERS] for c in per_center[ci]]


def clean_route(path, protected, G):
    """경유점을 잇다 생긴 군더더기 정리 — 바로 되돌아가는 가시(a→b→a)와 짧은 고리.
    protected(뾰족한 꼭짓점 · 가지 끝 경유점)를 지나는 것은 그림의 일부라 남긴다."""
    xs, ys = G.x_list, G.y_list
    for _ in range(4):
        changed = False
        st = []
        for x in path:
            if len(st) >= 2 and st[-2] == x and st[-1] not in protected:
                st.pop()
                changed = True
            else:
                st.append(x)
        out, cum, pos = [], [], {}
        for x in st:
            j = pos.get(x)
            if j is not None and cum[-1] - cum[j] < CYCLE_MAX_M and not any(n in protected for n in out[j + 1:]):
                for n in out[j + 1:]:
                    if pos.get(n, -1) > j:
                        del pos[n]
                del out[j + 1:]
                del cum[j + 1:]
                changed = True
                continue
            if out:
                p = out[-1]
                cum.append(cum[-1] + math.hypot(xs[x] - xs[p], ys[x] - ys[p]))
            else:
                cum.append(0.0)
            out.append(x)
            pos[x] = len(out) - 1
        path = out
        if not changed:
            break
    return path


def sym_mean_distance(A, B, closed_a, probe=None):
    """폴리라인 A(그림, 닫힘) ↔ B(경로) 대칭 평균 거리(m) — 양쪽을 20m 간격으로 찍어 상대 폴리라인(5m 간격 점)까지.
    probe(점들)를 주면 그 점들에서 B 까지 거리도 함께 돌려준다(꼭짓점 확인용)."""
    a20, a5 = resample_polyline(A, FIDELITY_STEP_M, closed_a), resample_polyline(A, 5.0, closed_a)
    b20, b5 = resample_polyline(B, FIDELITY_STEP_M, False), resample_polyline(B, 5.0, False)
    tree_b = cKDTree(b5)
    d_ab = tree_b.query(a20)[0].mean()
    d_ba = cKDTree(a5).query(b20)[0].mean()
    fid = float((d_ab + d_ba) / 2)
    if probe is None:
        return fid
    return fid, tree_b.query(np.asarray(probe, float))[0]


def filled_region(coords):
    """닫힌 선(가지 포함)이 둘러싼 면 — 선을 교차점에서 쪼개 만든 면들의 합. 가지(나갔다 돌아옴)는 면을 만들지 않는다."""
    c = np.asarray(coords, float)
    if len(c) < 3:
        return None
    if not np.allclose(c[0], c[-1]):
        c = np.vstack([c, c[:1]])
    faces = list(polygonize(unary_union(LineString(c))))
    return unary_union(faces) if faces else None


def area_iou(region_a, coords_b):
    b = filled_region(coords_b)
    if region_a is None or b is None or b.area <= 0:
        return 0.0
    inter = region_a.intersection(b).area
    return float(inter / (region_a.area + b.area - inter))


def majority_dong(G, e):
    """경로 길이가 가장 많이 놓인 동(간선의 u 노드 동 기준)."""
    if not len(e):
        return ""
    s = np.bincount(G.dong_code[G.u[e]], weights=G.length[e], minlength=len(G.dong_names))
    return str(G.dong_names[int(np.argmax(s))])


def course_stats(G, nodes):
    e = G.edge_ids(nodes)
    L = G.length[e]
    total = float(L.sum())
    cnt = np.bincount(e, minlength=G.m) if len(e) else np.zeros(G.m, int)
    reused = float(((cnt[cnt > 1] - 1) * G.length[cnt > 1]).sum())
    return {"edges": e, "length_m": total,
            "car_free_pct": float(L[G.car_free[e]].sum() / total * 100) if total else 0.0,
            "major_pct": float(L[G.major[e]].sum() / total * 100) if total else 0.0,
            "reused_m": reused, "dong": majority_dong(G, e)}


def evaluate(T, G, cand):
    """2단계 — 자리 하나를 실제 보행망 경로로 그려 점수를 매긴다."""
    P = T.place(cand["cx"], cand["cy"], cand["scale"], cand["rot"], cand["mirror"])
    wp, is_key = resample_with_keys(P, T.key_idx, WAYPOINT_M)
    _, snap = G.tree.query(wp)
    seq, keyset = [], set()
    for node, k in zip(snap.tolist(), is_key.tolist()):
        if not seq or seq[-1] != node:
            seq.append(node)
        if k:
            keyset.add(node)
    if len(seq) > 1 and seq[-1] == seq[0]:
        seq.pop()
    if len(seq) < 3:
        return None
    # 그림 둘레(+LOCAL_MARGIN_M)의 부분 그래프에서만 찾는다 — 전체 34k 노드보다 몇 배 빠르다
    lo, hi = P.min(0) - LOCAL_MARGIN_M, P.max(0) + LOCAL_MARGIN_M
    inside = (G.xy[:, 0] >= lo[0]) & (G.xy[:, 0] <= hi[0]) & (G.xy[:, 1] >= lo[1]) & (G.xy[:, 1] <= hi[1])
    loc = np.flatnonzero(inside)
    eids = np.flatnonzero(inside[G.u] & inside[G.v])
    remap = np.full(G.n, -1, np.int64)
    remap[loc] = np.arange(len(loc))
    seq_l = remap[np.asarray(seq)]
    if (seq_l < 0).any():
        return None
    tt = cKDTree(resample_polyline(P, 5.0, closed=True))
    d_node = np.minimum(tt.query(G.xy[loc], distance_upper_bound=PROX_CAP_M)[0], PROX_CAP_M)
    d_mid = np.minimum(tt.query(G.mid[eids], distance_upper_bound=PROX_CAP_M)[0], PROX_CAP_M)
    ul, vl = remap[G.u[eids]], remap[G.v[eids]]
    w = G.base_cost[eids] * (1.0 + ((d_node[ul] + 2 * d_mid + d_node[vl]) / 4 / PROX_D0_M) ** 2)
    M = csr_matrix((np.r_[w, w], (np.r_[ul, vl], np.r_[vl, ul])), shape=(len(loc), len(loc)))
    # 경유점마다 다음 경유점까지 — 출발점을 한꺼번에 넘겨 dijkstra 한 번(limit = 가장 먼 이웃 쌍 기준)
    nxt = np.r_[seq_l[1:], seq_l[:1]]
    crow = np.hypot(*(G.xy[loc[seq_l]] - G.xy[loc[nxt]]).T)
    src, row = np.unique(seq_l, return_inverse=True)
    dist, pred = dijkstra(M, directed=True, indices=src, return_predecessors=True,
                          limit=8.0 * float(crow.max()) + 600.0)
    path_l = [int(seq_l[0])]
    for a, b, r in zip(seq_l.tolist(), nxt.tolist(), row.tolist()):
        if np.isfinite(dist[r, b]):
            p = [b]
            while p[-1] != a:
                p.append(int(pred[r, p[-1]]))
            path_l.extend(p[-2::-1])
        else:                                                   # limit 밖 — 그 쌍만 제한 없이 다시
            p = shortest_path(M, a, b)
            if p is None:
                return None
            path_l.extend(p[1:])
    path = clean_route(loc[np.asarray(path_l)].tolist(), keyset, G)
    if len(path) < 4:
        return None
    st = course_stats(G, path)
    fid, d_key = sym_mean_distance(P, G.xy[path], closed_a=True, probe=P[T.key_idx] if len(T.key_idx) else P[:1])
    key_rms = float(np.sqrt(np.mean(d_key ** 2)))
    iou = area_iou(T.region(cand["cx"], cand["cy"], cand["scale"], cand["rot"], cand["mirror"]), G.xy[path])
    perim_m = T.perimeter * cand["scale"]
    ratio = st["length_m"] / perim_m
    allowed = 1.3 * T.retrace * cand["scale"] + 0.03 * st["length_m"]
    excess = max(0.0, st["reused_m"] - allowed) / st["length_m"]
    km = st["length_m"] / 1000.0
    out_of_range = max(0.0, RANGE_KM[0] - km) + max(0.0, km - RANGE_KM[1])
    size = T.scale_ref / cand["scale"]                      # 큰 그림일수록 같은 m 오차가 덜 보인다
    score = ((fid + KEY_WEIGHT * max(0.0, key_rms - KEY_FREE_M)) * size + IOU_WEIGHT_M * (1.0 - iou)
             + LEN_PENALTY_M * max(0.0, ratio - LEN_RATIO_MAX)
             + REUSE_PENALTY_M * excess + RANGE_PENALTY_M * out_of_range)
    return {**cand, "outline": P, "nodes": path, "fidelity_m": fid, "key_rms": key_rms, "iou": iou, "ratio": ratio,
            "excess_reuse": excess, "score": float(score), **st}


def polish(T, G, r):
    """패턴 탐색 — 이동 · 회전 · 크기를 한 칸씩 바꿔 보고 가장 나은 쪽으로. 나아지지 않으면 칸을 반으로."""
    best = r
    dxy, drot, dsc = POLISH_STEP
    lo, hi = T.scale_ref * SCALE_LIMIT[0], T.scale_ref * SCALE_LIMIT[1]
    for _ in range(POLISH_ROUNDS):
        trial = []
        for dx, dy, dr, fs in ((dxy, 0, 0, 1), (-dxy, 0, 0, 1), (0, dxy, 0, 1), (0, -dxy, 0, 1),
                               (0, 0, drot, 1), (0, 0, -drot, 1), (0, 0, 0, 1 + dsc), (0, 0, 0, 1 - dsc)):
            rot = best["rot"] + dr
            scale = best["scale"] * fs
            if abs(rot) > T.rot_limit + 1e-9 or not lo <= scale <= hi:
                continue
            c = {"ci": best["ci"], "cx": best["cx"] + dx, "cy": best["cy"] + dy, "scale": scale, "rot": rot,
                 "mirror": best["mirror"], "s1": best["s1"]}
            e = evaluate(T, G, c)
            if e is not None:
                trial.append(e)
        b = min(trial, key=lambda e: e["score"]) if trial else None
        if b is not None and b["score"] < best["score"] - 0.05:
            best = b
        else:
            dxy, drot, dsc = dxy / 2, drot / 2, dsc / 2
            if dxy < 15:
                break
    return best


def search_shape(T, G, ns, centers):
    """그림 하나 — 1단계 후보 → 2단계 경로 → 상위 POLISH_N 개 다듬기. 자리별 최선만 남긴 목록(점수순)."""
    evals = [r for r in (evaluate(T, G, c) for c in stage1(T, ns, centers)) if r is not None]
    evals.sort(key=lambda r: r["score"])
    starts = []
    for r in evals:
        if all(math.hypot(r["cx"] - s["cx"], r["cy"] - s["cy"]) >= 2 * GRID_M for s in starts):
            starts.append(r)
            if len(starts) >= POLISH_N:
                break
    pool = evals + [polish(T, G, r) for r in starts]
    pool.sort(key=lambda r: r["score"])
    kept = []
    for r in pool:
        if all(math.hypot(r["cx"] - k["cx"], r["cy"] - k["cy"]) >= 150 for k in kept):
            kept.append(r)
            if len(kept) >= SPREAD_POOL:
                break
    return kept


def option_regions(T, opts):
    """자리마다 그림이 차지하는 면 — 10m 로 단순화하고 OVERLAP_GAP_M 의 반만큼 키운다(두 그림이 그만큼 떨어져야 안 겹침)."""
    return np.array([T.region(r["cx"], r["cy"], r["scale"], r["rot"], r["mirror"]).simplify(10.0)
                     .buffer(OVERLAP_GAP_M / 2) for r in opts], dtype=object)


def penalty_matrix(A, B, ga, gb):
    """코스 자리 목록 A × B 의 겹침 벌점 — 두 그림 면이 겹친 넓이 ÷ 작은 면 넓이 × 40m + 같은 동이면 4m.
    상자나 외접원으로 재면 길쭉하거나 가는 그림(공룡 · 갈매기)이 실제로는 안 겹치는 이웃까지 밀어내서 면으로 잰다.
    경계 상자가 겹치는 쌍만 면 교차를 계산한다."""
    ba, bb = shapely.bounds(ga), shapely.bounds(gb)
    w = np.minimum(ba[:, None, 2], bb[None, :, 2]) - np.maximum(ba[:, None, 0], bb[None, :, 0])
    h = np.minimum(ba[:, None, 3], bb[None, :, 3]) - np.maximum(ba[:, None, 1], bb[None, :, 1])
    frac = np.zeros((len(A), len(B)))
    ii, jj = np.nonzero((w > 0) & (h > 0))
    if len(ii):
        inter = shapely.area(shapely.intersection(ga[ii], gb[jj]))
        frac[ii, jj] = inter / np.minimum(shapely.area(ga)[ii], shapely.area(gb)[jj])
    same = np.array([r["dong"] for r in A])[:, None] == np.array([r["dong"] for r in B])[None, :]
    return OVERLAP_PENALTY_M * frac + SAME_DONG_PENALTY_M * same


def choose_spread(results, templates):
    """그림마다 자리 하나 — (각 코스 점수의 합 + 코스 쌍마다 겹침 벌점의 합)이 가장 작도록 고른다.

    좋은 자리는 촘촘한 몇 동네(이동 · 사동 · 본오1동 · 사이동 · 와동)에 몰려 있어 여러 그림이 같은 곳을 원한다.
    먼저 고른 그림이 좋은 자리를 차지하면 나중 그림이 크게 밀리므로, 그림마다 상위 SPREAD_OPTIONS 곳의
    벌점 행렬을 미리 만들고 ① 한 그림씩 다시 고르기 ② 두 그림을 함께 다시 고르기를 나아지지 않을 때까지 되풀이한다.
    시작안은 '차례로 고르기' · '모두 자기 최고 자리' · 고정 시드 무작위 SPREAD_RESTARTS 개 — 합이 가장 작은 답을 쓴다."""
    keys = [k for k in results if results[k]]
    opts = {k: results[k][:SPREAD_OPTIONS] for k in keys}
    score = {}
    for k in keys:                                              # 자기 최고 자리보다 REGRET_FREE 넘게 나빠지면 제곱으로 더 친다
        s = np.array([r["score"] for r in opts[k]])            # — 한 그림만 크게 망가지는 답보다 여럿이 조금씩 양보하는 답
        score[k] = s + REGRET_WEIGHT * np.clip(s - s.min() - REGRET_FREE, 0, None) ** 2
    regions = {k: option_regions(templates[k], opts[k]) for k in keys}
    pen = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            m = penalty_matrix(opts[a], opts[b], regions[a], regions[b])
            pen[a, b], pen[b, a] = m, m.T

    def total(ch):
        return float(sum(score[k][ch[k]] for k in keys)
                     + sum(pen[a, b][ch[a], ch[b]] for i, a in enumerate(keys) for b in keys[i + 1:]))

    def side(k, ch, skip=None):
        """그림 k 의 자리별 비용 = 점수 + (skip 을 뺀) 다른 그림들과의 벌점."""
        return score[k] + sum(pen[k, j][:, ch[j]] for j in keys if j != k and j != skip)

    def improve(ch):
        for _ in range(50):
            changed = False
            for k in keys:
                c = side(k, ch)
                i = int(np.argmin(c))
                if c[i] < c[ch[k]] - 1e-9:
                    ch[k], changed = i, True
            for x, a in enumerate(keys):
                for b in keys[x + 1:]:
                    M = side(a, ch, skip=b)[:, None] + side(b, ch, skip=a)[None, :] + pen[a, b]
                    i, j = np.unravel_index(int(np.argmin(M)), M.shape)
                    if M[i, j] < M[ch[a], ch[b]] - 1e-9:
                        ch[a], ch[b], changed = int(i), int(j), True
            if not changed:
                break
        return ch

    greedy, left = {}, list(keys)
    while left:
        best = None
        for k in left:
            c = score[k] + sum(pen[k, j][:, greedy[j]] for j in greedy)
            i = int(np.argmin(c))
            if best is None or c[i] < best[0] - 1e-9:
                best = (float(c[i]), k, i)
        greedy[best[1]] = best[2]
        left.remove(best[1])
    rng = np.random.default_rng(SPREAD_SEED)
    starts = [greedy, {k: 0 for k in keys}]
    starts += [{k: int(rng.integers(len(opts[k]))) for k in keys} for _ in range(SPREAD_RESTARTS)]
    best = min((improve(dict(s)) for s in starts), key=total)
    return {k: opts[k][best[k]] for k in keys}


def drawing_runs(G, t0):
    ns = NetSamples(G)
    centers = ns.dense_centers(G)
    log(f"  보행망 표본 {len(ns.xy):,}점 · 후보 중심 {len(centers):,}곳 (밀도 {DENSE_MIN_KM_PER_KM2:g}km/km² 이상)"
        f"  [{time.time() - t0:.0f}s]")
    templates = [Template(*spec) for spec in SHAPE_SPECS]
    results = {}
    for T in templates:
        t1 = time.time()
        evals = search_shape(T, G, ns, centers)
        results[T.key] = evals
        b = evals[0] if evals else None
        log(f"  {T.name:6s} 자리 {len(evals)} · 최고 점수 {b['score']:.1f} "
            f"(충실도 {b['fidelity_m']:.1f}m · {b['length_m'] / 1000:.2f}km · {b['dong']})  {time.time() - t1:.1f}s"
            if b else f"  {T.name} 경로 없음")
    chosen = choose_spread(results, {T.key: T for T in templates})
    return templates, chosen, results


# ══ 차 없는 길 ═════════════════════════════════════════════════════════
def edge_way_names(G):
    """간선별 OSM way 이름 — public_data.edge_road 와 같은 좌표 반올림으로 way 를 간선에 다시 붙인다."""
    src = RAW / "ansan_walk.geojson"
    if not src.exists():
        return None
    try:
        import geopandas as gpd
        sys.path.insert(0, str(ROOT / "src"))
        import osm
        import params as PM
        dong = gpd.read_file(PROC / "dong.geojson").to_crs(5179)[["ADM_NM", "geometry"]]
        ways = osm.load_ways(src, dong, log=lambda m: None)
        snap = PM.SNAP_M.value
    except Exception as exc:                                  # 이름은 없어도 코스는 만든다
        log(f"  way 이름을 못 붙였다 — 동 이름으로 대신 ({exc})")
        return None
    if "name" not in ways.columns:
        return None
    best = {}
    for geom, nm in zip(ways.geometry.values, ways["name"].to_numpy()):
        if not isinstance(nm, str) or not nm.strip():
            continue
        c = np.round(np.asarray(geom.coords)[:, :2] / snap).astype(np.int64)
        for (ax, ay), (bx, by) in zip(c[:-1], c[1:]):
            if ax != bx or ay != by:
                best.setdefault((min((ax, ay), (bx, by)), max((ax, ay), (bx, by))), nm.strip())
    q = np.round(G.xy / snap).astype(np.int64)
    out = np.full(G.m, "", dtype=object)
    for i, (a, b) in enumerate(zip(G.u, G.v)):
        ka, kb = tuple(q[a]), tuple(q[b])
        out[i] = best.get((min(ka, kb), max(ka, kb)), "")
    return out


def seeds_far_apart(xy, spacing, max_n):
    """먼 점 고르기 — 첫 점은 x 가 가장 작은 노드, 이후 기존 씨앗에서 가장 먼 노드(간격 spacing 이상)."""
    first = int(np.lexsort((xy[:, 1], xy[:, 0]))[0])
    picked = [first]
    dmin = np.hypot(*(xy - xy[first]).T)
    while len(picked) < max_n:
        j = int(np.argmax(dmin))
        if dmin[j] < spacing:
            break
        picked.append(j)
        dmin = np.minimum(dmin, np.hypot(*(xy - xy[j]).T))
    return picked


def carfree_courses(G, names):
    L = G.length
    cf_idx = np.flatnonzero(G.car_free)
    A = coo_matrix((L[cf_idx], (G.u[cf_idx], G.v[cf_idx])), shape=(G.n, G.n)).tocsr()
    A = (A + A.T).tocsr()
    _, lab = connected_components(A, directed=False)
    on_cf = np.zeros(G.n, bool)
    on_cf[G.u[cf_idx]] = on_cf[G.v[cf_idx]] = True
    comp_len = pd.Series(L[cf_idx]).groupby(lab[G.u[cf_idx]]).sum()
    comps = comp_len[comp_len >= CF_COMP_MIN_M].sort_values(ascending=False, kind="stable")
    w = L * np.where(G.car_free, 1.0, NONCF_COST) * (1.0 + MAJOR_COST * G.major)
    M = G.matrix(w)
    cands = []
    for c, clen in comps.items():
        members = np.flatnonzero((lab == c) & on_cf)
        n_seed = int(min(6, max(1, clen // 4000 + 1)))
        for si in seeds_far_apart(G.xy[members], CF_SEED_SPACING_M, n_seed):
            a = int(members[si])
            d_cf = dijkstra(A, directed=False, indices=a, limit=max(CF_TARGETS_M) * 1.6)
            d_in = np.where(lab == c, d_cf, np.inf)
            tried = set()
            for target in CF_TARGETS_M:
                ok = np.isfinite(d_in)
                if not ok.any():
                    break
                b = int(np.flatnonzero(ok)[np.argmin(np.abs(d_in[ok] - target))])
                if b == a or b in tried or d_in[b] < 500:
                    continue
                tried.add(b)
                course = make_loop(G, M, w, a, b)
                if course is None:
                    continue
                st = course_stats(G, course["nodes"])
                if not (CF_MIN_M <= st["length_m"] <= CF_MAX_M) or st["car_free_pct"] < CF_SHARE_MIN * 100:
                    continue
                q = st["car_free_pct"] / 100 + (0.25 if course["loop"] else 0.0) \
                    - 0.08 * abs(st["length_m"] - 5000) / 1000 - 0.3 * st["major_pct"] / 100
                cands.append({**course, **st, "quality": float(q), "comp": int(c)})
    cands.sort(key=lambda r: (-r["quality"], r["nodes"][0]))
    for r in cands:
        r["center"] = G.xy[r["nodes"]].mean(0)
        r["samples"] = resample_polyline(G.xy[r["nodes"]], 25.0, closed=False)
        r["tree"] = cKDTree(r["samples"])
    picked = []
    while len(picked) < CF_MAX_COURSES:
        best = None
        for r in cands:
            if any(r is o for o in picked) or sum(o["comp"] == r["comp"] for o in picked) >= CF_PER_COMPONENT:
                continue
            if any(near_duplicate(r, o) for o in picked):
                continue
            adj = r["quality"] - CF_SAME_DONG_PENALTY * sum(o["dong"] == r["dong"] for o in picked)
            if best is None or adj > best[0] + 1e-12:
                best = (adj, r)
        if best is None:
            break
        picked.append(best[1])
    if len(picked) < CF_MIN_COURSES:
        log(f"  [!] 차 없는 길 코스가 {len(picked)}개뿐 (최소 {CF_MIN_COURSES})")
    used = {}
    for r in picked:
        r["name"] = carfree_name(G, r, names)
        used[r["name"]] = used.get(r["name"], 0) + 1
        if used[r["name"]] > 1:
            r["name"] = f"{r['name']} {used[r['name']]}"
    return picked


def near_duplicate(r, o):
    """두 코스가 거의 같은 길인가 — 어느 한쪽 길이의 CF_DUP_SHARE 이상이 다른 쪽에서 CF_DUP_M 안에 있으면.
    간선이 달라도 개천 양쪽 둑길처럼 나란히 가는 코스를 같은 코스로 본다."""
    if math.hypot(*(r["center"] - o["center"])) < 400:
        return True
    near_r = (o["tree"].query(r["samples"])[0] <= CF_DUP_M).mean()
    near_o = (r["tree"].query(o["samples"])[0] <= CF_DUP_M).mean()
    return max(near_r, near_o) >= CF_DUP_SHARE


def make_loop(G, M, w, a, b):
    """a → b 두 길(두 번째는 첫 길 간선을 40배로 쳐서 비켜 감) → 한 바퀴. 많이 겹치면 첫 길로 왕복."""
    p1 = shortest_path(M, a, b)
    if p1 is None or len(p1) < 2:
        return None
    e1 = G.edge_ids(p1)
    w2 = w.copy()
    w2[e1] *= 40.0
    p2 = shortest_path(G.matrix(w2), a, b)
    if p2 is not None:
        e2 = G.edge_ids(p2)
        shared = G.length[np.intersect1d(e1, e2)].sum() / G.length[e1].sum()
        if shared <= CF_DISJOINT_MAX:
            loop_nodes = p1 + p2[::-1][1:]
            st = course_stats(G, loop_nodes)
            if st["length_m"] <= CF_MAX_M and st["car_free_pct"] >= CF_SHARE_MIN * 100:
                return {"nodes": loop_nodes, "loop": True}
    return {"nodes": p1 + p1[::-1][1:], "loop": False}


def carfree_name(G, r, names):
    e = r["edges"]
    if names is not None:
        m = G.car_free[e] & (names[e] != "")
        if m.any():
            s = pd.Series(G.length[e][m]).groupby(names[e][m]).sum().sort_values(ascending=False, kind="stable")
            if s.iloc[0] >= 0.2 * r["length_m"]:
                nm = str(s.index[0])
                return f"{r['dong']} {nm}" if nm in GENERIC_WAY_NAMES else nm
    return f"{r['dong']} 차 없는 길"


# ══ 출력 ═══════════════════════════════════════════════════════════════
def to_latlon(xy):
    from pyproj import Transformer
    tr = Transformer.from_crs(5179, 4326, always_xy=True)
    lon, lat = tr.transform(np.asarray(xy)[:, 0], np.asarray(xy)[:, 1])
    return np.c_[lat, lon]


def rounded(latlon):
    return [[round(float(a), 5), round(float(b), 5)] for a, b in latlon]


def template_points(P):
    """그림 외곽선(지도 좌표)을 15m 간격으로 찍고 직선 위 점은 줄인다 — 닫힌 선(처음 점을 끝에 한 번 더)."""
    pts = resample_polyline(P, 15.0, closed=True)
    pts = np.vstack([pts, pts[:1]])
    line = LineString(pts).simplify(1.5, preserve_topology=False)
    return np.asarray(line.coords)


def course_record(G, kind, cid, name, nodes, st, loop, extra=None):
    nodes = [int(x) for x in nodes]
    e = G.edge_ids(nodes)
    trail = float(G.length[e][np.isin(G.highway[e], TRAIL_CLASSES)].sum() / G.length[e].sum() * 100) if len(e) else 0.0
    rec = {"id": cid, "type": kind}
    if extra and "shape" in extra:
        rec["shape"] = extra.pop("shape")
    rec.update({"name": name, "length_m": int(round(st["length_m"])),
                "car_free_pct": round(st["car_free_pct"], 1), "major_pct": round(st["major_pct"], 1),
                "trail_pct": round(trail, 1), "dong": st["dong"], "loop": bool(loop),
                "start": rounded(G.latlon[nodes[:1]])[0],
                "path": rounded(G.latlon[nodes]), "nodes": nodes})
    if extra:
        rec.update(extra)
    return rec


def save_preview(G, rec, route_xy, outline_xy, out_png, subtitle):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.collections import LineCollection
    names = {f.name for f in font_manager.fontManager.ttflist}
    for fam in ("Malgun Gothic", "NanumGothic", "AppleGothic"):
        if fam in names:
            plt.rcParams["font.family"] = fam
            break
    plt.rcParams["axes.unicode_minus"] = False
    allp = route_xy if outline_xy is None else np.vstack([route_xy, outline_xy])
    lo, hi = allp.min(0), allp.max(0)
    c = (lo + hi) / 2
    half = (hi - lo).max() / 2 * 1.12 + 120
    x0, x1, y0, y1 = c[0] - half, c[0] + half, c[1] - half, c[1] + half
    m = ((G.mid[:, 0] > x0 - 300) & (G.mid[:, 0] < x1 + 300) & (G.mid[:, 1] > y0 - 300) & (G.mid[:, 1] < y1 + 300))
    segs = np.stack([G.xy[G.u[m]], G.xy[G.v[m]]], axis=1)
    cf, mj = G.car_free[m], G.major[m]
    fig = plt.figure(figsize=(8, 8), dpi=100)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.88])
    ax.add_collection(LineCollection(segs[~cf & ~mj], colors="#c9c9c9", linewidths=0.7, zorder=1))
    ax.add_collection(LineCollection(segs[mj], colors="#e3b8b0", linewidths=1.3, zorder=1))
    ax.add_collection(LineCollection(segs[cf], colors="#a9d3a0", linewidths=0.9, zorder=1))
    if outline_xy is not None:
        o = np.vstack([outline_xy, outline_xy[:1]])
        ax.plot(o[:, 0], o[:, 1], color="#1f5fbf", lw=1.6, ls=(0, (5, 3)), zorder=3, label="그림")
    ax.plot(route_xy[:, 0], route_xy[:, 1], color="#e4572e", lw=3.6, alpha=0.9, zorder=2,
            solid_capstyle="round", solid_joinstyle="round", label="코스")
    ax.plot(*route_xy[0], "o", ms=9, mfc="white", mec="#e4572e", mew=2.5, zorder=4, label="출발")
    bar = 500 if half > 700 else 200
    bx, by = x0 + 0.06 * (x1 - x0), y0 + 0.05 * (y1 - y0)
    ax.plot([bx, bx + bar], [by, by], color="#333", lw=3, zorder=5)
    ax.text(bx + bar / 2, by + 0.015 * (y1 - y0), f"{bar} m", ha="center", va="bottom", fontsize=10, color="#333")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.legend(loc="upper right", fontsize=9, frameon=True)
    fig.text(0.5, 0.955, f"{rec['name']} · {rec['length_m'] / 1000:.2f} km", ha="center", fontsize=17,
             weight="bold")
    fig.text(0.5, 0.918, subtitle, ha="center", fontsize=11, color="#444")
    fig.savefig(out_png)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description="드로잉 런 · 차 없는 길 코스 생성")
    ap.add_argument("--preview-dir", default=None, help="코스마다 미리보기 PNG 를 이 폴더에 (없으면 안 만든다)")
    ap.add_argument("--no-preview", action="store_true", help="미리보기를 만들지 않는다(--preview-dir 보다 우선)")
    args = ap.parse_args(argv)
    t0 = time.time()
    log("[1] 보행망 읽기")
    G = RunGraph()
    log(f"  노드 {G.n:,} · 간선 {G.m:,} · 차 없는 길 {G.length[G.car_free].sum() / 1000:.1f}km "
        f"/ 전체 {G.length.sum() / 1000:.1f}km")

    log("[2] 드로잉 런")
    templates, chosen, _ = drawing_runs(G, t0)
    tpl = {T.key: T for T in templates}

    log(f"[3] 차 없는 길  [{time.time() - t0:.0f}s]")
    names = edge_way_names(G)
    cf = carfree_courses(G, names)

    log(f"[4] 저장  [{time.time() - t0:.0f}s]")
    courses, previews = [], []
    for key, *_ in SHAPE_SPECS:
        r = chosen.get(key)
        if r is None:
            log(f"  [!] {key} 코스 없음")
            continue
        T = tpl[key]
        rec = course_record(G, "drawing", f"drawing-{key}", T.name, r["nodes"], r, True,
                            {"shape": key, "fidelity_m": round(r["fidelity_m"], 1),
                             "template": rounded(to_latlon(template_points(r["outline"])))})
        courses.append(rec)
        previews.append((rec, G.xy[r["nodes"]], r["outline"],
                         f"{rec['dong']} · 그림과 평균 {r['fidelity_m']:.0f} m 차이 · 차 없는 길 {rec['car_free_pct']:.0f}%"
                         f" · 큰길 {rec['major_pct']:.0f}%"))
    for i, r in enumerate(cf, 1):
        rec = course_record(G, "carfree", f"carfree-{i:02d}", r["name"], r["nodes"], r, r["loop"])
        courses.append(rec)
        previews.append((rec, G.xy[r["nodes"]], None,
                         f"{rec['dong']} · 차 없는 길 {rec['car_free_pct']:.0f}% · 큰길 {rec['major_pct']:.0f}%"
                         f" · {'한 바퀴' if r['loop'] else '왕복'}"))
    doc = {"built": datetime.date.today().isoformat(), "source": SOURCE_NOTE, "courses": courses}
    OUT_JSON.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"  {OUT_JSON} ({OUT_JSON.stat().st_size / 1024:.0f} KB · 코스 {len(courses)}개)")
    for c in courses:
        log(f"  {c['id']:18s} {c['name']:14s} {c['dong']:6s} {c['length_m']:5d}m 차없는길 {c['car_free_pct']:5.1f}%"
            f" 큰길 {c['major_pct']:5.1f}%" + (f" 충실도 {c['fidelity_m']:.1f}m" if "fidelity_m" in c else "")
            + f" loop={c['loop']}")
    if args.preview_dir and not args.no_preview:
        out = pathlib.Path(args.preview_dir)
        out.mkdir(parents=True, exist_ok=True)
        for rec, route_xy, outline_xy, sub in previews:
            save_preview(G, rec, route_xy, outline_xy, out / f"{rec['id']}.png", sub)
        log(f"  미리보기 {len(previews)}장 → {out}")
    log(f"끝 — {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
