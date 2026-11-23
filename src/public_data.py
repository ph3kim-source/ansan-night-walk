# -*- coding: utf-8 -*-
"""
공개 실데이터 정제 — data/public/raw → data/public/derived (수정사항 #15)
실행:  python src/collect_public.py   # 원본 받기 (네트워크)
       python src/public_data.py      # 정제 (오프라인, 30초 남짓)

만드는 것 (data/public/derived/)
  lights.csv       안산시 보안등 — 24개 동 안 · 좌표 · 동 · 같은 좌표 묶음 번호(loc)
  cctv.csv         CCTV 공개분(일부) — 지도 표시용. 계산에 쓰지 않는다(params.FACILITY_PARTIAL)
  bells.csv        비상벨 공개분(일부) — 지도 표시용
  police.csv       지구대 · 파출소 · 경찰서 · 치안센터(OSM). night_open = params.POLICE_NIGHT
  stations.csv     역 × 밤 하차(22시 · 23시 · 24시 이후, 하루 평균) · 반경 1km 거주 · 종사자 · 산업단지역 판정
  edge_public.csv  보행망 간선별(data/processed/edges.csv 행 순서 그대로) — 도로 등급 · 보안등 수 · 밤 역 귀갓길 흐름
                   · sidewalk(OSM 에 차도 옆 보도로 따로 그린 길, #26)
  accidents.csv    교통사고 다발지역(한국도로교통공단 표준데이터) — 안산 행 · 유형 · 연도 · 건수 · 중심 · 범위 고리(위경도, #26)
  report.json      판정 + 근거 원자료 (CLAUDE.md §7 — 판정 줄마다 원자료를 같이 남긴다)

밤 역 귀갓길 흐름(f22 · f23 · f24, 사람/밤)
  역(산업단지역 제외)마다 밤 하차 인원을 → 그 역이 가장 가까운(보행망 거리) 집들에 거주 규모만큼 나누고
  → 최단 경로로 걸어간다고 보고 간선마다 지나는 사람 수를 더한다. 내린 사람이 전부 걸어서 집에 간다는 가정이라
  절대값이 아니라 상대 지수로만 쓴다. 가중치는 없다(나눔 비율 = 거주 규모 그대로).

해 지는 시각은 자료가 아니라 계산이다(sun_times — NOAA 태양 위치 식, 오차 1~2분).
"""
import calendar
import datetime
import io
import json
import math
import pathlib
import re
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "public" / "raw"
DER = ROOT / "data" / "public" / "derived"
PROC = ROOT / "data" / "processed"
BASE = ROOT / "data" / "base"
sys.path.insert(0, str(ROOT / "src"))
import params as PM  # noqa: E402

REP = {}
_DONG = None


def log(m):
    print(m, flush=True)


def note(key, verdict, **raw):
    """판정 한 줄 + 근거 원자료."""
    REP[key] = {"verdict": verdict, **{k: (v.item() if hasattr(v, "item") else v) for k, v in raw.items()}}
    log(f"    · {verdict}  " + " ".join(f"{k}={v}" for k, v in raw.items()))


def available():
    """원본이 다 있는가 — 없으면 ingest 가 임의값으로 돌아간다."""
    need = ["보안등_경기도안산시.csv", "osm_police_fire.json", "osm_stations.json"]
    return all((RAW / n).exists() for n in need) and bool(list(RAW.glob("korail_시간대별승하차_*.xlsx")))


def read_csv(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            raw.decode(enc)
        except UnicodeDecodeError:
            continue
        return pd.read_csv(io.BytesIO(raw), encoding=enc, dtype=str)
    raise ValueError(f"인코딩을 모르는 파일: {path}")


def dong():
    import geopandas as gpd
    global _DONG
    if _DONG is None:
        _DONG = gpd.read_file(PROC / "dong.geojson").to_crs(5179)[["ADM_NM", "geometry"]]
    return _DONG


def points(df, lat, lon):
    """위경도 → x · y(EPSG:5179) · 동. 3안 24개 동 밖(대부동 · 인접 시)은 버린다. → (안쪽 표, 버린 행 수)"""
    import geopandas as gpd
    d = df.copy()
    d["lat"] = pd.to_numeric(d[lat], errors="coerce")
    d["lon"] = pd.to_numeric(d[lon], errors="coerce")
    d = d.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    g = gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d["lon"], d["lat"]), crs=4326).to_crs(5179)
    g["x"], g["y"] = g.geometry.x.to_numpy(), g.geometry.y.to_numpy()
    j = gpd.sjoin(g, dong(), predicate="within", how="left")
    j = j[~j.index.duplicated()]
    out = int(j["ADM_NM"].isna().sum())
    j = j[j["ADM_NM"].notna()].rename(columns={"ADM_NM": "dong"})
    return pd.DataFrame(j.drop(columns=["geometry", "index_right"])).reset_index(drop=True), out


# ══ 시설 ═══════════════════════════════════════════════════════════
def lights():
    d0 = read_csv(RAW / "보안등_경기도안산시.csv")
    d, out = points(d0, "위도", "경도")
    key = np.round(d[["x", "y"]].to_numpy()).astype(np.int64)
    d["loc"] = pd.factorize(pd.Series([f"{a}_{b}" for a, b in key]))[0]
    keep = ["보안등위치명", "설치형태", "설치연도", "관리기관명", "데이터기준일자", "lon", "lat", "x", "y", "dong", "loc"]
    d = d[keep]
    note("lights", "안산시 보안등 — 24개 동 안만(대부동 · 경계 밖 제외)", 원행=len(d0), 동안=len(d), 버림=out,
         고유위치=int(d["loc"].nunique()), 기준일=",".join(sorted(d["데이터기준일자"].dropna().unique())),
         관리기관=d["관리기관명"].value_counts().to_dict())
    by = d["dong"].value_counts()
    missing = sorted(set(dong()["ADM_NM"]) - set(by.index))
    note("lights_by_dong", "동별 보안등 수 — 큰길 가로등 · 아파트 단지 조명은 이 자료에 없다", 없는동=missing,
         적은동=by.nsmallest(4).to_dict(), 많은동=by.nlargest(3).to_dict())
    return d


def facility(label, keep):
    """CCTV · 비상벨 공개분 — 표시용."""
    d0 = read_csv(RAW / f"{label}_표준데이터_안산.csv")
    d, out = points(d0, "위도", "경도")
    d = d[[c for c in keep if c in d.columns] + ["lon", "lat", "x", "y", "dong"]]
    by = d["dong"].value_counts()
    top = by.head(7)
    note(f"{label}_partial", f"{label} 공개분 — 일부만 들어 있다(계산 제외, 표시만)", 원행=len(d0), 동안=len(d),
         상위7개동비중=f"{top.sum() / max(len(d), 1):.1%}", 상위7개동=top.to_dict(), 없는동수=int(24 - len(by)),
         관리기관=d0["관리기관명"].value_counts().to_dict() if "관리기관명" in d0 else {})
    return d


def police():
    el = json.loads((RAW / "osm_police_fire.json").read_text(encoding="utf-8"))["elements"]
    rows = []
    for e in el:
        t = e.get("tags", {})
        if t.get("amenity") != "police" or not t.get("name"):
            continue
        c = e.get("center", {})
        rows.append({"osm": f"{e['type']}/{e['id']}", "name_raw": t["name"],
                     "lat": e.get("lat", c.get("lat")), "lon": e.get("lon", c.get("lon"))})
    d, out = points(pd.DataFrame(rows), "lat", "lon")
    short = d["name_raw"].str.replace(r"^(경기\s*)?안산(상록|단원)경찰서\s*", "", regex=True).str.replace(" ", "")
    d["name"] = np.where(short == "", d["name_raw"].str.replace(" ", ""), short)
    d["kind"] = np.select([d["name"].str.contains("지구대"), d["name"].str.contains("파출소"),
                           d["name"].str.contains("치안센터"), d["name"].str.contains("경찰서")],
                          ["지구대", "파출소", "치안센터", "경찰서"], "기타")
    n_all = len(d)
    d = d.drop_duplicates("name").reset_index(drop=True)
    d["night_open"] = d["kind"].isin(PM.POLICE_NIGHT.value)
    note("police", f"OSM 경찰 시설 — 밤에 열린 곳 = {'·'.join(PM.POLICE_NIGHT.value)}", 동안=n_all,
         같은이름중복제거=n_all - len(d), 종류=d["kind"].value_counts().to_dict(), 밤에열린곳=int(d["night_open"].sum()))
    return d[["name", "kind", "night_open", "osm", "lon", "lat", "x", "y", "dong"]]


# ══ 역 · 밤 하차 ═════════════════════════════════════════════════════
def korail_hourly(path):
    """코레일 '광역철도 시간대별 승하차인원' 엑셀 → (역별 긴 표, (년, 월), 노선 합계 표)."""
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    ym = None
    for r in rows[:6]:
        for v in r or ():
            m = re.search(r"(\d{4})년\s*(\d{1,2})월", str(v or ""))
            if m:
                ym = (int(m.group(1)), int(m.group(2)))
                break
        if ym:
            break
    heads = [i for i, r in enumerate(rows) if r and r[0] == "노선명"]

    def table(i, has_station):
        H, recs, line, stn = rows[i], [], None, None
        for r in rows[i + 1:]:
            if not r or r[0] == "노선명":
                break
            if all(v is None for v in r[:4]):
                continue
            line = r[0] or line
            if has_station:
                # 노선마다 끝에 역명이 빈 '노선 소계' 두 행이 있다. 빈칸을 직전 역명으로 채우면 소계가 마지막 역
                # (서해선이면 원시역)으로 붙는다 — 실제로 그렇게 틀렸다(수정사항 #15). 역별 표에서는 건너뛴다
                if r[1] is None:
                    continue
                stn = r[1]
            if r[2] not in ("승차", "하차"):
                continue
            recs.append({"line": line, "station": stn, "kind": r[2],
                         **{str(H[j]).strip(): r[j] for j in range(3, len(H)) if H[j]}})
        return pd.DataFrame(recs)

    by_line = table(heads[0], False)
    by_stn = table(heads[-1], True)
    return by_stn, ym, by_line


def _grid():
    import geopandas as gpd
    g = gpd.read_file(BASE / "grid_1km.geojson")
    g.columns = ["GRID_CD", "ADM_CD", "ADM_NM", "pop", "mfg", "geometry"]
    g = g.to_crs(5179)
    g["a0"] = g.area
    return g


def stations():
    path = sorted(RAW.glob("korail_시간대별승하차_*.xlsx"))[-1]
    k, (yy, mm), by_line = korail_hourly(path)
    days = calendar.monthrange(yy, mm)[1]
    cols = PM.STATION_NIGHT_COLS.value
    # 칸 정의 확인 — '시작 시각' 기준이면 24시 이후 승차가 23시 승차보다 훨씬 작아야 한다
    tot = by_line[(by_line["line"] == by_line["line"].iloc[0]) & (by_line["kind"] == "승차")].iloc[0]
    note("korail_cols", "칸 이름 = 시작 시각(22시 = 22:00~22:59) · '24시 이후' = 0 · 1시 합", 노선=tot["line"],
         승차_22시=int(tot["22시"]), 승차_23시=int(tot["23시"]), 승차_24시이후=int(tot["24시 이후"]))
    # 파서 검증 — 역별 하차 합이 노선 합계와 같아야 한다. 소계 행이 역으로 섞이면 2배가 된다
    chk = []
    for ln, g in k[k["kind"] == "하차"].groupby("line"):
        lt = by_line[(by_line["line"] == ln) & (by_line["kind"] == "하차")]
        if len(lt):
            chk.append((ln, int(pd.to_numeric(g["합계"]).sum()), int(lt["합계"].iloc[0])))
    bad = [c for c in chk if c[1] != c[2]]
    note("korail_check", "역별 하차 합 = 노선 합계 (파서 검증)", 노선=len(chk), 불일치=bad,
         예=[c for c in chk if c[0] in ("안산선", "서해선")])
    if bad:
        raise SystemExit(f"[X] 코레일 표 파싱이 어긋남: {bad}")

    el = json.loads((RAW / "osm_stations.json").read_text(encoding="utf-8"))["elements"]
    o = pd.DataFrame([{"osm_id": e["id"], "name": e["tags"].get("name"), "lat": e["lat"], "lon": e["lon"],
                       "subway": e["tags"].get("subway") == "yes"} for e in el if e.get("tags", {}).get("name")])
    o, _ = points(o.drop_duplicates("osm_id"), "lat", "lon")
    rows = []
    for r in k.to_dict("records"):               # itertuples 는 '22시' 같은 컬럼명을 위치 이름으로 바꾼다
        nm = re.sub(r"\(.*\)$", "", str(r["station"]))
        cand = o[o["name"] == nm]
        if cand.empty:
            continue
        if len(cand) > 1:                         # 초지처럼 노선마다 승강장이 따로 — 서해선 = subway 태그 없는 쪽
            pick = cand["subway"] != (r["line"] == "서해선")
            cand = cand[pick] if pick.any() else cand
        s = cand.iloc[0]
        rows.append({"station": r["station"], "line": r["line"], "kind": r["kind"], "osm_id": s.osm_id,
                     "lon": s.lon, "lat": s.lat, "x": s.x, "y": s.y, "dong": s.dong,
                     **{f"v{h}": float(r[c] or 0) / days for c, h in [("21시", 21)] + list(cols.items())},
                     "day": float(r["합계"] or 0) / days})
    t = pd.DataFrame(rows)
    al = t[t["kind"] == "하차"].drop(columns="kind").rename(columns={"v21": "a21", "v22": "a22", "v23": "a23", "v0": "a24"})
    bo = t[t["kind"] == "승차"].set_index(["line", "station"])
    st = al.set_index(["line", "station"])
    st["b22"], st["b23"], st["b24"] = bo["v22"], bo["v23"], bo["v0"]
    st = st.rename(columns={"day": "a_day"}).reset_index()
    st["night"] = st["a22"] + st["a23"] + st["a24"]
    st["month"] = f"{yy}-{mm:02d}"

    # 산업단지역 — 반경 r 안 제조업 종사자 > 거주인구 (SGIS 1km 격자, 면적 비례)
    rule = PM.INDUSTRIAL_STATION.value
    g = _grid()
    import geopandas as gpd
    ring = gpd.GeoSeries(gpd.points_from_xy(st["x"], st["y"]), crs=5179).buffer(rule["r_m"])
    st["pop_r"] = [float((g["pop"] * g.intersection(c).area / g["a0"]).sum()) for c in ring]
    st["mfg_r"] = [float((g["mfg"] * g.intersection(c).area / g["a0"]).sum()) for c in ring]
    st["industrial"] = st["mfg_r"] > st["pop_r"]
    ind = st[st["industrial"]]
    note("stations", f"코레일 {yy}년 {mm}월 · 안산 24개 동 안 역 {len(st)}곳(노선별) · 밤(22시~막차) 하차 하루 평균",
         밤하차합=round(float(st["night"].sum())), 역별=st.set_index("station")["night"].round().astype(int).to_dict())
    note("industrial", f"산업단지역(반경 {rule['r_m']}m 제조업 종사자 > 거주인구) — 귀갓길 계산에서 뺀다",
         역=ind["station"].tolist(), 밤하차=ind["night"].round().astype(int).tolist(),
         거주=ind["pop_r"].round().astype(int).tolist(), 종사자=ind["mfg_r"].round().astype(int).tolist(),
         비중=f"{ind['night'].sum() / st['night'].sum():.1%}",
         나머지_거주대비종사자_최대=f"{(st.loc[~st['industrial'], 'mfg_r'] / st.loc[~st['industrial'], 'pop_r']).max():.2f}")
    return st


# ══ 간선 속성 ═════════════════════════════════════════════════════════
def edge_road(nodes, edges):
    """간선별 OSM highway — osm.build_graph 와 같은 좌표 반올림으로 way 를 간선에 다시 붙인다(edges.csv 는 그대로).
    + sidewalk: OSM 에서 차도 옆 보도로 따로 그린 길(highway=footway · footway=sidewalk) — #26. 큰길 · 골목에 보도가 있는지는
      OSM 에 거의 없다(sidewalk 태그 길이 2km 남짓) — 보도로 '따로 그린' 길만 안다."""
    import osm
    w = osm.load_ways(ROOT / "data" / "raw" / "ansan_walk.geojson", dong(), log=lambda m: None)
    fw = w["footway"].astype(str).to_numpy() if "footway" in w.columns else np.full(len(w), "nan", dtype=object)
    snap = PM.SNAP_M.value
    best = {}
    for geom, hw, f in zip(w.geometry.values, w["highway"].astype(str).to_numpy(), fw):
        c = np.round(np.asarray(geom.coords)[:, :2] / snap).astype(np.int64)
        for (ax, ay), (bx, by) in zip(c[:-1], c[1:]):
            if ax == bx and ay == by:
                continue
            k = (min((ax, ay), (bx, by)), max((ax, ay), (bx, by)))
            ln = math.hypot(ax - bx, ay - by)
            if k not in best or ln < best[k][0]:
                best[k] = (ln, hw, hw == "footway" and f == "sidewalk")
    q = np.round(nodes[["x", "y"]].to_numpy() / snap).astype(np.int64)
    hw, side = [], []
    for u, v in zip(edges["u"].to_numpy(), edges["v"].to_numpy()):
        a, b = tuple(q[u]), tuple(q[v])
        r = best.get((min(a, b), max(a, b)), (0, "unknown", False))
        hw.append(r[1])
        side.append(r[2])
    hw, side = np.array(hw, dtype=object), np.array(side, dtype=bool)
    major = np.isin(hw, PM.MAJOR_ROAD.value)
    L = edges["len_m"].to_numpy()
    note("edge_road", "간선 도로 등급 — 큰길(가로등 구간)과 골목을 가른다", 간선=len(hw),
         태그못붙인간선=int((hw == "unknown").sum()), 큰길길이=f"{L[major].sum() / L.sum():.1%}",
         등급별길이km={k: round(float(L[hw == k].sum()) / 1000, 1) for k in pd.Series(hw).value_counts().index[:10]})
    cf = np.isin(hw, PM.RUN_CAR_FREE_HW.value)
    note("edge_sidewalk", "OSM 에 차도 옆 보도로 따로 그린 길(footway=sidewalk) — 차 없는 길에서 뺀다(#26)",
         보도km=round(float(L[side].sum()) / 1000, 1), 차없는길km_보도포함=round(float(L[cf].sum()) / 1000, 1),
         보도비중=f"{L[side].sum() / max(L[cf].sum(), 1e-9):.1%}")
    return hw, major, side


def accidents():
    """교통사고 다발지역(한국도로교통공단 표준데이터, #26) — 안산 행 전부. 폴리곤은 EPSG:5179 좌표가 따옴표 없는 JSON 꼴로
    들어 있다 → 숫자만 뽑아 고리로 → 위경도로 바꾼다. 어느 유형 · 연도를 화면에 쓸지는 params.PED_ACC 가 정한다(build_app)."""
    from pyproj import Transformer
    p = RAW / "교통사고다발지역_표준데이터_안산.csv"
    if not p.exists():
        return pd.DataFrame()
    a = read_csv(p)
    tf = Transformer.from_crs(5179, 4326, always_xy=True)
    rings = []
    for s in a["사고다발지역폴리곤정보"].fillna(""):
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", s)]
        xy = np.array(nums[: len(nums) // 2 * 2]).reshape(-1, 2) if len(nums) >= 6 else np.zeros((0, 2))
        if len(xy):
            lo, la = tf.transform(xy[:, 0], xy[:, 1])
            rings.append(json.dumps([[round(y, 6), round(x, 6)] for x, y in zip(lo, la)][::2] or None))   # 점 절반만(둥근 고리)
        else:
            rings.append("")
    out = pd.DataFrame({
        "id": a["사고지역관리번호"].astype(str) + "-" + a["위치코드"].astype(str),
        "year": pd.to_numeric(a["사고연도"]).astype(int), "type": a["사고유형구분"],
        "name": a["사고지역위치명"].str.replace("경기도 안산시 ", "", regex=False),
        "n_acc": pd.to_numeric(a["사고건수"]).astype(int), "n_cas": pd.to_numeric(a["사상자수"]).astype(int),
        "n_dead": pd.to_numeric(a["사망자수"]).astype(int),
        "lat": pd.to_numeric(a["위도"]), "lon": pd.to_numeric(a["경도"]), "ring": rings,
        "ref_date": a["데이터기준일자"]})
    note("accidents", "교통사고 다발지역(도로교통공단) — 안산 행 · 유형 × 연도", 행=len(out),
         유형별={k: int(v) for k, v in out["type"].value_counts().items()},
         최근5년_유형별={k: int(v) for k, v in out[out["year"] >= out["year"].max() - 4]["type"].value_counts().items()},
         연도범위=f"{out['year'].min()}~{out['year'].max()}", 폴리곤없음=int((out["ring"] == "").sum()),
         기준일=str(out["ref_date"].iloc[0]) if len(out) else "")
    return out


def lights_per_edge(nodes, edges, pts_xy, r):
    """간선(선분)에서 r 안에 있는 점 개수 — 간선 중점이 아니라 선분 전체와의 거리."""
    import shapely
    xy = nodes[["x", "y"]].to_numpy()
    lines = shapely.linestrings(np.stack([xy[edges["u"]], xy[edges["v"]]], axis=1))
    tree = shapely.STRtree(lines)
    pts = shapely.points(pts_xy)
    _, d = tree.query_nearest(pts, return_distance=True, all_matches=False)   # 점마다 거리 하나(동률 중복 없이)
    hit = tree.query(shapely.buffer(pts, r), predicate="intersects")
    n = np.bincount(hit[1], minlength=len(edges))
    return n, d


def station_walk(nodes, edges, cells, st, max_m=None, w=None):
    """밤 역 귀갓길 흐름 (3, 간선) 사람/밤 — 22시 · 23시 · 24시 이후. + 역별 요약."""
    from scipy.sparse.csgraph import dijkstra
    import night_core as NC
    import alloc as AL
    max_m = PM.STATION_WALK_MAX_M.value if max_m is None else max_m
    G = NC.NightGraph(nodes, edges)
    use = st[~st["industrial"].astype(bool)].copy()
    if use.empty:
        return np.zeros((3, G.m)), use
    use["node"] = [G.snap(x, y) for x, y in use[["x", "y"]].to_numpy()]
    A = use.groupby("node")[["a22", "a23", "a24"]].sum()
    src = A.index.to_numpy()
    dist, pred, srcs = dijkstra(G._mat(G.length), directed=True, indices=src, return_predecessors=True,
                                min_only=True, limit=max_m)
    w = AL.homes(cells) if w is None else w                     # 집 쪽 규모 = 1km 인구를 OSM 주거건물 비례로
    dc, cn = G.tree.query(cells[["x", "y"]].to_numpy())
    ok = (dc <= PM.NODE_CELL_MAX_M.value) & np.isfinite(dist[cn]) & (w > 0)
    cs = srcs[cn]
    wsum = pd.Series(w[ok]).groupby(cs[ok]).sum()
    D = np.zeros((3, G.n))
    for b, col in enumerate(["a22", "a23", "a24"]):
        np.add.at(D[b], cn[ok], A[col].reindex(cs[ok]).to_numpy() * w[ok] / wsum.reindex(cs[ok]).to_numpy())
    reach = np.flatnonzero(np.isfinite(dist) & (pred >= 0))
    order = reach[np.argsort(-dist[reach], kind="stable")]
    eid = G.edge_of(pred[order], order)
    F = np.zeros((3, G.m))
    for k, nd in enumerate(order):
        F[:, eid[k]] += D[:, nd]
        D[:, pred[nd]] += D[:, nd]
    by = pd.DataFrame({"node": cs[ok], "w": w[ok], "d": dist[cn[ok]]})
    summ = by.groupby("node").apply(lambda g: pd.Series({"cells": len(g), "homes_w": g["w"].sum(),
                                                         "mean_walk_m": np.average(g["d"], weights=g["w"])}),
                                    include_groups=False)
    use = use.join(summ, on="node")
    return F, use


# ══ 해 지는 시각 (NOAA 태양 위치 식) ═══════════════════════════════════════
def sun_times(day, lat, lon, tz=9.0, zenith=90.833):
    """(해 뜨는 시각, 해 지는 시각) — 시(소수). zenith 90.833 = 일출몰, 96 = 시민박명(어두워지는 시각)."""
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    ha = math.degrees(math.acos(math.cos(math.radians(zenith)) / (math.cos(la) * math.cos(decl))
                                - math.tan(la) * math.tan(decl)))
    rise = (720 - 4 * (lon + ha) - eqt) / 60 + tz
    sset = (720 - 4 * (lon - ha) - eqt) / 60 + tz
    return rise, sset


def center_latlon():
    c = dong().to_crs(4326).union_all().centroid
    return c.y, c.x


def hm(h):
    m = int(round(h * 60))
    return f"{m // 60:02d}:{m % 60:02d}"


def sunset_table(year):
    lat, lon = center_latlon()
    out = []
    for mo in range(1, 13):
        d = datetime.date(year, mo, 15)
        _, s = sun_times(d, lat, lon)
        _, dusk = sun_times(d, lat, lon, zenith=96.0)
        out.append({"month": mo, "sunset": hm(s), "dusk": hm(dusk), "h22_after_sunset": round(22 - s, 1)})
    return out


# ══ 빌드 ═══════════════════════════════════════════════════════════
def build():
    if not available():
        raise SystemExit(f"[X] {RAW} 에 원본이 없습니다 — 먼저 python src/collect_public.py")
    DER.mkdir(parents=True, exist_ok=True)
    REP.clear()
    log("[1] 시설")
    L = lights()
    C = facility("CCTV", ["설치목적구분", "카메라대수", "설치연월", "데이터기준일자"]) \
        if (RAW / "CCTV_표준데이터_안산.csv").exists() else pd.DataFrame()
    B = facility("비상벨", ["설치위치", "설치장소유형", "경찰연계유무", "데이터기준일자"]) \
        if (RAW / "비상벨_표준데이터_안산.csv").exists() else pd.DataFrame()
    if len(B) and len(C):
        from scipy.spatial import cKDTree
        bd = cKDTree(C[["x", "y"]].to_numpy()).query(B[["x", "y"]].to_numpy())[0]
        note("bells_cctv", "공개분 비상벨 → 가장 가까운 공개분 CCTV 거리(같은 기둥에 함께 설치된 경우가 많은가)",
             중앙값m=round(float(np.median(bd)), 1), p25m=round(float(np.percentile(bd, 25)), 1))
    Po = police()
    log("[2] 역 · 밤 하차")
    S = stations()
    log("[3] 간선 — 도로 등급 · 보안등 · 밤 역 귀갓길")
    nodes = pd.read_csv(PROC / "nodes.csv", encoding="utf-8-sig")
    edges = pd.read_csv(PROC / "edges.csv")
    cells = pd.read_csv(PROC / "cells.csv", encoding="utf-8-sig")
    hw, major, side = edge_road(nodes, edges)
    Acc = accidents()
    r = PM.LIGHT_R_M.value
    ln, dist = lights_per_edge(nodes, edges, L[["x", "y"]].to_numpy(), r)
    Lm = edges["len_m"].to_numpy()
    minor = ~major
    note("light_dist", f"보안등 좌표 → 가장 가까운 보행망 간선 거리 (LIGHT_R_M={r}m 의 근거)",
         중앙값m=round(float(np.median(dist)), 1), p75m=round(float(np.percentile(dist, 75)), 1),
         안10m=f"{(dist <= 10).mean():.1%}", 안20m=f"{(dist <= 20).mean():.1%}", 안30m=f"{(dist <= 30).mean():.1%}")
    u = L.drop_duplicates("loc")[["x", "y"]].to_numpy()
    from scipy.spatial import cKDTree
    nn = cKDTree(u).query(u, k=2)[0][:, 1]
    note("light_spacing", "보안등 고유 위치 간 최근접 간격", 중앙값m=round(float(np.median(nn)), 1),
         p25m=round(float(np.percentile(nn, 25)), 1), p75m=round(float(np.percentile(nn, 75)), 1))
    note("light_cover", f"골목 길이 중 보안등 {r}m 안", 골목km=round(float(Lm[minor].sum()) / 1000, 1),
         보안등있음=f"{Lm[minor & (ln > 0)].sum() / Lm[minor].sum():.1%}",
         큰길km=round(float(Lm[major].sum()) / 1000, 1))
    F, use = station_walk(nodes, edges, cells, S)
    tot = F.sum(axis=0)
    pm = tot * Lm
    unlit_minor = minor & (ln == 0)
    note("station_walk", f"밤 역 귀갓길(보행 {PM.STATION_WALK_MAX_M.value:,}m 안 · 산업단지역 제외) — 사람·m 기준",
         역=len(use), 배정된밤하차=round(float(use[["a22", "a23", "a24"]].sum().sum())),
         보안등없는골목비중=f"{pm[unlit_minor].sum() / max(pm.sum(), 1e-9):.1%}",
         큰길비중=f"{pm[major].sum() / max(pm.sum(), 1e-9):.1%}",
         평균보행m=round(float(np.average(use['mean_walk_m'].fillna(0), weights=use['homes_w'].fillna(0) + 1e-9))))

    L.to_csv(DER / "lights.csv", index=False, encoding="utf-8-sig")
    C.to_csv(DER / "cctv.csv", index=False, encoding="utf-8-sig")
    B.to_csv(DER / "bells.csv", index=False, encoding="utf-8-sig")
    Po.to_csv(DER / "police.csv", index=False, encoding="utf-8-sig")
    S.merge(use[["line", "station", "node", "cells", "homes_w", "mean_walk_m"]], on=["line", "station"], how="left") \
     .to_csv(DER / "stations.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"highway": hw, "major": major, "lights_n": ln,
                  "f22": F[0].round(4), "f23": F[1].round(4), "f24": F[2].round(4), "sidewalk": side}) \
      .to_csv(DER / "edge_public.csv", index=False, encoding="utf-8-sig")
    Acc.to_csv(DER / "accidents.csv", index=False, encoding="utf-8-sig")
    yr = int(S["month"].iloc[0][:4])
    REP["_sunset"] = {"year": yr, "latlon": [round(x, 4) for x in center_latlon()], "table": sunset_table(yr)}
    REP["_meta"] = {"built": datetime.date.today().isoformat(),
                    "manifest": json.loads((RAW / "MANIFEST.json").read_text(encoding="utf-8"))
                    if (RAW / "MANIFEST.json").exists() else {}}
    (DER / "report.json").write_text(json.dumps(REP, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log(f"[v] {DER}")


# 시연판이 읽는 파일 — ingest_inventory.py 가 data/proto 로 옮긴다(화면은 data/proto 만 읽는다, CLAUDE.md §6)
PROTO_FILES = ["lights.csv", "cctv.csv", "bells.csv", "police.csv", "stations.csv", "edge_public.csv", "report.json",
               "accidents.csv"]                                      # 교통사고 다발지역(#26) — 실데이터 전용(임의값 판에선 지운다)


def export_proto(outp):
    """derived → data/proto. derived 가 없거나 원본보다 오래됐으면 다시 만든다."""
    import shutil
    srcs = [DER / f for f in PROTO_FILES]
    newest_raw = max(p.stat().st_mtime for p in RAW.glob("*") if p.is_file())
    if not all(p.exists() for p in srcs) or min(p.stat().st_mtime for p in srcs) < newest_raw:
        build()
    for p in srcs:
        shutil.copy2(p, outp / ("public_report.json" if p.name == "report.json" else p.name))
    return json.loads((DER / "report.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    build()
