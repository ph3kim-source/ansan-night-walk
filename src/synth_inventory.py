# -*- coding: utf-8 -*-
"""
임의값 인벤토리 생성기 — 실데이터가 오기 전에 시연 프로토타입을 돌리기 위한 '가짜 납품분'

실행:  python src/synth_inventory.py
출력:  data/synthetic/raw/     인벤토리 실측 파일명 · 컬럼명 · 코드값 · cp949 그대로
       data/synthetic/latent/  가상 세계의 정답(가게별 영업시간 등) — 적재 코드 검증용

★ 값은 전부 임의값이다 (params.SYNTH_DATA, C등급). 화면·보고서에 인용하지 않는다.

왜 '가상 세계 하나'에서 만드는가
--------------------------------
데이터셋마다 따로 난수를 뽑으면 서로 앞뒤가 안 맞는다(DS-054 에선 편의점이 열려 있는데
DS-014 에선 그 동에 사람이 없는 식). 그래서 실데이터 뼈대 위에 가상의 안산 하나를 만들고,
각 데이터셋은 그 세계를 자기 규격으로 관측한 결과로 만든다.

  실데이터 뼈대                              가상 세계 (임의 가정)
  ──────────────────────────────            ─────────────────────────────
  SGIS 1km 인구 · OSM 주거건물 28,268동      100m 셀 거주인구
  소상공인 상가 34,489곳 위치·업종            가게별 인기도 · 영업시간 · 시간대별 결제
  행안부 동별 내·외국인 · SGIS 동별 종사자     시간대별 재택률 · 출근률 · 이동수단 비중
  OSM 보행망                                 보안등 · CCTV 위치

  → DS-082 · DS-054 · DS-048 · DS-014 · DS-008 · DS-004 · DS-001 + 보안등 · CCTV + 카드 블록 좌표

실물과 다르게 줄인 곳 (data/synthetic/README.md 에 같은 내용)
  - DS-054 · DS-008 은 21~02시만 만든다(실물 00~23시). 앞뒤 21·02시는 심야 절단 시험용이다
  - DS-004 는 7일, DS-001 은 14일치만 만든다(실물 한 달)
  - DS-082 108컬럼 중 3안이 쓰는 몇 개만 값이 있고 나머지는 0, 인구 0 인 행은 뺐다
  - 큰 파일은 .csv.gz (실물도 일부 .csv.gz 로 납품됨 — 인벤토리 09_파일목록 DS-002·003)
"""
import datetime as dt
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
OUT = ROOT / "data" / "synthetic" / "raw"
LATENT = ROOT / "data" / "synthetic" / "latent"
BASE = ROOT / "data" / "base"          # 기초 데이터 (실데이터 뼈대)
sys.path.insert(0, str(ROOT / "src"))
import params as PM

MONTH = PM.SYNTH_MONTH.value
YEAR, MON = int(MONTH[:4]), int(MONTH[4:])
DAYS = pd.date_range(f"{YEAR}-{MON:02d}-01", periods=pd.Period(MONTH, "M").days_in_month, freq="D")
HOURS = [21, 22, 23, 0, 1, 2]                 # DS-054·008 을 만드는 시각. 22~01 이 심야, 21·02 는 절단 시험용
DOW_KR = "월화수목금토일"
RNG = np.random.default_rng(PM.SYNTH_SEED.value)

# ── 가상 세계의 가정값 (전부 임의. 서비스 파라미터가 아니라 '가짜 안산'의 설정이다) ──────────────
# 밤 기준 요일 계수 — 금·토 밤에 사람이 많다
NIGHT_DOW = np.array([0.90, 0.92, 0.95, 1.00, 1.30, 1.35, 0.85])
# 시간대별 재택률(0~23시) · 출근률 — 유동인구(DS-014)의 뼈대
HOME = np.array([.93, .95, .96, .96, .95, .92, .85, .70, .55, .48, .45, .45,
                 .45, .45, .46, .48, .52, .58, .66, .74, .80, .85, .88, .91])
WORK = np.array([.06, .06, .05, .05, .06, .10, .25, .60, .95, 1, 1, 1,
                 .90, 1, 1, 1, .95, .80, .50, .30, .20, .14, .10, .08])
# 가게 무리별: 시간당 결제 기대값(인기도 1 기준) · 0~23시 수요 곡선 · 건당 금액 · 주변 사람 수
GROUP = {
    #            base  ticket  people
    "cvs":      (2.2,  6800,   4),
    "gas":      (1.5,  52000,  2),
    "pc":       (0.9,  4500,   12),
    "nightlife": (1.1, 48000,  15),
    "late_food": (1.4, 27000,  10),
    "food":     (1.6,  18000,  12),
    "retail":   (1.2,  15000,  6),
    "lodging":  (0.4,  45000,  8),
}
PROFILE = {   # 0~23시 수요 (영업 중일 때). 낮 시간은 DS-014 동 단위 방문객에만 쓰인다
    "cvs":       [.50, .35, .25, .20, .20, .30, .50, .80, .90, .80, .80, .90, 1, .90, .80, .80, .90, 1, 1, 1, 1, .95, .85, .70],
    "gas":       [.30, .20, .15, .15, .20, .40, .70, .90, 1, .90, .80, .80, .80, .80, .80, .90, 1, 1, 1, .90, 1, .80, .60, .45],
    "pc":        [.90, .75, .55, .45, .30, .20, .10, .10, .15, .20, .30, .40, .50, .60, .70, .80, .80, .80, .80, .85, .90, 1, 1, 1],
    "nightlife": [.90, .70, .45, .25, .10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, .05, .10, .20, .30, .40, .70, .95, 1],
    "late_food": [.45, .30, .20, .10, .05, 0, 0, 0, 0, 0, .10, .40, .70, .40, .30, .30, .40, .60, .90, 1, 1, .90, .75, .60],
    "food":      [0, 0, 0, 0, 0, 0, .05, .10, .20, .20, .30, .80, 1, .70, .40, .30, .40, .70, 1, .90, .70, .60, .25, 0],
    "retail":    [0, 0, 0, 0, 0, 0, 0, .05, .20, .40, .60, .70, .80, .80, .80, .80, .90, 1, 1, 1, 1, .70, .45, .25],
    "lodging":   [.80, .60, .40, .20, .10, .10, .10, .05, .05, .05, .05, .10, .10, .10, .10, .20, .30, .40, .50, .60, 1, .90, .90, .80],
}
# 늦게까지 여는 음식점의 소분류별 비율 (나머지는 21~22시에 닫는다)
LATE_FOOD = {"치킨": .60, "곱창 전골/구이": .50, "돼지고기 구이/찜": .40, "족발/보쌈": .40,
             "국/탕/찌개류": .25, "해산물 구이/찜": .30, "횟집": .30, "베트남식 전문": .25,
             "마라탕/훠궈": .20, "피자": .25, "버거": .20, "김밥/만두/분식": .15, "중국집": .10,
             "카페": .10, "기타 동남아식 전문": .25}
# DS-014 연령 비율 (10~74세 13칸) — 주민 · 밤 방문객 · 종사자
AGE_RES = np.array([.045, .045, .06, .07, .07, .07, .075, .08, .085, .085, .08, .06, .04])
AGE_VIS = np.array([.01, .04, .14, .16, .14, .12, .11, .09, .08, .05, .03, .015, .005])
AGE_WRK = np.array([0, .005, .07, .12, .13, .12, .12, .11, .11, .10, .07, .03, .01])
MALE = {"res": .51, "vis": .58, "wrk": .64}


def log(m):
    print(m, flush=True)


# ══ 카드 업종 체계 (임의) ════════════════════════════════════════════
# 실측 샘플 행(인벤토리 04): DS-054 'D11001 · 소매/유통 · 종합소매점 · 슈퍼마켓', DS-048 'F01 · 생활서비스 · …'
# → 코드 = 대분류 영문 1자 + 중분류 2자리 (+ 소분류 3자리). 분류명은 지어냈다(params.CARD_ANCHOR_NM3 need 참조)
NAMED = {   # 상가 소분류명 → (카드 소분류코드, 대분류, 중분류, 소분류, 가게 무리)
    "편의점": ("D11002", "소매/유통", "종합소매점", "편의점", "cvs"),
    "주유소": ("E05001", "자동차", "주유소/충전소", "주유소", "gas"),
    "PC방": ("H03001", "여가/오락", "게임/오락", "PC방", "pc"),
    "노래방": ("H03002", "여가/오락", "게임/오락", "노래방", "nightlife"),
    "요리 주점": ("A08001", "음식", "주점", "요리주점", "nightlife"),
    "일반 유흥 주점": ("A08002", "음식", "주점", "일반유흥주점", "nightlife"),
    "생맥주 전문": ("A08003", "음식", "주점", "호프/맥주", "nightlife"),
    "무도 유흥 주점": ("A08004", "음식", "주점", "무도유흥주점", "nightlife"),
}
MID = {     # 상가 (대분류, 중분류) → (카드 중분류코드, 대분류, 중분류)
    ("음식", "한식"): ("A01", "음식", "한식"), ("음식", "중식"): ("A02", "음식", "중식"),
    ("음식", "일식"): ("A03", "음식", "일식"), ("음식", "서양식"): ("A04", "음식", "서양식"),
    ("음식", "기타 간이"): ("A06", "음식", "분식/간이"), ("음식", "비알코올"): ("A07", "음식", "커피/음료"),
    ("음식", "구내식당·뷔페"): ("A09", "음식", "구내식당/뷔페"), ("음식", "동남아시아"): ("A10", "음식", "아시아음식"),
    ("음식", "주점"): ("A08", "음식", "주점"),
    ("소매", "종합 소매"): ("D11", "소매/유통", "종합소매점"), ("소매", "식료품 소매"): ("D03", "소매/유통", "식품"),
    ("소매", "섬유·의복·신발 소매"): ("D02", "소매/유통", "의류/잡화"), ("소매", "가전·통신 소매"): ("D01", "소매/유통", "가전제품"),
    ("소매", "연료 소매"): ("E05", "자동차", "주유소/충전소"),
    ("숙박", None): ("B01", "숙박", "숙박"), ("보건의료", None): ("C01", "의료", "병의원/약국"),
    ("교육", None): ("G01", "교육", "학원/교육"), ("수리·개인", None): ("F02", "생활서비스", "미용/세탁/수리"),
    ("예술·스포츠", None): ("H01", "여가/오락", "스포츠/여가"),
}
OTHER = ("I99", "기타", "기타")


def card_taxonomy(p):
    """상가 → 카드 업종(대·중·소분류 + 코드) + 가게 무리. 벡터화가 어려워 행 단위 매핑."""
    big = p["상권업종대분류명"].astype(str).str.strip()
    mid = p["상권업종중분류명"].astype(str).str.strip()
    sub = p["상권업종소분류명"].astype(str).str.strip()
    rows = []
    sub_code = {}
    for b, m, s in zip(big, mid, sub):
        if s in NAMED:
            cd, n1, n2, n3, grp = NAMED[s]
        else:
            c2, n1, n2 = MID.get((b, m), MID.get((b, None), OTHER))
            key = (c2, s)
            if key not in sub_code:
                sub_code[key] = f"{c2}{100 + len([k for k in sub_code if k[0] == c2]):03d}"
            cd, n3 = sub_code[key], s.replace(" ", "")
            if b == "음식":
                grp = "food"
            elif b == "소매" and m == "종합 소매":
                grp = "retail"
            elif b == "숙박":
                grp = "lodging"
            else:
                grp = "closed"                      # 밤에 결제가 없는 업종
        rows.append((cd, n1, n2, n3, grp))
    t = pd.DataFrame(rows, columns=["card_tpbuz_cd", "card_tpbuz_nm_1", "card_tpbuz_nm_2",
                                    "card_tpbuz_nm_3", "grp"], index=p.index)
    return t


# ══ 카드 블록 (임의 규칙 — params.CARD_BLOCK_XY C등급) ══════════════════
# 안산 위도에서 약 100m × 100m. 원점은 대부동 풍도(126.38°E, 37.11°N)까지 덮어야 한다 —
# 처음에 126.50·37.15 로 잡았다가 풍도 상가가 음수 행이 되어 5자리 코드(74103)가 나왔다
LON0, LAT0, DLON, DLAT = 126.30, 37.05, 0.00113, 0.0009


def block_of(lon, lat):
    col = np.floor((np.asarray(lon) - LON0) / DLON).astype(np.int64)
    row = np.floor((np.asarray(lat) - LAT0) / DLAT).astype(np.int64)
    return 100000 + row * 600 + col                          # 6자리 정수 — 실측 샘플(159533)과 같은 모양


def block_center(blk):
    k = np.asarray(blk, dtype=np.int64) - 100000
    row, col = k // 600, k % 600
    return LON0 + (col + .5) * DLON, LAT0 + (row + .5) * DLAT


# ══ 실데이터 뼈대 ════════════════════════════════════════════════════
def load_dongs():
    """25개 동(대부동 포함 — 실물 DS-014 도 25개 동). 행안부 코드는 data/base/admi_codes.csv
    (소상공인 상가정보 2026.06 의 행정동코드에서 뽑아 둔 25줄)."""
    g = gpd.read_file(BASE / "dong_sgis.geojson").to_crs(5179)
    s = pd.read_csv(BASE / "admi_codes.csv", dtype=str, encoding="utf-8-sig").set_index("행정동명")
    g["admi8"] = g["ADM_NM"].map(s["행정동코드"])
    g["sgg5"] = g["ADM_NM"].map(s["시군구코드"])
    g["sgg_nm"] = g["ADM_NM"].map(s["시군구명"])
    if g["admi8"].isna().any():
        raise SystemExit(f"[X] 행정동코드 매핑 실패: {g.loc[g.admi8.isna(), 'ADM_NM'].tolist()}")
    pt = g.geometry.representative_point()
    g["cx"], g["cy"] = pt.x.round().astype(int), pt.y.round().astype(int)
    g["area_km2"] = g.geometry.area / 1e6
    # 실데이터: 행안부 동별 내·외국인 (2026-02-20)
    f = BASE / "dong_pop_20260220.csv"
    try:
        q = pd.read_csv(f, encoding="cp949")
    except UnicodeDecodeError:
        q = pd.read_csv(f, encoding="utf-8-sig")
    q["ADM_NM"] = q["행정동명"].astype(str).str.replace(" ", "", regex=False)
    q = q.set_index("ADM_NM")
    g["pop"] = g["ADM_NM"].map(q["인구 전체"]).astype(float)
    g["forn"] = g["ADM_NM"].map(q["외국인 전체"]).astype(float)
    g["workers"] = g["전산업종사자"].astype(float)
    return g.reset_index(drop=True)


def load_cells_residents(dongs):
    """100m 셀 거주인구 — SGIS 1km 인구를 OSM 주거건물(세대수 > 층수 > 1)로 안분 + 임의 잡음."""
    c = pd.read_csv(PROC / "cells.csv", encoding="utf-8-sig")
    j = json.loads((BASE / "osm_homes.json").read_text(encoding="utf-8"))["elements"]
    h = pd.DataFrame([{"lon": e["center"]["lon"], "lat": e["center"]["lat"],
                       "flats": pd.to_numeric(e["tags"].get("building:flats"), errors="coerce"),
                       "lv": pd.to_numeric(e["tags"].get("building:levels"), errors="coerce")}
                      for e in j if "center" in e])
    gh = gpd.GeoDataFrame(h, geometry=gpd.points_from_xy(h.lon, h.lat), crs=4326).to_crs(5179)
    w = np.where(h.flats.notna(), h.flats, np.where(h.lv.notna(), h.lv, 1.0))
    d, i = cKDTree(c[["x", "y"]].to_numpy()).query(np.c_[gh.geometry.x, gh.geometry.y])
    ok = d <= 71                                                     # 셀 안 (반대각선 70.7m)
    home_w = np.bincount(i[ok], weights=w[ok], minlength=len(c))
    blk = c["cell_id"].str.split("_").str[0]
    tot = pd.Series(home_w).groupby(blk.values).transform("sum").to_numpy()
    pop1k = c["pop_night"].to_numpy() * 100
    r0 = np.where(tot > 0, pop1k * home_w / np.where(tot > 0, tot, 1), c["pop_night"].to_numpy())
    c["res"] = r0 * RNG.lognormal(0, .25, len(c))
    c["home_w"] = home_w
    fshare = dongs.set_index("ADM_NM").eval("forn / pop")
    c["forn_share"] = c["dong"].map(fshare).fillna(.05)
    log(f"    셀 {len(c):,} · 주거건물 {len(h):,}동(셀 매칭 {ok.sum():,}) · 거주 셀 {(c.res >= 1).sum():,}")
    return c


def load_shops(dongs):
    p = pd.read_csv(BASE / "poi.csv", encoding="utf-8-sig")
    p = p[p["행정동명"].isin(dongs["ADM_NM"])].reset_index(drop=True)
    g = gpd.GeoDataFrame(p, geometry=gpd.points_from_xy(p["경도"], p["위도"]), crs=4326).to_crs(5179)
    # 동 이름은 안산인데 좌표가 경계(+200m) 밖인 상가가 있으면 뺀다(있으면 보고). 2026.06 자료에는 없다
    inside = g.within(dongs.union_all().buffer(200)).to_numpy()
    if (~inside).any():
        log(f"    상가 좌표가 안산 경계 밖 {int((~inside).sum())}곳 제외 (동 이름은 안산)")
    p, g = p[inside].reset_index(drop=True), g[inside].reset_index(drop=True)
    t = card_taxonomy(p)
    p = pd.concat([p, t], axis=1)
    p["x"], p["y"] = g.geometry.x.to_numpy(), g.geometry.y.to_numpy()
    p["blk_cd"] = block_of(p["경도"], p["위도"])
    code = dongs.set_index("ADM_NM")
    p["admi8"] = p["행정동명"].map(code["admi8"])
    p["sgg5"] = p["행정동명"].map(code["sgg5"])
    n = len(p)
    # 가게별 잠재 속성 — 인기도 · 영업 종료 시각(24 이상 = 다음날 새벽) · 24시간 · 휴업(6개월 무실적)
    p["popularity"] = RNG.lognormal(0, .6, n)
    close = np.full(n, 22.0)
    grp = p["grp"].to_numpy()
    u = RNG.random(n)
    close[grp == "cvs"] = np.where(u[grp == "cvs"] < .88, 99, RNG.choice([24, 25], (grp == "cvs").sum()))
    close[grp == "gas"] = np.where(u[grp == "gas"] < .35, 99, RNG.choice([22, 23, 24], (grp == "gas").sum()))
    close[grp == "pc"] = np.where(u[grp == "pc"] < .90, 99, RNG.choice([25, 26], (grp == "pc").sum()))
    close[grp == "nightlife"] = RNG.choice([25, 26, 27, 28], (grp == "nightlife").sum(), p=[.25, .35, .25, .15])
    close[grp == "retail"] = RNG.choice([22, 23, 24], (grp == "retail").sum(), p=[.4, .4, .2])
    close[grp == "lodging"] = 99
    is_food = grp == "food"
    late_p = p["상권업종소분류명"].astype(str).str.strip().map(LATE_FOOD).fillna(.05).to_numpy()
    late = is_food & (u < late_p)
    p.loc[late, "grp"] = "late_food"
    close[late] = RNG.choice([24, 25, 26, 29], late.sum(), p=[.35, .3, .2, .15])
    close[is_food & ~late] = RNG.choice([21, 22, 23], (is_food & ~late).sum(), p=[.45, .45, .10])
    p["close_h"] = close                     # 99 = 24시간
    p["dead"] = (RNG.random(n) < .04) & (p["grp"] != "closed")
    log(f"    상가 {n:,} · 밤 영업 무리 " + " · ".join(
        f"{k} {int((p.grp == k).sum()):,}" for k in GROUP))
    return p


def is_open(close_h, hour):
    """hour 시(0~23)에 영업 중인가. close_h ≥ 24 는 다음날 새벽까지(99 = 24시간). 저녁 개점은 18시 이전으로 본다."""
    h = np.where(np.asarray(hour) < 12, np.asarray(hour) + 24, np.asarray(hour))
    return (close_h == 99) | (h < close_h)


# ══ DS-054 (블록 × 1시간 카드 결제, 비개방) ══════════════════════════════
def gen_ds054(p):
    s = p[p["grp"].isin(GROUP.keys()) & ~p["dead"]].reset_index(drop=True)
    recs = []
    for day in DAYS:
        for hour in HOURS:
            night = day - pd.Timedelta(days=1) if hour < 12 else day       # 밤 기준 요일
            dowf = NIGHT_DOW[night.weekday()]
            g = s["grp"].to_numpy()
            base = np.array([GROUP[x][0] for x in g])
            prof = np.array([PROFILE[x][hour] for x in g])
            lam = base * s["popularity"].to_numpy() * prof * dowf
            lam *= is_open(s["close_h"].to_numpy(), hour)
            lam *= RNG.random(len(s)) > .03                                 # 가끔 쉬는 날
            n = RNG.poisson(lam)
            k = n > 0
            if k.any():
                recs.append(pd.DataFrame({"ta_ymd": day.strftime("%Y%m%d"), "hour": f"{hour:02d}",
                                          "i": np.flatnonzero(k), "cnt": n[k]}))
    r = pd.concat(recs, ignore_index=True)
    r = r.join(s[["blk_cd", "admi8", "sgg5", "card_tpbuz_cd", "card_tpbuz_nm_1", "card_tpbuz_nm_2",
                  "card_tpbuz_nm_3", "grp"]], on="i")
    # 블록 × 업종(소분류) × 일 × 시로 묶는다 — 실물에는 가게 단위가 없다
    key = ["ta_ymd", "sgg5", "admi8", "blk_cd", "card_tpbuz_cd", "card_tpbuz_nm_1", "card_tpbuz_nm_2",
           "card_tpbuz_nm_3", "hour", "grp"]
    a = r.groupby(key, as_index=False, sort=False)["cnt"].sum()
    # 성·연령 행으로 쪼갠다 — 밤에는 건수가 적어 조합도 1~3개뿐. n 을 k 칸으로 순차 이항 분할
    n_all = a["cnt"].to_numpy()
    k = np.minimum(n_all, np.minimum(3, 1 + RNG.poisson(.6, len(a))))
    parts = np.zeros((len(a), 3), dtype=np.int64)
    remain = n_all.copy()
    for j in range(3):
        left = k - j                                                     # 남은 칸 수
        take = np.where(left == 1, remain,
                        np.where(left > 1, RNG.binomial(remain, 1.0 / np.maximum(left, 1)), 0))
        parts[:, j] = take
        remain = remain - take
    rep = a.loc[a.index.repeat(3)].reset_index(drop=True)
    rep["cnt"] = parts.reshape(-1)
    rep = rep[rep["cnt"] > 0].copy()
    rep["sex"] = np.where(RNG.random(len(rep)) < .6, "M", "F")
    rep["age"] = RNG.choice([f"{x:02d}" for x in range(4, 15)], len(rep),
                            p=np.array([.03, .12, .15, .14, .13, .12, .1, .08, .06, .04, .03]) / 1.0)
    # 같은 묶음 안에서 성·연령이 겹치면 합친다
    key2 = [c for c in key] + ["sex", "age"]
    rep = rep.groupby(key2, as_index=False, sort=False)["cnt"].sum()
    tick = rep["grp"].map({k_: v[1] for k_, v in GROUP.items()}).to_numpy()
    rep["amt"] = np.round(rep["cnt"] * tick * RNG.lognormal(0, .45, len(rep))).astype(np.int64)
    sale = RNG.choice(["A", "B", "C", "D", "신규", ""], len(rep), p=[.55, .22, .12, .05, .02, .04])
    rep["sale"] = sale                                                  # 빈칸 = null(30억 초과 또는 정보 없음)
    out_df = pd.DataFrame({
        "ta_ymd": rep["ta_ymd"], "cty_rgn_no": rep["sgg5"], "admi_cty_no": rep["admi8"],
        "blk_cd": rep["blk_cd"], "card_tpbuz_cd": rep["card_tpbuz_cd"],
        "card_tpbuz_nm_1": rep["card_tpbuz_nm_1"], "card_tpbuz_nm_2": rep["card_tpbuz_nm_2"],
        "card_tpbuz_nm_3": rep["card_tpbuz_nm_3"], "sale": rep["sale"], "hour": rep["hour"],
        "sex": rep["sex"], "age": rep["age"], "cnt": rep["cnt"], "amt": rep["amt"]})
    return out_df.sort_values(["ta_ymd", "hour", "blk_cd"]).reset_index(drop=True)


# ══ DS-048 (블록 가맹점 정보, 월별, 대민개방) ═════════════════════════════
def gen_ds048(p):
    n = len(p)
    grp = p["grp"].to_numpy()
    fran_p = np.select([grp == "cvs", grp == "pc", np.isin(grp, ["food", "late_food"])], [.92, .40, .25], .10)
    entp_p = np.select([grp == "gas", grp == "cvs"], [.50, .05], .08)
    tenure = RNG.choice(6, n, p=[.18, .15, .12, .10, .08, .37])
    months = np.array([6, 18, 30, 42, 54, 96])[tenure] + RNG.integers(-5, 6, n)
    d = pd.DataFrame({
        "ta_ym": MONTH, "cty_rgn_no": p["sgg5"], "admi_cty_no": p["admi8"], "blk_cd": p["blk_cd"],
        "card_tpbuz_cd": p["card_tpbuz_cd"].str[:3], "card_tpbuz_nm_1": p["card_tpbuz_nm_1"],
        "card_tpbuz_nm_2": p["card_tpbuz_nm_2"],
        "sale": RNG.choice(["A", "B", "C", "D", "신규", ""], n, p=[.55, .22, .12, .05, .02, .04]),
        "mm_cnt": np.maximum(months, 1), "entp_cnt": (RNG.random(n) < entp_p).astype(int)})
    d["mer_cnt"] = 1 - d["entp_cnt"]
    d["fran_cnt"] = (RNG.random(n) < fran_p).astype(int)
    d["open_cnt"] = (RNG.random(n) < .012).astype(int)
    d["stop_cnt"] = p["dead"].astype(int).to_numpy()                  # 최근 6개월 무실적 = 가상 세계의 휴업
    d["close_cnt"] = (RNG.random(n) < .006).astype(int)
    for j, c in enumerate(["open_11_cnt", "open_12_23_cnt", "open_24_35_cnt", "open_36_47_cnt",
                           "open_48_59_cnt", "open_60_cnt"]):
        d[c] = (tenure == j).astype(int)
    key = ["ta_ym", "cty_rgn_no", "admi_cty_no", "blk_cd", "card_tpbuz_cd", "card_tpbuz_nm_1",
           "card_tpbuz_nm_2", "sale"]
    return d.groupby(key, as_index=False, sort=False).sum(numeric_only=True)


# ══ DS-082 (100m 격자 거주 · 신용, 비개방, 민감도 최상) ══════════════════════
DS082_COLS = ['BS_YR_MON', 'CELL_100', 'TOT_REG_CD', 'hcd', 'GENDER', 'AGE', 'TOT_CNT', 'M_CNT', 'FM_CNT',
              'YES_INCOME', 'SELF_ENT', 'ETC_CNT', 'FOR_CNT', 'AVG_DIST', 'HIGH_CNT', 'AVG_INC', 'AVG_INC_1',
              'AVG_INC_2', 'AVG_INC_3', 'AVG_INC_4', 'AVG_INC_5', 'AVG_INC_6', 'AVG_INC_7', 'AVG_INC_8',
              'AVG_INC_9', 'AVG_INC_10', 'MED_INC', 'YES_HOUS_CNT', 'AVG_EVHOUS1', 'CAR_CNT', 'ABROCAR_CNT',
              'CAR_NEW_CNT', 'AVG_CAR', 'AVG_EC_CAR', 'CARD_OWN_CNT', 'CRED_OWN_CNT', 'AVG_CRED_OWN',
              'CHECK_OWN_CNT', 'AVG_CHECK_OWN', 'AVG_CARD', 'AVG_SELLING_CRED', 'AVG_CASH', 'AVG_LUMP',
              'AVG_INST', 'AVG_CRED', 'AVG_CHECK', 'AVG_CRED_ABRO', 'AVG_CASH_ABRO', 'DELQ_S_CNT',
              'DELQ_L_CNT', 'LOAN_CNT', 'LOAN1_CNT', 'LOAN2_CNT', 'CRED_LOAN_CNT', 'HOUS_LOAN_CNT',
              'BANK_LOAN_CNT', 'POL_LOAN_CNT', 'AVG_LOAN', 'AVG_LOAN1', 'AVG_LOAN2', 'AVG_CRED_LOAN',
              'AVG_HOUS_LOAN', 'CARD_LOAN_CNT', 'AVG_CARD_LOAN', 'LOAN_LIMIT_CNT', 'AVG_LOAN_LIMIT',
              'NEW_LOAN_CNT', 'NEW_LOAN1_CNT', 'NEW_LOAN2_CNT', 'NEW_CRED_CNT', 'NEW_HOUS_CNT', 'AVG_SCORE',
              'CNT_1', 'CNT_2', 'CNT_3', 'CNT_4', 'CNT_5', 'CNT_6', 'CNT_7', 'CNT_8', 'CNT_9', 'CNT_10',
              'CONSUME_CNT', 'RAT_BIG_ENT', 'RAT_YESINCOME', 'RAT_PROENT', 'RAT_OWNER', 'RAT_RUN', 'RAT_PRORUN',
              'RAT_ETC', 'APT_CNT', 'NAPT_CNT', 'OWN_HOUS_CNT', 'NOWN_HOUS_CNT', 'PYN_U20_CNT', 'PYN_O20_CNT',
              'PYN_O30_CNT', 'PYN_O40_CNT', 'RAT_INC_SALE', 'RAT_INC_RENT', 'AVG_HIGH_YINC', 'RAT_YINC_1',
              'RAT_YINC_2', 'RAT_YINC_3', 'RAT_YINC_4', 'RAT_YINC_5', 'RAT_YINC_6', 'RAT_YINC_7']
AGE082 = [10, 21, 26, 31, 36, 41, 46, 51, 56, 61, 66, 70]          # 07_코드값사전 '연령 AGE (개인신용 5세)'
AGE082_P = np.array([.03, .08, .09, .09, .09, .095, .1, .1, .095, .09, .075, .145])


def cell100_code(cell_id):
    """'다사3123_03' → '다사310233' (국가격자 100m: 문자2 + x3 + y3 = 1km 코드에 x·y 한 자리씩)."""
    g, ij = cell_id.split("_")
    return f"{g[:2]}{g[2:4]}{ij[0]}{g[4:6]}{ij[1]}"


def gen_ds082(c, dongs):
    code = dongs.set_index("ADM_NM")
    adult = c["res"].to_numpy() * .82 * .93                            # 만18세 이상 · KCB 등록
    rows = []
    for g in (1, 2):
        for a, pa in zip(AGE082, AGE082_P):
            lam = adult * pa * .5
            tot = RNG.poisson(lam)
            m = tot > 0
            if not m.any():
                continue
            sub = c.loc[m]
            t = tot[m]
            r = pd.DataFrame({"BS_YR_MON": MONTH, "CELL_100": sub["cell_id"].map(cell100_code).to_numpy(),
                              "TOT_REG_CD": [f"{code.loc[d_, 'ADM_CD']}{k:06d}" for d_, k in
                                             zip(sub["dong"], (sub.index.to_numpy() * 7) % 999983)],
                              "hcd": sub["dong"].map(code["admi8"]).to_numpy() + "00",
                              "GENDER": g, "AGE": a, "TOT_CNT": t,
                              "M_CNT": t if g == 1 else 0, "FM_CNT": t if g == 2 else 0})
            working = 21 <= a <= 61
            r["YES_INCOME"] = RNG.binomial(t, .58 if working else .12)
            r["SELF_ENT"] = RNG.binomial(t, .13 if working else .05)
            r["ETC_CNT"] = RNG.binomial(t, .08)
            r["FOR_CNT"] = RNG.binomial(t, np.clip(sub["forn_share"].to_numpy() * .35, 0, 1))
            r["AVG_DIST"] = np.where(r["YES_INCOME"] > 0, RNG.normal(9000, 2500, len(r)).clip(500), 0).round()
            r["AVG_INC"] = np.where(t > 0, RNG.normal(3300 if working else 1500, 600, len(r)).clip(500), 0).round()
            r["MED_INC"] = (r["AVG_INC"] * .88).round()
            apt = sub["home_w"].to_numpy() > 20
            r["APT_CNT"] = np.where(apt, t, RNG.binomial(t, .3))
            r["NAPT_CNT"] = t - r["APT_CNT"]
            rows.append(r)
    d = pd.concat(rows, ignore_index=True).reindex(columns=DS082_COLS, fill_value=0)
    return d.sort_values(["CELL_100", "GENDER", "AGE"]).reset_index(drop=True)


# ══ 동 단위 가상 세계: 시간대별 방문객 · 재택 · 종사자 ════════════════════════
def dong_visitors(p, dongs):
    """동 × 무리별 가게 수 × 24시간 곡선 × 사람 수 → 동 × 시각 방문객(요일 계수 전)."""
    live = p[p["grp"].isin(GROUP.keys()) & ~p["dead"]]
    cnt = live.groupby(["행정동명", "grp"])["popularity"].sum().unstack(fill_value=0)
    v = np.zeros((len(dongs), 24))
    for gname, (_, _, people) in GROUP.items():
        if gname not in cnt:
            continue
        col = dongs["ADM_NM"].map(cnt[gname]).fillna(0).to_numpy()
        v += np.outer(col, np.array(PROFILE[gname])) * people
    return v                                                             # (동, 24)


def gen_ds014(dongs, vis):
    """동 × 일 × 시 × 내외국인(N/F) — 32컬럼, ETL_YMD 가 마지막 컬럼(실측 헤더 순서)."""
    ages = [10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70]
    cols = [f"M_{a}_CNT" for a in ages] + [f"F_{a}_CNT" for a in ages]
    res_n = (dongs["pop"] - dongs["forn"]).to_numpy()
    res_f = dongs["forn"].to_numpy()
    wrk = dongs["workers"].to_numpy()

    def split(total, age_p, male):
        m = np.outer(total * male, age_p / age_p.sum())
        f = np.outer(total * (1 - male), age_p / age_p.sum())
        return np.hstack([m, f])

    out = []
    for day in DAYS:
        wk = day.weekday()
        work_f = .55 if wk >= 5 else 1.0
        for h in range(24):
            night = day - pd.Timedelta(days=1) if h < 6 else day
            vf = NIGHT_DOW[night.weekday()] if (h >= 18 or h < 6) else (1.1 if wk >= 5 else 1.0)
            v = vis[:, h] * vf
            w = wrk * WORK[h] * work_f
            n_part = (split(res_n * HOME[h], AGE_RES, MALE["res"]) + split(v * .85, AGE_VIS, MALE["vis"])
                      + split(w * .70, AGE_WRK, MALE["wrk"]))
            f_part = (split(res_f * HOME[h], AGE_RES, MALE["res"]) + split(v * .15, AGE_VIS, MALE["vis"])
                      + split(w * .30, AGE_WRK, MALE["wrk"]))
            for gb, part in (("N", n_part), ("F", f_part)):
                vals = part * RNG.lognormal(0, .06, part.shape)
                df = pd.DataFrame(np.round(vals, 2), columns=cols)
                df.insert(0, "ADMI_CD", dongs["admi8"].to_numpy())
                df.insert(1, "CTY_NM", dongs["sgg_nm"].to_numpy())
                df.insert(2, "ADMI_NM", dongs["ADM_NM"].to_numpy())
                df.insert(3, "TIME_CD", h)
                df.insert(4, "FORN_GB", gb)
                df["ETL_YMD"] = day.strftime("%Y%m%d")
                out.append(df)
    return pd.concat(out, ignore_index=True)


def walk_share(dongs, p):
    """동별 밤 도보 비중 — 가게 밀도 분위가 높을수록 걸어서 움직인다(임의 가정)."""
    dens = p.groupby("행정동명").size().reindex(dongs["ADM_NM"]).fillna(0).to_numpy() / dongs["area_km2"].to_numpy()
    q = pd.Series(dens).rank(pct=True).to_numpy()
    return .14 + .28 * q


def gen_ds008(dongs, vis, p):
    """동 × 일 × 출발시각(21~02) × 이동수단 × 성 × 연령(10세) — 12컬럼."""
    wshare = walk_share(dongs, p)
    trip_rate = {21: .055, 22: .045, 23: .032, 0: .020, 1: .012, 2: .008}
    hour_walk = {21: 1.0, 22: 1.05, 23: 1.1, 0: 1.15, 1: 1.1, 2: 1.0}
    age_codes = ["02", "03", "04", "05", "06", "07", "08"]
    age_p = np.array([.06, .24, .22, .20, .17, .08, .03])
    res = dongs["pop"].to_numpy()
    out = []
    for day in DAYS:
        for h in HOURS:
            night = day - pd.Timedelta(days=1) if h < 12 else day
            dowf = NIGHT_DOW[night.weekday()]
            present = res * HOME[h] * .25 + vis[:, h] * dowf               # 밖에서 움직일 만한 사람
            trips = present * trip_rate[h] * RNG.lognormal(0, .08, len(dongs))
            w = np.clip(wshare * hour_walk[h], 0, .6)
            rest = 1 - w
            bus = .22 if h in (21, 22, 23) else .08
            sub = .12 if h in (21, 22, 23, 0) else 0.0
            modes = {0: rest * .55, 1: rest * bus, 2: rest * sub, 3: w, 7: rest * (.45 - bus - sub + .0)}
            if h in (21, 22):
                modes[4], modes[5] = rest * .004, rest * .002
            for tg, share in modes.items():
                for sex, sp in (("M", .56), ("W", .44)):
                    cnt = np.outer(trips * share * sp, age_p) * RNG.lognormal(0, .15, (len(dongs), len(age_p)))
                    df = pd.DataFrame(np.round(cnt, 2), columns=age_codes)
                    df["O_ADMI_CD"] = dongs["admi8"].to_numpy()
                    df = df.melt(id_vars="O_ADMI_CD", var_name="AGE_GRP", value_name="CNT")
                    df["TRANS_GB"], df["SEX_CD"], df["O_TIME_CD"] = tg, sex, h
                    df["ETL_YMD"] = day.strftime("%Y%m%d")
                    out.append(df[df["CNT"] >= .01])
    d = pd.concat(out, ignore_index=True)
    info = dongs.set_index("admi8")
    d["O_MEGA_NM"] = "경기도"
    d["O_CTY_NM"] = d["O_ADMI_CD"].map(info["sgg_nm"])
    d["O_ADMI_NM"] = d["O_ADMI_CD"].map(info["ADM_NM"])
    d["O_CENTER_X"] = d["O_ADMI_CD"].map(info["cx"])
    d["O_CENTER_Y"] = d["O_ADMI_CD"].map(info["cy"])
    cols = ["ETL_YMD", "O_TIME_CD", "O_ADMI_CD", "O_MEGA_NM", "O_CTY_NM", "O_ADMI_NM", "O_CENTER_X",
            "O_CENTER_Y", "TRANS_GB", "SEX_CD", "AGE_GRP", "CNT"]
    return d[cols]


# ══ OD — DS-004(동 × 목적, 시간 없음) · DS-001(구 × 시간 × 목적 × 수단) ═══════════════
PURPOSE_SCALE = {0: .48, 1: .22, 2: .06, 3: .08, 4: .01, 5: .02, 6: .18}   # 하루 통행 / 인구
HOUR_P = {   # 목적별 0~23시 출발 분포
    0: [12, 6, 3, 2, 2, 3, 5, 10, 15, 20, 25, 30, 40, 45, 50, 60, 80, 110, 130, 110, 80, 65, 50, 30],
    1: [3, 2, 2, 5, 15, 40, 90, 160, 140, 60, 25, 15, 10, 10, 10, 10, 15, 20, 15, 10, 8, 6, 5, 4],
    2: [0, 0, 0, 0, 0, 2, 10, 80, 120, 40, 15, 10, 10, 15, 20, 15, 10, 5, 3, 2, 1, 0, 0, 0],
    3: [1, 0, 0, 0, 0, 1, 2, 5, 10, 20, 40, 60, 70, 70, 70, 70, 75, 80, 70, 50, 30, 15, 5, 2],
    4: [0, 0, 0, 0, 0, 1, 3, 8, 15, 25, 35, 40, 40, 40, 35, 30, 25, 15, 8, 5, 3, 1, 0, 0],
    5: [0, 0, 0, 0, 0, 1, 3, 10, 40, 60, 60, 50, 30, 40, 45, 40, 30, 15, 5, 2, 1, 1, 0, 0],
    6: [5, 3, 2, 1, 1, 2, 5, 15, 30, 45, 55, 60, 65, 65, 65, 65, 70, 75, 70, 60, 45, 30, 18, 10],
}
WALK_BY_PURPOSE = {0: .22, 1: .12, 2: .35, 3: .25, 4: .15, 5: .15, 6: .22}


def od_matrix(dongs, p):
    """동 × 동 × 목적별 하루 통행(요일 계수 전)."""
    x, y = dongs["cx"].to_numpy(float), dongs["cy"].to_numpy(float)
    d = np.hypot(x[:, None] - x[None, :], y[:, None] - y[None, :]) / 1000
    np.fill_diagonal(d, np.sqrt(dongs["area_km2"].to_numpy()) / 2)
    pop = dongs["pop"].to_numpy()
    wrk = dongs["workers"].to_numpy()
    shops = p.groupby("행정동명").size().reindex(dongs["ADM_NM"]).fillna(0).to_numpy()
    hosp = p[p["상권업종대분류명"] == "보건의료"].groupby("행정동명").size().reindex(dongs["ADM_NM"]).fillna(0).to_numpy()
    act = wrk + 2 * shops
    g = {0: np.outer(act, pop) * np.exp(-d / 2.5), 1: np.outer(pop, wrk) * np.exp(-d / 4),
         2: np.outer(pop, pop) * np.exp(-d / 1.5), 3: np.outer(pop, shops) * np.exp(-d / 2),
         4: np.outer(pop, shops + 50) * np.exp(-d / 6), 5: np.outer(pop, hosp + 1) * np.exp(-d / 3),
         6: np.outer(pop, act) * np.exp(-d / 2)}
    tot = pop.sum()
    return {k: v / v.sum() * tot * PURPOSE_SCALE[k] for k, v in g.items()}


def gen_ds004(dongs, od):
    days = DAYS[:7]
    dow_f = {0: [1.0, 1.0, 1.0, 1.0, 1.15, 1.1, .85], 1: [1, 1, 1, 1, 1, .45, .3]}
    age_codes = ["02", "03", "04", "05", "06", "07"]
    age_p = np.array([.08, .22, .22, .21, .18, .09])
    info = dongs.reset_index(drop=True)
    out = []
    n = len(info)
    oi, di = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    for day in days:
        for pur, mat in od.items():
            f = dow_f.get(pur, [1] * 7)[day.weekday()]
            for sex, sp in (("M", .52), ("W", .48)):
                cnt = mat[..., None] * f * sp * age_p[None, None, :] * RNG.lognormal(0, .2, (n, n, len(age_p)))
                cnt = np.round(cnt, 2)
                keep = cnt >= .5
                a, b, c_ = np.nonzero(keep)
                out.append(pd.DataFrame({"ETL_YMD": day.strftime("%Y%m%d"), "o": a, "d": b,
                                         "PURPOSE": pur, "SEX_CD": sex,
                                         "AGE_GRP": np.array(age_codes)[c_], "CNT": cnt[keep]}))
    r = pd.concat(out, ignore_index=True)
    for side, col in (("O", "o"), ("D", "d")):
        r[f"{side}_ADMI_CD"] = info["admi8"].to_numpy()[r[col]]
        r[f"{side}_MEGA_NM"] = "경기도"
        r[f"{side}_CTY_NM"] = info["sgg_nm"].to_numpy()[r[col]]
        r[f"{side}_ADMI_NM"] = info["ADM_NM"].to_numpy()[r[col]]
        r[f"{side}_CENTER_X"] = info["cx"].to_numpy()[r[col]]
        r[f"{side}_CENTER_Y"] = info["cy"].to_numpy()[r[col]]
    # 안산 밖 행 몇 개 — 실물 '_4127' 추출분에도 출발·도착 한쪽만 안산인 행이 있다. 적재 코드가 걸러야 한다
    ext = r.sample(300, random_state=1).copy()
    ext["D_ADMI_CD"], ext["D_CTY_NM"], ext["D_ADMI_NM"] = "41390580", "시흥시", "정왕1동"
    ext["D_CENTER_X"], ext["D_CENTER_Y"] = 930500, 1918200
    r = pd.concat([r, ext], ignore_index=True)
    cols = ["ETL_YMD", "O_ADMI_CD", "O_MEGA_NM", "O_CTY_NM", "O_ADMI_NM", "O_CENTER_X", "O_CENTER_Y",
            "D_ADMI_CD", "D_MEGA_NM", "D_CTY_NM", "D_ADMI_NM", "D_CENTER_X", "D_CENTER_Y",
            "PURPOSE", "SEX_CD", "AGE_GRP", "CNT"]
    return r[cols]


def gen_ds001(dongs, od):
    """구(상록 41271 · 단원 41273) 간 OD × 일 × 출발·도착시각 × 목적 × 수단 × 성 × 연령."""
    days = DAYS[:14]
    sgg = dongs.groupby("sgg5").agg(nm=("sgg_nm", "first"), cx=("cx", "mean"), cy=("cy", "mean"))
    codes = dongs["sgg5"].to_numpy()
    keys = list(sgg.index)
    mats = {pur: np.array([[m[np.ix_(codes == a, codes == b)].sum() for b in keys] for a in keys])
            for pur, m in od.items()}
    age_codes = np.array(["03", "04", "05", "06"])
    age_p = np.array([.27, .26, .25, .22])
    modes = np.array([0, 1, 2, 3, 7])
    sexes, sex_p = np.array(["M", "W"]), np.array([.52, .48])
    hrs = np.arange(24)
    late = (hrs >= 22) | (hrs < 2)
    bus = np.where((hrs >= 6) & (hrs <= 23), .25, .06)
    subw = np.where(hrs >= 6, .12, 0.0)
    out = []
    for day in days:
        prev = (day - pd.Timedelta(days=1)).weekday()
        for pur, mat in mats.items():
            hp = np.array(HOUR_P[pur], float)
            hp /= hp.sum()
            f = np.ones(24)
            if pur == 0:                                                  # 금·토 밤 귀가가 늦다(밤 기준 요일)
                nite = np.where(hrs < 6, prev, day.weekday())
                f = np.where(late, pd.Series(nite).map({4: 1.5, 5: 1.5, 6: .8}).fillna(1.0).to_numpy(), 1.0)
            walk = WALK_BY_PURPOSE[pur] * np.where(late, 1.25, 1.0)
            rest = 1 - walk
            ms = np.stack([rest * .5, rest * bus, rest * subw, walk, rest * (.5 - bus - subw)], axis=1)  # (24, 5)
            # (시, 수단, 성, 출발구, 도착구, 연령)
            base = (hp * f)[:, None, None, None, None, None] * ms[:, :, None, None, None, None] \
                * sex_p[None, None, :, None, None, None] * mat[None, None, None, :, :, None] \
                * age_p[None, None, None, None, None, :]
            cnt = np.round(base * RNG.lognormal(0, .2, base.shape), 2)
            h_, m_, s_, a, b, c_ = np.nonzero(cnt >= .5)
            dtime = np.where(RNG.random(len(a)) < .8, h_, (h_ + 1) % 24)
            out.append(pd.DataFrame({
                "ETL_YMD": day.strftime("%Y%m%d"), "DOW": DOW_KR[day.weekday()], "O_TIME_CD": h_,
                "o": a, "d": b, "D_TIME_CD": dtime, "PURPOSE": pur, "TRANS_GB": modes[m_],
                "SEX_CD": sexes[s_], "AGE_GRP": age_codes[c_], "CNT": cnt[h_, m_, s_, a, b, c_]}))
    r = pd.concat(out, ignore_index=True)
    for side, col in (("O", "o"), ("D", "d")):
        r[f"{side}_CTY_CD"] = np.array(keys)[r[col]]
        r[f"{side}_MEGA_NM"] = "경기도"
        r[f"{side}_CTY_NM"] = sgg["nm"].to_numpy()[r[col]]
        r[f"{side}_CENTER_X"] = sgg["cx"].round().astype(int).to_numpy()[r[col]]
        r[f"{side}_CENTER_Y"] = sgg["cy"].round().astype(int).to_numpy()[r[col]]
    ext = r.sample(200, random_state=2).copy()                              # 안산 밖(시흥) 행 — 걸러야 한다
    ext["D_CTY_CD"], ext["D_CTY_NM"], ext["D_CENTER_X"], ext["D_CENTER_Y"] = "41390", "시흥시", 930500, 1918200
    r = pd.concat([r, ext], ignore_index=True)
    cols = ["ETL_YMD", "DOW", "O_TIME_CD", "O_CTY_CD", "O_MEGA_NM", "O_CTY_NM", "O_CENTER_X", "O_CENTER_Y",
            "D_TIME_CD", "D_CTY_CD", "D_MEGA_NM", "D_CTY_NM", "D_CENTER_X", "D_CENTER_Y",
            "PURPOSE", "TRANS_GB", "SEX_CD", "AGE_GRP", "CNT"]
    return r[cols]


# ══ 보안등 · CCTV (공공데이터 표준 규격, 임의값) ═══════════════════════════
def gen_lights_cctv(c, dongs):
    n = pd.read_csv(PROC / "nodes.csv", encoding="utf-8-sig")
    e = pd.read_csv(PROC / "edges.csv")
    res_q = pd.Series(c["res"].to_numpy()).rank(pct=True).to_numpy()
    node_q = res_q[n["cell"].to_numpy()]
    u, v = e["u"].to_numpy(), e["v"].to_numpy()
    L = e["len_m"].to_numpy()
    pq = (node_q[u] + node_q[v]) / 2
    k = RNG.poisson(L / 32 * (.12 + .75 * pq))                       # 주거지 골목일수록 촘촘하게
    ei = np.repeat(np.arange(len(e)), k)
    t = RNG.random(len(ei))
    x = n["x"].to_numpy()[u[ei]] * (1 - t) + n["x"].to_numpy()[v[ei]] * t + RNG.normal(0, 3, len(ei))
    y = n["y"].to_numpy()[u[ei]] * (1 - t) + n["y"].to_numpy()[v[ei]] * t + RNG.normal(0, 3, len(ei))
    g = gpd.GeoDataFrame(geometry=gpd.points_from_xy(x, y), crs=5179).to_crs(4326)
    dong = n["dong"].to_numpy()[u[ei]]
    gu = pd.Series(dong).map(dongs.set_index("ADM_NM")["sgg_nm"]).str.split().str[-1].to_numpy()
    lights = pd.DataFrame({
        "보안등위치명": [f"{d_} 보안등 {i + 1:05d}" for i, d_ in enumerate(dong)],
        "설치개수": np.where(RNG.random(len(ei)) < .92, 1, 2),
        "소재지도로명주소": "",
        "소재지지번주소": [f"경기도 안산시 {a} {b} 일원" for a, b in zip(gu, dong)],
        "위도": g.geometry.y.round(7), "경도": g.geometry.x.round(7),
        "설치연도": RNG.integers(2003, 2026, len(ei)),
        "설치형태": RNG.choice(["한전주", "단독주", "벽부형", "기타"], len(ei), p=[.55, .3, .12, .03]),
        "관리기관전화번호": "031-000-0000",
        "관리기관명": [f"경기도 안산시 {a}청" for a in gu],
        "데이터기준일자": f"{YEAR}-{MON:02d}-30", "제공기관코드": "0000000", "제공기관명": "경기도 안산시(임의값)"})
    # CCTV — 교차로(차수 3 이상) 중 주거지일수록
    deg = np.bincount(np.r_[u, v], minlength=len(n))
    cand = np.flatnonzero(deg >= 3)
    pick = cand[RNG.random(len(cand)) < (.06 + .28 * node_q[cand])]
    gc = gpd.GeoDataFrame(geometry=gpd.points_from_xy(n["x"].to_numpy()[pick] + RNG.normal(0, 4, len(pick)),
                                                      n["y"].to_numpy()[pick] + RNG.normal(0, 4, len(pick))),
                          crs=5179).to_crs(4326)
    cd = n["dong"].to_numpy()[pick]
    cgu = pd.Series(cd).map(dongs.set_index("ADM_NM")["sgg_nm"]).str.split().str[-1].to_numpy()
    cctv = pd.DataFrame({
        "관리기관명": [f"경기도 안산시 {a}청" for a in cgu],
        "소재지도로명주소": "",
        "소재지지번주소": [f"경기도 안산시 {a} {b} 일원" for a, b in zip(cgu, cd)],
        "설치목적구분": RNG.choice(["생활방범", "어린이보호", "쓰레기단속", "교통단속", "기타"], len(pick),
                             p=[.70, .15, .07, .05, .03]),
        "카메라대수": RNG.choice([1, 2, 3, 4], len(pick), p=[.45, .3, .15, .1]),
        "카메라화소수": RNG.choice([200, 400], len(pick), p=[.6, .4]),
        "촬영방면정보": RNG.choice(["360도 전방면", "교차로 방면", "골목 방면"], len(pick)),
        "보관일수": 30,
        "설치연월": [f"{y_}-{m_:02d}" for y_, m_ in zip(RNG.integers(2010, 2026, len(pick)),
                                                       RNG.integers(1, 13, len(pick)))],
        "관리기관전화번호": "031-000-0000",
        "WGS84위도": gc.geometry.y.round(7), "WGS84경도": gc.geometry.x.round(7),
        "데이터기준일자": f"{YEAR}-{MON:02d}-30", "제공기관코드": "0000000", "제공기관명": "경기도 안산시(임의값)"})
    return lights, cctv


# ══ 쓰기 ═════════════════════════════════════════════════════════════
def write(df, name, gz=False):
    path = OUT / (name + (".csv.gz" if gz else ".csv"))
    df.to_csv(path, index=False, encoding="cp949", compression="gzip" if gz else None)
    mb = path.stat().st_size / 1e6
    log(f"    [v] {path.name:<52s} {len(df):>9,}행 · {mb:6.1f}MB")
    return {"file": path.name, "rows": int(len(df)), "mb": round(mb, 2), "cols": int(df.shape[1])}


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    LATENT.mkdir(parents=True, exist_ok=True)
    log(f"[0] 기준월 {MONTH} · 시드 {PM.SYNTH_SEED.value} · 출력 {OUT}")
    log("[1] 실데이터 뼈대")
    dongs = load_dongs()
    c = load_cells_residents(dongs)
    p = load_shops(dongs)
    vis = dong_visitors(p, dongs)

    log("[2] 규격 파일 (임의값)")
    rep = {}
    rep["DS-054"] = write(gen_ds054(p), f"tbsh_gyeonggi_agrde_1tm_{MONTH}", gz=True)
    rep["DS-048"] = write(gen_ds048(p), f"tbsh_gyeonggi_mer_s_{MONTH}")
    rep["DS-082"] = write(gen_ds082(c, dongs), f"GYEONGGI_CELL_STAT_{MONTH}", gz=True)
    rep["DS-014"] = write(gen_ds014(dongs, vis), f"T22_GG_ADMI_FLOWPOP_{MONTH}_4127")
    rep["DS-008"] = write(gen_ds008(dongs, vis, p), f"T11_GG_TRANS_SEXAGE_ADMI_OUTFLOW_{MONTH}_4127", gz=True)
    od = od_matrix(dongs, p)
    rep["DS-004"] = write(gen_ds004(dongs, od), f"T13_GG_PURPOSE_SEXAGE_ADMI_OD_{MONTH}_4127", gz=True)
    rep["DS-001"] = write(gen_ds001(dongs, od), f"T25_GG_PURPOSE_TRANS_SEXAGE_SGG_OD_{MONTH}_4127", gz=True)
    lights, cctv = gen_lights_cctv(c, dongs)
    rep["보안등"] = write(lights, "전국보안등정보표준데이터_안산_임의값")
    rep["CCTV"] = write(cctv, "전국CCTV표준데이터_안산_임의값")
    blocks = np.unique(p["blk_cd"].to_numpy())
    lon, lat = block_center(blocks)
    rep["블록좌표"] = write(pd.DataFrame({"blk_cd": blocks, "lon": np.round(lon, 6), "lat": np.round(lat, 6)}),
                          "card_block_centroid_임의규칙")

    log("[3] 가상 세계의 정답 (적재 코드 검증용 — 실물에는 없다)")
    keep = ["상호명", "상권업종소분류명", "행정동명", "경도", "위도", "x", "y", "blk_cd", "card_tpbuz_nm_3",
            "grp", "popularity", "close_h", "dead"]
    p[keep].to_csv(LATENT / "shops_latent.csv", index=False, encoding="utf-8-sig")
    c[["cell_id", "dong", "res", "home_w"]].to_csv(LATENT / "cells_latent.csv", index=False, encoding="utf-8-sig")
    meta = {"month": MONTH, "seed": PM.SYNTH_SEED.value, "hours": HOURS, "files": rep,
            "anchors_24h": int(((p.grp.isin(["cvs", "gas", "pc"])) & (p.close_h == 99)).sum()),
            "anchors_all": int(p.grp.isin(["cvs", "gas", "pc"]).sum()),
            "dead_shops": int(p["dead"].sum()), "sec": round(time.time() - t0, 1)}
    (LATENT / "generation_report.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[v] 완료 {meta['sec']}초 · 앵커 {meta['anchors_all']:,}곳 중 24시간 {meta['anchors_24h']:,} · "
        f"휴업 {meta['dead_shops']:,}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
