# -*- coding: utf-8 -*-
"""
인벤토리 규격 파일 → 시연 프로토타입 입력 (data/proto/)
실행:  python src/ingest_inventory.py               # 기본: data/synthetic/raw (임의값) → data/proto
       python src/ingest_inventory.py <원본폴더>     # 실데이터가 오면 폴더만 바꾼다
       py -3.12 src/ingest_inventory.py data/real/raw   # 민간 실데이터(#19, src/stage_real.py 가 옮긴 것) → data/real/proto

★ 임의값이 아닌 입력의 결과는 data/real/proto 에 쓴다(#19). data/proto 는 공유본(GitHub 공개) · 드라이브 앱에 실리므로
  민간 실데이터가 들어가면 안 된다 — build_share.py · build_app_folders.py 도 ingest_report 의 _meta.synthetic 을 보고 거부한다.
  화면은 환경변수 NIGHT_DATA=real 일 때 data/real/proto 를 읽는다(`시연_실데이터.bat`).
  카드 블록 좌표표가 없으면(실물) DS-054 · 048 은 지도에 못 올리고 앵커를 상가정보(공개) 심야 업종 위치로 대신한다.

★ 이 파일은 실데이터가 와도 그대로 쓰는 코드다. 그래서 인벤토리 품질 주의사항을 전부 여기서 처리한다.
  Q-21 소수·지수 표기 → float 명시 파싱, 반올림 안 함      Q-22 cp949
  Q-24 좌표계(UTM-K 5179 / 블록 WGS84)                   FORN_GB N 만(이중계산 방지)
  심야 절단(22·23·0·1), 0·1시는 전날 밤(params.SLOT_NIGHT_OF)
  카드 헤더 대소문자(규격서 BLK_CD ↔ 실측 blk_cd) · '_4127' 추출분 안의 안산 밖 행

출력 (화면은 이것만 읽는다 — 원자료 행은 화면에 닿지 않는다, CLAUDE.md §6)
  terms.npz          (28 시간대 × 셀) R 주민 보행 · V 방문 결제 · A_d 문 연 앵커까지 거리
  anchor_blocks.csv  앵커 블록 좌표 · 시간대별 '문 연다' 비율 · DS-048 가맹점 수 · 상가 이름(실데이터)
  dong_curve.csv     DS-014 동 × 0~23시 내국인 20~54세 평시 곡선 (대민개방 — 시민 화면 표출용)
  walk_share.csv     DS-008 동 × 시각 도보 비중
  od_night.csv       동 OD × 시간대 밤 도보 귀가 통행 (DS-004 × DS-001)
  lights.csv · cctv.csv                       보안등 · CCTV — data/public 이 있으면 실데이터(public_data.export_proto), 없으면 임의값
  bells.csv · police.csv · stations.csv       비상벨(공개분) · 지구대 · 파출소(OSM) · 역 밤 하차(코레일) — 실데이터만
  edge_public.csv · public_report.json        간선별 도로 등급 · 보안등 수 · 밤 역 귀갓길 흐름 / 정제 판정
  trips.npz          귀가 통행 표본의 최단경로 사건행렬 (개선 우선 구간용)
  ingest_report.json 판정 + 근거 원자료
"""
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.sparse import csr_matrix, save_npz
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "synthetic" / "raw"
SYN_RAW = RAW
OUTP = ROOT / "data" / "proto"
REAL_OUT = ROOT / "data" / "real" / "proto"     # 민간 실데이터 결과 — 이 PC에서만(#19)
sys.path.insert(0, str(ROOT / "src"))
import params as PM
import night_core as NC

NIGHT = PM.NIGHT_HOURS.value
REP = {}


def log(m):
    print(m, flush=True)


def note(key, verdict, **raw):
    """판정 한 줄 + 근거 원자료 (CLAUDE.md §7)."""
    REP[key] = {"verdict": verdict, **{k: (v.item() if hasattr(v, "item") else v) for k, v in raw.items()}}
    log(f"    · {verdict}  " + " ".join(f"{k}={v}" for k, v in raw.items()))


def find(stem):
    hits = sorted(list(RAW.glob(f"{stem}*.csv")) + list(RAW.glob(f"{stem}*.csv.gz")))
    if not hits:
        raise SystemExit(f"[X] {RAW} 에 {stem}* 가 없습니다")
    return dedup(stem, hits)


def dedup(stem, files):
    """바이트가 같은 파일은 한 번만 읽는다 — 이름의 달이 다른데 내용이 같은 파일이 납품될 수 있다(#19).
    두 번 읽으면 그 달이 두 번 세어지고 빠진 달은 모른 채 지나간다. 크기가 같은 파일끼리만 해시를 잰다."""
    import hashlib
    from collections import Counter
    size = Counter(f.stat().st_size for f in files)
    seen, keep, dups = {}, [], []
    for f in files:
        if size[f.stat().st_size] > 1:
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for b in iter(lambda: fh.read(1 << 22), b""):
                    h.update(b)
            if h.hexdigest() in seen:
                dups.append(f"{f.name} = {seen[h.hexdigest()]}")
                continue
            seen[h.hexdigest()] = f.name
        keep.append(f)
    if dups and f"dup_{stem}" not in REP:
        note(f"dup_{stem}", "바이트가 같은 파일은 한 번만 읽음 — 둘 중 한 달 자료가 없다(어느 달인지는 파일 안 날짜로 확인)",
             같은파일=dups, 읽은파일=len(keep))
    return keep


def encoding_of(f):
    """원본 인코딩 — 인벤토리 Q-22 는 cp949 지만 실물 일부는 UTF-8 일 수 있어 앞부분 64KB 로 가린다(#19)."""
    import codecs
    import gzip
    with (gzip.open if str(f).endswith(".gz") else open)(f, "rb") as h:
        b = h.read(1 << 16)
    try:
        codecs.getincrementaldecoder("utf-8")().decode(b, final=False)   # 끝에 잘린 글자는 봐준다
    except UnicodeDecodeError:
        return "cp949"
    return "utf-8-sig" if any(x > 127 for x in b) else "cp949"


def read(stem, usecols=None, dtype=None, lower=False, keep=None, chunk=1_000_000):
    """같은 이름의 월별 파일을 전부 이어 읽는다. 헤더는 월마다 다를 수 있다(Q-09) — 필요한 컬럼만.
    keep(df) → df 를 주면 조각마다 먼저 거른다 — 실데이터 OD 는 한 달 수백만 행이라 다 읽으면 메모리가 모자란다(#19)."""
    out = []
    for f in find(stem):
        enc = encoding_of(f)
        head = pd.read_csv(f, nrows=0, encoding=enc).columns
        cmap = {c.lower(): c for c in head} if lower else {c: c for c in head}
        want = None if usecols is None else [cmap[c] for c in usecols]
        dt = None if dtype is None else {cmap.get(k, k): v for k, v in dtype.items() if cmap.get(k, k) in head}
        for d in pd.read_csv(f, encoding=enc, usecols=want, dtype=dt, float_precision="high",
                             low_memory=False, chunksize=chunk):
            if lower:
                d.columns = [c.lower() for c in d.columns]
            out.append(d if keep is None else keep(d))
    return pd.concat(out, ignore_index=True)


def tally_keep(outer, inner, tally):
    """조각 거르기 + 개수 세기 — outer 밖은 '버린 행', outer 안은 '남은 행'(예전 note 와 같은 뜻), 반환은 outer & inner."""
    def f(d):
        o = outer(d)
        tally["out"] = tally.get("out", 0) + int((~o).sum())
        tally["in"] = tally.get("in", 0) + int(o.sum())
        return d[o & inner(d)]
    return f


def night_of(ymd, hour):
    """(일자 문자열, 시) → 밤 기준 날짜. 0·1시는 전날 밤."""
    d = pd.to_datetime(ymd.astype(str), format="%Y%m%d")
    return d - pd.to_timedelta((np.asarray(hour) < 12).astype(int), unit="D")


def slot_of(night_date, hour):
    hidx = pd.Series(hour).map({h: i for i, h in enumerate(NIGHT)}).to_numpy()
    return night_date.dt.weekday.to_numpy() * len(NIGHT) + hidx


def nights_per_slot(night_date, hour):
    """시간대별로 자료에 들어 있는 밤의 수 — 평균을 낼 분모."""
    s = pd.DataFrame({"slot": slot_of(night_date, hour), "n": night_date.to_numpy()})
    return s.groupby("slot")["n"].nunique().reindex(range(len(NC.SLOTS)), fill_value=0).to_numpy()


def cell100_to_id(code):
    """'다사310233' → '다사3123_03' (prep.py 의 cell_id 규칙)."""
    c = str(code)
    return f"{c[:2]}{c[2:4]}{c[5:7]}_{c[4]}{c[7]}"


# ══ 1. 셀·그래프 뼈대 (본체 prep.py 산출물) ══════════════════════════════
def load_base():
    cells = pd.read_csv(PROC / "cells.csv", encoding="utf-8-sig")
    nodes = pd.read_csv(PROC / "nodes.csv", encoding="utf-8-sig")
    edges = pd.read_csv(PROC / "edges.csv")
    dong = gpd.read_file(PROC / "dong.geojson")
    return cells, nodes, edges, dong


def ansan(code):
    return pd.Series(code).astype(str).str.startswith("4127").to_numpy()


# ══ 2. 주민 보행 R = DS-008 도보 출발 × DS-082 거주 비중 ═════════════════════
def term_R(cells, nbr):
    log("\n[2] 주민 보행 — DS-008 도보 출발 × DS-082 100m 거주 비중")
    d8 = read("T11_GG_TRANS_SEXAGE_ADMI_OUTFLOW",
              usecols=["ETL_YMD", "O_TIME_CD", "O_ADMI_CD", "O_ADMI_NM", "TRANS_GB", "AGE_GRP", "CNT"],
              dtype={"ETL_YMD": str, "O_ADMI_CD": str, "AGE_GRP": str, "CNT": float})
    n0 = len(d8)
    d8 = d8[ansan(d8["O_ADMI_CD"])]
    hours_seen = sorted(d8["O_TIME_CD"].unique().tolist())
    cut = d8["O_TIME_CD"].isin(NIGHT)
    note("ds008_hour_cut", "심야 4칸만 남김", 시각=hours_seen, 남은행=int(cut.sum()), 버린행=int((~cut).sum()))
    d8 = d8[cut & ~d8["O_ADMI_NM"].isin(PM.EXCLUDE_DONG.value)].copy()
    nd = night_of(d8["ETL_YMD"], d8["O_TIME_CD"])
    d8["slot"] = slot_of(nd, d8["O_TIME_CD"].to_numpy())
    nights = nights_per_slot(nd, d8["O_TIME_CD"].to_numpy())
    moved = int(((d8["O_TIME_CD"] < 12) & (nd.dt.date != pd.to_datetime(d8["ETL_YMD"]).dt.date)).sum())
    note("night_of", "0·1시 행을 전날 밤으로 옮김", 옮긴행=moved, 시간대별_밤수_최소=int(nights.min()),
         최대=int(nights.max()))
    # 도보 비중(표출용) · 20~59세(10세 코드 03~06 — FLOW_AGE 20~54 와 5년 차이, 10세 단위라 더 못 자른다)
    d8a = d8[d8["AGE_GRP"].isin(["03", "04", "05", "06"])]
    tot = d8a.groupby(["O_ADMI_NM", "O_TIME_CD"])["CNT"].sum()
    walk = d8a[d8a["TRANS_GB"] == 3].groupby(["O_ADMI_NM", "O_TIME_CD"])["CNT"].sum()
    ws = (walk / tot).rename("walk_share").reset_index()
    ws.to_csv(OUTP / "walk_share.csv", index=False, encoding="utf-8-sig")
    W = (d8a[d8a["TRANS_GB"] == 3].groupby(["O_ADMI_NM", "slot"])["CNT"].sum()
         .unstack(fill_value=0).reindex(columns=range(len(NC.SLOTS)), fill_value=0))
    W = W.div(np.maximum(nights, 1), axis=1)                          # 밤 1회 평균
    note("ds008_walk", "도보(TRANS_GB=3) 출발 = 주민 보행의 동 총량", 원행=n0,
         도보비중_범위=f"{ws.walk_share.min():.2f}~{ws.walk_share.max():.2f}")

    # DS-082 파일 이름이 해마다 다르다 — 2025 GYEONGGI_CELL_STAT_ · 2026 GYEONGGI_CELL_HCD_STAT_ (#19). 소득 · 부채 칸은 읽지 않는다
    n82 = len(find("GYEONGGI_CELL"))
    d82 = read("GYEONGGI_CELL", usecols=["CELL_100", "hcd", "AGE", "TOT_CNT"],
               dtype={"CELL_100": str, "hcd": str, "TOT_CNT": float})
    d82 = d82[ansan(d82["hcd"]) & d82["AGE"].isin([21, 26, 31, 36, 41, 46, 51])]   # 20~54세 (FLOW_AGE)
    pop = d82.groupby("CELL_100")["TOT_CNT"].sum() / n82                 # 월 평균(파일 하나 = 한 달)
    ids = pop.index.map(cell100_to_id)
    cidx = pd.Series(np.arange(len(cells)), index=cells["cell_id"])
    hit = ids.isin(cidx.index)
    res = np.zeros(len(cells))
    res[cidx[ids[hit]].to_numpy()] = pop.to_numpy()[hit]
    small = int(((pop > 0) & (pop < 30)).sum())
    note("ds082_match", "CELL_100 → 3안 100m 셀", 격자=len(pop), 매칭=int(hit.sum()), 못맞춘격자=int((~hit).sum()),
         인구30미만격자=small)
    dtot = pd.Series(res).groupby(cells["dong"].to_numpy()).transform("sum").to_numpy()
    share = np.where(dtot > 0, res / np.where(dtot > 0, dtot, 1), 0)
    Wc = W.reindex(cells["dong"]).fillna(0).to_numpy()                 # (셀, 28)
    R = (Wc * share[:, None]).T                                        # (28, 셀)
    R = np.asarray(nbr @ R.T).T                                        # 반경 100m 합 (ANCHOR_R_M)
    return R, share, res


def term_P(cells):
    """DS-032 50m 셀 × 시간 유동인구(내국인 20~54세 — FLOW_AGE · FORN_GB N) → 3안 100m 셀 × 28 시간대, 밤 1회 평균(#20).
    '그 자리에 있는 사람'이라 밤의 주택가는 집에 있는 주민까지 잡힌다 — 어떻게 쓸지는 FLOW_FORM 이 정한다.
    20GB 를 메모리에 올리지 않게 조각마다 밤 4칸 · 안산 · 내국인만 남겨 (100m 셀, 시간대) 합으로 접는다. 원자료 행은 남기지 않는다.
    #35 — 같은 읽기에서 러닝 시간대(RUN_BANDS — 새벽 · 저녁) 시각도 따로 접는다(요일 구분 없이 날짜 × 시각 1회 평균).
    반환: (P (28, 셀) 또는 None, run {"bands": [...], "hours": {...}, "P": (시간대 수, 셀)} 또는 None). 밤 P 계산은 #20 과 같다."""
    files = find("T1_GG_50CELL_FLOWPOP") if list(RAW.glob("T1_GG_50CELL_FLOWPOP*.csv")) else []
    if not files:
        return None, None
    log("\n[2b] DS-032 50m 셀 × 시간 유동인구 → 100m 셀 × 밤 시간대 (+ 러닝 새벽 · 저녁)")
    cols = [f"{s}_{a}_CNT" for s in "MF" for a in PM.FLOW_AGE.value]
    use = ["ADMI_CD", "UTMK_X", "UTMK_Y", "TIME_CD", "FORN_GB", "ETL_YMD"] + cols
    tree = cKDTree(cells[["x", "y"]].to_numpy())
    bands = list(PM.RUN_BANDS.value)
    band_of = {int(h): i for i, k in enumerate(bands) for h in PM.RUN_BANDS.value[k]}
    if set(band_of) & set(NIGHT):
        raise SystemExit("[X] RUN_BANDS 시각이 밤 시간대(NIGHT_HOURS)와 겹칩니다")
    parts, nights, forn, t, span = [], set(), {}, {"행": 0, "남은행": 0, "격자밖": 0}, {}
    bparts, bdays, tb = [], [set() for _ in bands], {"남은행": 0, "격자밖": 0}
    for f in files:
        enc = encoding_of(f)
        for d in pd.read_csv(f, encoding=enc, usecols=use, chunksize=2_000_000, float_precision="high",
                             dtype={"ADMI_CD": str, "ETL_YMD": str, "FORN_GB": str, **{c: float for c in cols}}):
            t["행"] += len(d)
            lo, hi = d["ETL_YMD"].min(), d["ETL_YMD"].max()          # 파일 이름의 달을 믿지 않는다(#19 T22) — 안의 날짜를 남긴다
            a, b = span.get(f.name, (lo, hi))
            span[f.name] = (min(a, lo), max(b, hi))
            isn = (d["FORN_GB"] == "N").to_numpy()
            forn["N"] = forn.get("N", 0) + int(isn.sum())
            forn["그 외"] = forn.get("그 외", 0) + int((~isn).sum())
            base = ansan(d["ADMI_CD"]) & isn
            db = d[base & d["TIME_CD"].isin(list(band_of)).to_numpy()]  # 러닝 시간대(#35) — 밤 계산과 따로
            d = d[base & d["TIME_CD"].isin(NIGHT).to_numpy()]
            if not db.empty:
                dist, ci = tree.query(db[["UTMK_X", "UTMK_Y"]].to_numpy(), distance_upper_bound=75.0)
                ok = np.isfinite(dist)
                tb["격자밖"] += int((~ok).sum())
                db, ci = db[ok], ci[ok]
                bi = db["TIME_CD"].map(band_of).to_numpy()
                for k in np.unique(bi):
                    u = db.loc[bi == k, ["ETL_YMD", "TIME_CD"]].drop_duplicates()
                    bdays[k].update(zip(u["ETL_YMD"], u["TIME_CD"]))
                bparts.append(pd.DataFrame({"c": ci, "b": bi, "p": db[cols].to_numpy().sum(axis=1)}).groupby(["c", "b"])["p"].sum())
                tb["남은행"] += len(db)
            if d.empty:
                continue
            dist, ci = tree.query(d[["UTMK_X", "UTMK_Y"]].to_numpy(), distance_upper_bound=75.0)  # 50m 중심 → 100m 중심 35m
            ok = np.isfinite(dist)
            t["격자밖"] += int((~ok).sum())
            d, ci = d[ok], ci[ok]
            nd = night_of(d["ETL_YMD"], d["TIME_CD"])
            h = d["TIME_CD"].to_numpy()
            nights.update(zip(nd.dt.strftime("%Y%m%d"), h))
            parts.append(pd.DataFrame({"c": ci, "s": slot_of(nd, h), "p": d[cols].to_numpy().sum(axis=1)})
                         .groupby(["c", "s"])["p"].sum())
            t["남은행"] += len(d)
    agg = pd.concat(parts).groupby(level=[0, 1]).sum()
    ns = np.zeros(len(NC.SLOTS))
    for ymd, h in nights:
        ns[NC.slot_index(pd.Timestamp(ymd).weekday(), int(h))] += 1
    P = np.zeros((len(NC.SLOTS), len(cells)))
    P[agg.index.get_level_values(1).to_numpy(), agg.index.get_level_values(0).to_numpy()] = agg.to_numpy()
    P /= np.maximum(ns, 1)[:, None]
    note("ds032", "50m 유동인구 → 100m 셀 × 밤 시간대(내국인 20~54세, 밤 1회 평균)", 파일=len(files), **t,
         내외국인행=forn, 시간대별_밤수=f"{int(ns.min())}~{int(ns.max())}", 값있는셀=int((P.max(axis=0) > 0).sum()),
         날짜범위={k: f"{a}~{b}" for k, (a, b) in span.items()})
    run = None
    if bparts:
        bagg = pd.concat(bparts).groupby(level=[0, 1]).sum()
        nb = np.array([len(s) for s in bdays], float)                 # 시간대마다 (날짜, 시각) 수 — 1회 평균의 분모
        Pr = np.zeros((len(bands), len(cells)))
        Pr[bagg.index.get_level_values(1).to_numpy(), bagg.index.get_level_values(0).to_numpy()] = bagg.to_numpy()
        Pr /= np.maximum(nb, 1)[:, None]
        run = {"bands": bands, "hours": {k: list(PM.RUN_BANDS.value[k]) for k in bands}, "P": Pr}
        note("ds032_run", "러닝 시간대(RUN_BANDS) — 같은 거르기, 요일 구분 없이 날짜 × 시각 1회 평균(#35)", **tb,
             **{f"{k}_날짜시각수": int(n) for k, n in zip(bands, nb)}, 값있는셀=int((Pr.max(axis=0) > 0).sum()))
    return P, run


def mask_cells(res):
    """화면에서 가릴 칸(#19) — 거주 1명 이상 MASK_MIN_POP 미만. 기준을 바꾸면 몇 칸이 가려지는지 같이 남긴다."""
    k = PM.MASK_MIN_POP.value
    note("mask_counts", f"화면에서 '자료 부족'으로 가릴 100m 칸 — 20~54세 거주 1명 이상 {k}명 미만(MASK_MIN_POP)",
         거주셀=int((res > 0).sum()), **{f"기준{t}명": int(((res > 0) & (res < t)).sum()) for t in (5, 10, 30)})
    return (res > 0) & (res < k)


def has_blocks():
    return bool(list(RAW.glob("card_block_centroid*.csv")))


def public_anchors(cells):
    """카드 블록 좌표표가 없을 때(실물, #19) — DS-054 · 048 은 지도에 못 올린다.
    앵커 = 상가정보(공개) 심야 업종 위치(본체와 같은 방식), 방문 결제 V = 0, '그 시간에 열었나'(s0~s27)는 비워 둔다."""
    a = pd.read_csv(PROC / "anchors.csv", encoding="utf-8-sig")
    a = a[a["kind"] == "앵커"].reset_index(drop=True)
    g = gpd.GeoDataFrame(a, geometry=gpd.points_from_xy(a["lon"], a["lat"]), crs=4326).to_crs(5179)
    xy = np.c_[g.geometry.x.to_numpy(), g.geometry.y.to_numpy()]
    d = cKDTree(xy).query(cells[["x", "y"]].to_numpy())[0]
    A_d = np.tile(d, (len(NC.SLOTS), 1))
    V = np.zeros((len(NC.SLOTS), len(cells)))
    ab = pd.DataFrame({"blk_cd": np.arange(len(a)), "x": xy[:, 0], "y": xy[:, 1], "lon": a["lon"], "lat": a["lat"],
                       "merchants": np.nan, "fran_cnt": np.nan, "stop_cnt": np.nan})
    ab = ab.join(pd.DataFrame(np.nan, index=ab.index, columns=[f"s{i}" for i in range(len(NC.SLOTS))]))
    ab["names"] = a["name"] + "(" + a["biz"] + ")"
    ab["dong"] = a["dong"]
    cards = sorted({p.name.split("_20")[0] for p in RAW.glob("tbsh_*.csv")})
    note("card_blocks", "카드 블록 좌표표가 없어 DS-054 · 048 을 지도에 못 올림 — 앵커는 상가정보 심야 업종 위치 · 방문 결제 비움 · "
         "영업 여부 모름(CARD_BLOCK_XY)", 앵커=len(a), 받은카드원본=cards)
    return V, A_d, ab


# ══ 3. 카드 — 방문 결제 V · 문 연 앵커 A_d (DS-054) + 가맹점 실재 (DS-048) ═══════════
def load_blocks():
    """블록코드 → 좌표. ★ 실물에는 이 표가 없다(params.CARD_BLOCK_XY, C등급)."""
    b = pd.read_csv(find("card_block_centroid")[0], encoding="cp949")
    g = gpd.GeoDataFrame(b, geometry=gpd.points_from_xy(b.lon, b.lat), crs=4326).to_crs(5179)
    b["x"], b["y"] = g.geometry.x.to_numpy(), g.geometry.y.to_numpy()
    return b.set_index("blk_cd")


def term_card(cells, blocks):
    log("\n[3] 카드 — DS-054 블록 × 1시간 (비개방) · DS-048 가맹점 (개방)")
    use = ["ta_ymd", "admi_cty_no", "blk_cd", "card_tpbuz_nm_2", "card_tpbuz_nm_3", "hour", "cnt"]
    c = read("tbsh_gyeonggi_agrde_1tm", usecols=use, lower=True,
             dtype={"ta_ymd": str, "admi_cty_no": str, "hour": str, "cnt": float, "blk_cd": np.int64})
    n0 = len(c)
    c = c[ansan(c["admi_cty_no"])].copy()
    c["h"] = c["hour"].astype(int)
    hours_seen = sorted(c["hour"].unique().tolist())
    cut = c["h"].isin(NIGHT)
    note("ds054_hour_cut", "심야 4칸만 남김", 시각=hours_seen, 남은행=int(cut.sum()), 버린행=int((~cut).sum()))
    c = c[cut].copy()
    nd = night_of(c["ta_ymd"], c["h"])
    c["slot"] = slot_of(nd, c["h"].to_numpy())
    c["night"] = nd.to_numpy()
    nights = nights_per_slot(nd, c["h"].to_numpy())
    miss = ~c["blk_cd"].isin(blocks.index)
    note("blk_xy", "블록코드 → 좌표 (임의 규칙, 실물에 없음)", 블록=int(c.blk_cd.nunique()),
         좌표없는블록=int(c.loc[miss, "blk_cd"].nunique()), 원행=n0)
    c = c[~miss]
    anc = PM.CARD_ANCHOR_NM3.value
    nl = PM.CARD_NIGHTLIFE_NM3.value
    kind = np.where(c["card_tpbuz_nm_3"].isin(anc), "anchor",
                    np.where(c["card_tpbuz_nm_3"].isin(nl), "nightlife", "visit"))
    c["kind"] = kind
    note("card_kind", "업종 소분류로 3갈래", 앵커행=int((kind == "anchor").sum()),
         유흥행=int((kind == "nightlife").sum()), 방문행=int((kind == "visit").sum()))

    # 앵커: 시간대별 '결제가 발생한 밤의 비율' (건수 크기는 안 쓴다 — Q-21)
    a = c[c["kind"] == "anchor"]
    an = a[a["cnt"] > 0].groupby(["blk_cd", "slot"])["night"].nunique().unstack(fill_value=0)
    an = an.reindex(columns=range(len(NC.SLOTS)), fill_value=0)
    share = an / np.maximum(nights, 1)
    active = share >= PM.ACTIVE_NIGHT_SHARE.value
    bxy = blocks.loc[share.index, ["x", "y"]].to_numpy()
    cxy = cells[["x", "y"]].to_numpy()
    A_d = np.full((len(NC.SLOTS), len(cells)), 5000.0)
    for s in range(len(NC.SLOTS)):
        on = active[s].to_numpy()
        if on.any():
            A_d[s] = cKDTree(bxy[on]).query(cxy)[0]
    note("anchor_active", f"과반 밤 규칙(≥{PM.ACTIVE_NIGHT_SHARE.value})으로 '문 연 블록'",
         앵커블록=len(share), 금23시=int(active[NC.slot_index(4, 23)].sum()),
         화01시=int(active[NC.slot_index(1, 1)].sum()))

    # 방문 결제: 앵커·유흥을 뺀 업종의 밤 1회 평균 건수 → 셀 반경 100m 합
    v = c[c["kind"] == "visit"].groupby(["blk_cd", "slot"])["cnt"].sum().unstack(fill_value=0)
    v = v.reindex(columns=range(len(NC.SLOTS)), fill_value=0).div(np.maximum(nights, 1), axis=1)
    vt = cKDTree(blocks.loc[v.index, ["x", "y"]].to_numpy())
    near = vt.query_ball_point(cxy, PM.ANCHOR_R_M.value)
    vv = v.to_numpy()
    V = np.zeros((len(NC.SLOTS), len(cells)))
    for i, lst in enumerate(near):
        if lst:
            V[:, i] = vv[lst].sum(axis=0)

    # 유흥 — 점수에는 안 들어간다. 필터를 빼면 무엇이 1등이 되는지 보고용
    nlb = c[c["kind"] == "nightlife"].groupby("blk_cd")["cnt"].sum()
    alb = c[c["kind"] == "anchor"].groupby("blk_cd")["cnt"].sum()
    allb = pd.concat([nlb.rename("nl"), alb.rename("an")], axis=1).fillna(0)
    top = allb.assign(t=allb.nl + allb.an).nlargest(max(1, len(allb) // 100), "t")
    note("nightlife_filter", "필터 없이 심야 결제 건수 상위 1% 블록을 보면", 블록=len(top),
         유흥이더많은블록=int((top.nl > top.an).sum()))

    # DS-048: 앵커 중분류 가맹점 실재 · 휴업 (블록 단위, 대민개방)
    m = read("tbsh_gyeonggi_mer_s", lower=True, dtype={"admi_cty_no": str, "blk_cd": np.int64})
    m = m[ansan(m["admi_cty_no"])]
    mid = sorted(c.loc[c["kind"] == "anchor", "card_tpbuz_nm_2"].unique())
    ma = m[m["card_tpbuz_nm_2"].isin(mid)].groupby("blk_cd")[["entp_cnt", "mer_cnt", "fran_cnt", "stop_cnt"]].sum()
    ma["merchants"] = ma["entp_cnt"] + ma["mer_cnt"]
    ab = share.index
    no48 = int((~ab.isin(ma.index)).sum())
    note("ds048_cross", "DS-054 앵커 블록이 DS-048 에도 있는가(실재 교차검증)", 앵커블록=len(ab),
         DS048에없는블록=no48, 앵커중분류=mid)
    note("ds048_nm2", "DS-048 은 중분류까지만 — 편의점과 슈퍼마켓이 '종합소매점'으로 섞인다",
         중분류=",".join(mid))
    out = pd.DataFrame({"blk_cd": ab, "x": bxy[:, 0], "y": bxy[:, 1],
                        "lon": blocks.loc[ab, "lon"].to_numpy(), "lat": blocks.loc[ab, "lat"].to_numpy()})
    out = out.join(ma[["merchants", "fran_cnt", "stop_cnt"]], on="blk_cd").fillna(0)
    sh = share.round(3)
    sh.columns = [f"s{i}" for i in range(len(NC.SLOTS))]
    out = out.join(sh, on="blk_cd")
    return V, A_d, out, c


def attach_names(ab):
    """앵커 블록에 실제 상가 이름(소상공인 상가정보, 실데이터)을 붙인다 — 블록 안 어느 가게인지는 모른다."""
    a = pd.read_csv(PROC / "anchors.csv", encoding="utf-8-sig")
    a = a[a["kind"] == "앵커"]
    sys.path.insert(0, str(ROOT / "src"))
    import synth_inventory as SY                                       # 같은 임의 블록 규칙
    a["blk_cd"] = SY.block_of(a["lon"], a["lat"])
    names = a.groupby("blk_cd").apply(lambda g: " · ".join(f"{n}({b})" for n, b in zip(g["name"], g["biz"]))[:120],
                                      include_groups=False)
    ab["names"] = ab["blk_cd"].map(names).fillna("")
    ab["dong"] = ab["blk_cd"].map(a.groupby("blk_cd")["dong"].first()).fillna("")
    return ab


# ══ 4. 동 곡선 (DS-014, 대민개방 — 시민 화면에 숫자를 그대로 낼 수 있는 유일한 유동인구) ══════════
def dong_curve():
    log("\n[4] DS-014 동 × 시각 유동인구 곡선")
    ages = [a for a in PM.FLOW_AGE.value]
    cols = [f"{s}_{a}_CNT" for s in "MF" for a in ages]
    d = read("T22_GG_ADMI_FLOWPOP", usecols=["ADMI_CD", "ADMI_NM", "TIME_CD", "FORN_GB", "ETL_YMD"] + cols,
             dtype={"ADMI_CD": str, "ETL_YMD": str, **{c: float for c in cols}})
    vals = sorted(d["FORN_GB"].astype(str).unique().tolist())
    d = d[ansan(d["ADMI_CD"]) & ~d["ADMI_NM"].isin(PM.EXCLUDE_DONG.value)]
    n_all = len(d)
    d = d[d["FORN_GB"] == "N"]
    note("forn_gb", "FORN_GB 'N'(내국인)만 — 'F'·국적코드까지 더하면 이중계산", 값=vals,
         남은행=len(d), 버린행=n_all - len(d))
    d["pop"] = d[cols].sum(axis=1)
    d["night"] = night_of(d["ETL_YMD"], d["TIME_CD"])
    d["dow"] = np.where(d["TIME_CD"] < 6, d["night"].dt.weekday, pd.to_datetime(d["ETL_YMD"]).dt.weekday)
    cur = d.groupby(["ADMI_NM", "dow", "TIME_CD"])["pop"].mean().reset_index()
    cur.columns = ["dong", "dow", "hour", "pop_20_54"]
    cur.to_csv(OUTP / "dong_curve.csv", index=False, encoding="utf-8-sig")
    return cur


# ══ 5. 밤 도보 귀가 OD (DS-004 동 OD × DS-001 구 시간·수단 비율) ═══════════════════
def od_night(dongs24):
    log("\n[5] 밤 도보 귀가 OD — DS-004(동 × 목적, 시간 없음) × DS-001(구 × 시간 × 수단)")
    ta = {}
    a = read("T13_GG_PURPOSE_SEXAGE_ADMI_OD",
             usecols=["ETL_YMD", "O_ADMI_CD", "O_ADMI_NM", "D_ADMI_CD", "D_ADMI_NM", "PURPOSE", "CNT"],
             dtype={"ETL_YMD": str, "O_ADMI_CD": str, "D_ADMI_CD": str, "CNT": float},
             keep=tally_keep(lambda d: ansan(d["O_ADMI_CD"]) & ansan(d["D_ADMI_CD"]),
                             lambda d: (d["PURPOSE"] == 0).to_numpy(), ta))
    note("ds004_ext", "출발·도착 모두 안산인 행만", 버린행=ta.get("out", 0), 남은행=ta.get("in", 0))
    a = a.copy()
    a["dow"] = pd.to_datetime(a["ETL_YMD"]).dt.weekday
    ndays = a.groupby("dow")["ETL_YMD"].nunique()
    day_od = a.groupby(["O_ADMI_NM", "D_ADMI_NM", "dow"])["CNT"].sum() / ndays.reindex(range(7)).fillna(1)
    day_od = day_od.dropna()

    tb = {}
    b = read("T25_GG_PURPOSE_TRANS_SEXAGE_SGG_OD",
             usecols=["ETL_YMD", "O_TIME_CD", "O_CTY_CD", "D_CTY_CD", "PURPOSE", "TRANS_GB", "CNT"],
             dtype={"ETL_YMD": str, "O_CTY_CD": str, "D_CTY_CD": str, "CNT": float},
             keep=tally_keep(lambda d: ansan(d["O_CTY_CD"]) & ansan(d["D_CTY_CD"]),
                             lambda d: (d["PURPOSE"] == 0).to_numpy(), tb))
    note("ds001_ext", "구 OD 도 안산↔안산만", 버린행=tb.get("out", 0))
    b = b.copy()
    day_tot = b.groupby("ETL_YMD")["CNT"].sum()                       # 그날 귀가 통행 전체(출발시각 기준)
    nb = b[b["O_TIME_CD"].isin(NIGHT)].copy()
    nd = night_of(nb["ETL_YMD"], nb["O_TIME_CD"])
    nb["slot"] = slot_of(nd, nb["O_TIME_CD"].to_numpy())
    nb["eve"] = nd.dt.strftime("%Y%m%d").to_numpy()
    nb = nb[nb["eve"].isin(day_tot.index)]                             # 그 밤의 저녁 날짜가 자료에 있어야 비율이 된다
    g = nb.groupby(["slot", "eve"])
    share = (g["CNT"].sum() / day_tot.reindex(g["CNT"].sum().index.get_level_values(1)).to_numpy()).groupby(level=0).mean()
    walk = (nb[nb["TRANS_GB"] == 3].groupby("slot")["CNT"].sum() / nb.groupby("slot")["CNT"].sum())
    note("ds001_profile", "구 단위 '하루 귀가 중 그 시각 비율' × '그 시각 귀가 중 도보 비율'",
         금23시_비율=round(float(share.get(NC.slot_index(4, 23), np.nan)), 4),
         화01시_비율=round(float(share.get(NC.slot_index(1, 1), np.nan)), 4),
         도보비율_범위=f"{walk.min():.2f}~{walk.max():.2f}")
    rows = []
    for s in range(len(NC.SLOTS)):
        d, _ = NC.SLOTS[s]
        f = float(share.get(s, 0.0)) * float(walk.get(s, 0.0))
        part = day_od.xs(d, level="dow") * f if d in day_od.index.get_level_values("dow") else None
        if part is None:
            continue
        p = part.reset_index()
        p.columns = ["o_dong", "d_dong", "trips"]
        p["slot"] = s
        rows.append(p)
    od = pd.concat(rows, ignore_index=True)
    od = od[od["o_dong"].isin(dongs24) & od["d_dong"].isin(dongs24)]
    od.to_csv(OUTP / "od_night.csv", index=False, encoding="utf-8-sig")
    note("od_night", "동 쌍 × 시간대 밤 도보 귀가 통행(독립 가정의 곱 — DS-004 에 시간·수단이 없어서)",
         행=len(od), 동쌍=int(od.groupby(["o_dong", "d_dong"]).ngroups))
    return od


# ══ 6. 보안등 · CCTV (공공데이터 표준 규격) ═════════════════════════════
def points(stem, lat_col, lon_col, keep):
    d = read(stem)
    d = d.dropna(subset=[lat_col, lon_col])
    g = gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d[lon_col].astype(float), d[lat_col].astype(float)),
                         crs=4326).to_crs(5179)
    out = d[keep].copy()
    out["lon"], out["lat"] = d[lon_col].astype(float).to_numpy(), d[lat_col].astype(float).to_numpy()
    out["x"], out["y"] = g.geometry.x.to_numpy(), g.geometry.y.to_numpy()
    return out


def output_for(raw):
    """입력 폴더 → (입력, 출력 폴더, 민간 실데이터인가). 임의값 폴더가 아니면 data/real/proto(#19)."""
    r = (pathlib.Path(raw) if raw else SYN_RAW).resolve()
    priv = r != SYN_RAW.resolve()
    return r, (REAL_OUT if priv else ROOT / "data" / "proto"), priv


def main(raw=None):
    global RAW, OUTP
    RAW, OUTP, priv = output_for(raw)
    t0 = time.time()
    OUTP.mkdir(parents=True, exist_ok=True)
    log(f"[1] 입력 {RAW} → 출력 {OUTP}" + ("  ★ 민간 실데이터 — 이 PC 밖으로 내보내지 않는다" if priv else ""))
    cells, nodes, edges, dong = load_base()
    cxy = cells[["x", "y"]].to_numpy()
    pairs = cKDTree(cxy).query_pairs(PM.ANCHOR_R_M.value + 1e-6, output_type="ndarray")
    n = len(cells)
    nbr = csr_matrix((np.ones(len(pairs) * 2 + n), (np.r_[pairs[:, 0], pairs[:, 1], np.arange(n)],
                                                     np.r_[pairs[:, 1], pairs[:, 0], np.arange(n)])), shape=(n, n))
    log(f"    셀 {n:,} · 반경 {PM.ANCHOR_R_M.value}m 이웃 평균 {nbr.sum(1).mean():.1f}칸 · 노드 {len(nodes):,} · 간선 {len(edges):,}")

    R, res_share, res = term_R(cells, nbr)
    P, run = term_P(cells) if priv else (None, None)                   # DS-032 — 있으면 유동 항을 대체(FLOW_FORM · #20)
    (OUTP / "run_terms.npz").unlink(missing_ok=True)                   # 지난 적재의 러닝 시간대가 남지 않게
    if run is not None:                                                # 러닝 새벽 · 저녁(#35) — 실데이터 판 앱만 읽는다
        np.savez_compressed(OUTP / "run_terms.npz", P=run["P"], bands=np.array(run["bands"]),
                            hours=json.dumps(run["hours"]))
    if has_blocks():                                                   # 임의값 세계 — 블록 좌표가 있다
        blocks = load_blocks()
        V, A_d, ab, card = term_card(cells, blocks)
        ab = attach_names(ab)
    else:                                                              # 실물 — 블록 좌표표가 없다(#19)
        V, A_d, ab = public_anchors(cells)
    ab.to_csv(OUTP / "anchor_blocks.csv", index=False, encoding="utf-8-sig")
    extra = {"masked": mask_cells(res)} if priv else {}                # 화면 가림(#19) — 실데이터 판만
    if P is not None:
        extra["P"] = P
    np.savez_compressed(OUTP / "terms.npz", R=R, V=V, A_d=A_d, res_share=res_share, **extra)

    # FLOW_FORM 효과 — 주민 보행만 쓰면 앵커 셀이 얼마나 하위로 떨어지는가 (임의값 기준, 구조 확인용)
    pR = NC._pct_min(R)
    pF = NC._pct_avg(np.maximum(pR, NC._pct_min(V)) if P is None else NC._pct_min(P))
    near_anchor = A_d <= PM.ANCHOR_R_M.value
    note("flow_form", "문 연 앵커가 100m 안인 셀-시간대 중 유동 하위 25% 비율 "
         + (("(실데이터 — 유동 = DS-032 50m 유동인구)" if P is not None else "(실데이터 — 카드 방문 결제 없음, 주민 보행만)")
            if priv else "(임의값 — 구조 확인용)"),
         주민보행만=f"{np.mean(pR[near_anchor] < .25):.1%}",
         **{("DS032" if P is not None else "max보정"): f"{np.mean(pF[near_anchor] < .25):.1%}"},   # 임의값 기록은 이름 그대로
         대상=int(near_anchor.sum()))

    dong_curve()
    od = od_night(sorted(cells["dong"].unique()))

    log("\n[6] 보안등 · CCTV · 지구대 · 역 (공개 실데이터 — 인벤토리 밖, 수정사항 #15)")
    import public_data as PD
    if PD.available():
        pr = PD.export_proto(OUTP)                                     # data/public/derived → data/proto
        note("facilities", "공개 실데이터(data/public) — 보안등 · 역 하차는 실데이터, CCTV · 비상벨은 공개분 일부(표시만)",
             보안등=pr["lights"]["동안"], CCTV=pr.get("CCTV_partial", {}).get("동안", 0),
             비상벨=pr.get("비상벨_partial", {}).get("동안", 0), 지구대파출소=pr["police"]["밤에열린곳"],
             역=len(pr["stations"]["역별"]))
    else:                                                              # 공개 원본이 없으면 예전처럼 임의값
        lights = points("전국보안등정보표준데이터", "위도", "경도", ["보안등위치명", "설치개수", "설치형태", "설치연도"])
        cctv = points("전국CCTV표준데이터", "WGS84위도", "WGS84경도", ["설치목적구분", "카메라대수"])
        lights.to_csv(OUTP / "lights.csv", index=False, encoding="utf-8-sig")
        cctv.to_csv(OUTP / "cctv.csv", index=False, encoding="utf-8-sig")
        for f in PD.PROTO_FILES[2:]:                                   # 실데이터 전용 파일은 지운다(섞이지 않게)
            (OUTP / ("public_report.json" if f == "report.json" else f)).unlink(missing_ok=True)
        note("facilities", "공공데이터 표준 규격(임의값) — data/public 원본 없음(python src/collect_public.py)",
             보안등=len(lights), CCTV=len(cctv))

    log("\n[7] 귀가 통행 표본 경로 (개선 우선 구간)")
    G = NC.NightGraph(nodes, edges)
    terms = {"R": R, "V": V}
    if P is not None:                                                  # 출발 칸 = 밤에 사람이 나와 있는 곳(DS-032)
        terms["O"] = P
    T, inc, W = NC.build_trips(G, cells, od, terms, res_share, log=log)
    save_npz(OUTP / "trips_inc.npz", inc)
    np.savez_compressed(OUTP / "trips.npz", W=W, o_node=T["o_node"].to_numpy(), d_node=T["d_node"].to_numpy(),
                        len_m=T["len_m"].to_numpy(), o_dong=T["o_dong"].to_numpy(), d_dong=T["d_dong"].to_numpy())

    # 가상 세계 정답과 대조 (임의값일 때만 — 실데이터에는 정답이 없다)
    lat = ROOT / "data" / "synthetic" / "latent" / "shops_latent.csv"
    if lat.exists() and not priv:
        check_latent(ab, lat)

    import re
    months = sorted({m for p in RAW.glob("*.csv*") for m in re.findall(r"_(20\d{4})(?=[_.-])", p.name)})
    REP["_meta"] = {"raw": str(RAW), "sec": round(time.time() - t0, 1), "slots": len(NC.SLOTS),
                    "cells": n, "synthetic": not priv}
    if priv:
        REP["_meta"].update(private=True, months=months, out=str(OUTP))
    (OUTP / "ingest_report.json").write_text(json.dumps(REP, ensure_ascii=False, indent=2, default=str),
                                             encoding="utf-8")
    log(f"\n[v] {OUTP.relative_to(ROOT)} 완료 ({REP['_meta']['sec']}초)")


def check_latent(ab, path):
    """'과반 밤' 규칙이 가상 세계의 실제 영업과 얼마나 맞는가 — 블록 × 시간대 단위."""
    import synth_inventory as SY
    s = pd.read_csv(path, encoding="utf-8-sig")
    s = s[s["grp"].isin(["cvs", "gas", "pc"]) & ~s["dead"]]
    truth = np.zeros((len(ab), len(NC.SLOTS)), bool)
    bi = pd.Series(np.arange(len(ab)), index=ab["blk_cd"])
    s = s[s["blk_cd"].isin(bi.index)]
    for si, (_, h) in enumerate(NC.SLOTS):
        op = SY.is_open(s["close_h"].to_numpy(), h)
        blk = s.loc[op, "blk_cd"].unique()
        truth[bi[blk].to_numpy(), si] = True
    pred = ab[[f"s{i}" for i in range(len(NC.SLOTS))]].to_numpy() >= PM.ACTIVE_NIGHT_SHARE.value
    tp = int((pred & truth).sum())
    note("latent_check", "임의값 세계의 실제 영업 대비 '문 연 블록' 판정 (적재 코드 검증)",
         정밀도=f"{tp / max(pred.sum(), 1):.1%}", 재현율=f"{tp / max(truth.sum(), 1):.1%}",
         판정=int(pred.sum()), 정답=int(truth.sum()))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1] if len(sys.argv) > 1 else None)
