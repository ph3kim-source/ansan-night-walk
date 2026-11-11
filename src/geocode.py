# -*- coding: utf-8 -*-
"""
주소 → 좌표 (오프라인 지오코더)

원리
----
공식 도로명주소 DB가 없으므로, 보유한 상가정보(안산 34,489건 · 시흥 25,119건)의
'도로명 + 건물본번지 + 좌표' 와 '법정동 + 지번 + 좌표' 를 색인으로 만들어 근사 변환한다.

  "경기도 안산시 상록구 석호로 123"
    → 도로명 '석호로' 의 건물번호 목록에서 123 에 가장 가까운 번호의 좌표
  "경기 시흥시 정왕동 2640"   (#77 — 네이버 지도 등에서 옮겨 적는 지번 주소)
    → 시흥시 정왕동 2640번지에 있는 상가의 좌표. 본번이 같은 곳만 쓴다(지번은 도로처럼 번호 순서로 늘어서지 않아
      가까운 번호로 근사하지 않는다)

시흥시(#77) — 반월산단 옆 시화산단 직장이 시흥 주소라서 넣었다. 두 시에 같은 도로명이 15개(만해로 · 번영로 …)
있어 주소에 '시흥' 이 없으면 안산을 먼저 본다. 공장 등록현황 좌표(pipeline/build_factory.py)는 안산 색인만 쓴다.
좌표(#77) — 시민 화면에서 지도로 고른 직장은 '위도, 경도' 글자로 넘어온다.

한계 (반드시 인지할 것)
  - 상가가 하나도 없는 '주거 전용 도로'는 색인에 없다 → 동 중심점으로 대체
  - 건물번호가 정확히 없으면 가장 가까운 번호로 근사 → 수십~수백 m 오차
  - 지번은 그 번지에 상가가 있어야 찾는다
  - 공식 대안: juso.go.kr 도로명주소 DB (무료). 확보 시 이 모듈만 교체하면 된다.

색인 생성:  python src/geocode.py build
테스트:     python src/geocode.py test
"""
import difflib, re, json, pathlib, sys
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
# 3안 구조 — 주소 색인은 data/geocode, 동 경계·1km 격자는 data/base (3안 독립 사본, 수정사항 #11)
P = ROOT / "data" / "geocode"
BASE = ROOT / "data" / "base"
RAW_SHOP = (ROOT / "data" / "소상공인시장진흥공단_상가(상권)정보_20260630"
            / "소상공인시장진흥공단_상가(상권)정보_경기_202606.csv")
IDX = P / "geocode_index.csv"
DONG = P / "geocode_dong.csv"
JIBUN = P / "geocode_jibun.csv"
#: 색인에 넣는 시 — 시군구코드 앞자리(안산 상록구 41271 · 단원구 41273, 시흥 41390). 순서가 같은 이름일 때의 우선순위다
CITIES = (("안산", "4127"), ("시흥", "41390"))


def build():
    """상가정보에서 도로명 · 지번 색인과 동 중심점을 만든다. 안산을 먼저 두고 시흥을 붙인다(#77)."""
    cols = ["시군구코드", "시군구명", "행정동명", "법정동명", "도로명", "대지구분명",
            "건물본번지", "건물부번지", "지번본번지", "지번부번지", "경도", "위도"]
    df = pd.read_csv(RAW_SHOP, encoding="utf-8", usecols=cols, low_memory=False)
    code = df["시군구코드"].astype(str)
    parts = []
    for city, prefix in CITIES:
        parts.append(df[code.str.startswith(prefix)].assign(시군구=city))
    df = pd.concat(parts, ignore_index=True)
    a = df.dropna(subset=["경도", "위도", "도로명", "건물본번지"]).copy()

    a["도로명_짧게"] = a["도로명"].astype(str).str.split().str[-1]
    a["건물본번지"] = pd.to_numeric(a["건물본번지"], errors="coerce")
    a = a.dropna(subset=["건물본번지"])
    idx = (a.groupby(["시군구", "도로명_짧게", "건물본번지"], sort=False)
             .agg(경도=("경도", "median"), 위도=("위도", "median"),
                  행정동명=("행정동명", "first"), 법정동명=("법정동명", "first"),
                  건수=("경도", "size")).reset_index())
    # 안산 줄은 #76 까지와 같은 순서(도로명 · 번호)로 — 공장 좌표가 이 색인을 쓴다
    idx = pd.concat([g.sort_values(["도로명_짧게", "건물본번지"]) for _, g in idx.groupby("시군구", sort=False)])
    idx = idx[["도로명_짧게", "건물본번지", "경도", "위도", "행정동명", "법정동명", "건수", "시군구"]]
    idx.to_csv(IDX, index=False, encoding="utf-8-sig")

    # 지번 — 법정동 + (산) + 본번 + 부번. 부번이 없으면 0
    j = df.dropna(subset=["경도", "위도", "법정동명", "지번본번지"]).copy()
    j["산"] = (j["대지구분명"].astype(str) == "산").astype(int)
    j["지번본번지"] = pd.to_numeric(j["지번본번지"], errors="coerce")
    j["지번부번지"] = pd.to_numeric(j["지번부번지"], errors="coerce").fillna(0)
    j = j.dropna(subset=["지번본번지"])
    jb = (j.groupby(["시군구", "법정동명", "산", "지번본번지", "지번부번지"], sort=False)
            .agg(경도=("경도", "median"), 위도=("위도", "median"), 행정동명=("행정동명", "first"),
                 건수=("경도", "size")).reset_index())
    jb[["지번본번지", "지번부번지"]] = jb[["지번본번지", "지번부번지"]].astype(int)
    jb.to_csv(JIBUN, index=False, encoding="utf-8-sig")

    # 동 중심점(법정동·행정동 모두, 시마다)
    rows = []
    for key, col in (("행정동", "행정동명"), ("법정동", "법정동명")):
        g = a.groupby(["시군구", col], sort=False).agg(경도=("경도", "median"), 위도=("위도", "median"),
                                                        건수=("경도", "size")).reset_index()
        g.columns = ["시군구", "동명", "경도", "위도", "건수"]
        g["구분"] = key
        rows.append(g)
    dn = pd.concat(rows)
    dn = pd.concat([g.sort_values(["구분", "동명"], ascending=[False, True]) for _, g in dn.groupby("시군구", sort=False)])
    dn[["동명", "경도", "위도", "건수", "구분", "시군구"]].to_csv(DONG, index=False, encoding="utf-8-sig")
    for city, _ in CITIES:
        print(f"[v] {city} — 도로명 색인 {int((idx['시군구'] == city).sum()):,}건 "
              f"(도로 {idx.loc[idx['시군구'] == city, '도로명_짧게'].nunique()}개) · 지번 {int((jb['시군구'] == city).sum()):,}건 · "
              f"동 중심 {int((dn['시군구'] == city).sum())}건")
    print(f"[v] → {IDX.name} · {JIBUN.name} · {DONG.name}")


_IDX = _DONG = _JIB = None


def _load():
    global _IDX, _DONG
    if _IDX is None:
        _IDX = pd.read_csv(IDX, encoding="utf-8-sig")
        _DONG = pd.read_csv(DONG, encoding="utf-8-sig")
        for t in (_IDX, _DONG):                     # #77 이전 색인(안산만, 시군구 칸 없음)도 읽는다
            if "시군구" not in t:
                t["시군구"] = "안산"
    return _IDX, _DONG


def _jibun():
    global _JIB
    if _JIB is None:
        _JIB = (pd.read_csv(JIBUN, encoding="utf-8-sig") if JIBUN.exists() else
                pd.DataFrame(columns=["시군구", "법정동명", "산", "지번본번지", "지번부번지", "경도", "위도", "행정동명", "건수"]))
    return _JIB


def _city(s):
    """주소에 적힌 시 — 없으면 None(안산 먼저, 그다음 시흥)."""
    for city, _ in CITIES:
        if city in str(s):
            return city
    return None


def _in_cities(df, city):
    """시를 적었으면 그 시만, 안 적었으면 안산 먼저 · 없으면 시흥 순서로 찾을 표들."""
    order = [city] if city else [c for c, _ in CITIES]
    return [df[df["시군구"] == c] for c in order]


ROAD_RE = re.compile(r"([가-힣A-Za-z0-9]+(?:로|길))\s*(\d+)(?:\s*-\s*(\d+))?")
DONG_RE = re.compile(r"([가-힣]+[0-9]*동)")
#: 지번 — '정왕동 2640' · '원시동 729-11번지' · '대부북동 산 12' (#77). 동 이름 바로 뒤의 번지만 지번으로 본다
JIBUN_RE = re.compile(r"([가-힣]+[0-9]*동)\s*(산\s*)?(\d+)(?:\s*-\s*(\d+))?\s*(?:번지)?(?![가-힣0-9])")
#: 좌표 — 시민 화면에서 지도로 고른 직장(#77). '37.30451, 126.78012'
COORD_RE = re.compile(r"(3\d\.\d{3,})\s*,\s*(12\d\.\d{3,})")
PICK_LABEL = "지도에서 고른 곳"

#: 주소 앞에 붙는 행정구역 · 정류장 꼬리 — 정류장 이름을 찾을 때 걷어낸다
ADMIN = {"경기도", "경기", "안산시", "안산", "단원구", "상록구", "시흥시", "시흥"}
TAIL = ("버스정류장", "정류장", "정류소")

# ── 정류장 이름 (#52) ─────────────────────────────────────────
# 직장 주소는 몰라도 '회사 앞 정류장 이름'은 아는 근로자가 많다. 산단 정류장 이름이 대개
# 회사 이름이기도 하다(변전소.일성신약 · LS오토모티브 · 흥일스텐). TAGO 정차 정류장 1,999개의
# 이름을 세 번째 색인으로 쓴다. 공장등록 440건은 산단 밖 공장이 대부분(초지동 11건)이라 못 썼다.
# #74 — 공장 등록현황 최신본(2026-07-31, 7,152곳)이 들어와 회사 이름과 공장 주소로도 찾는다(_factory_*).
_STOPS = None
_FAC = None

#: 회사 이름 비교에서 걷어내는 법인 표기
CORP_RE = re.compile(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(합\)|합자회사|\(사\)|\(재\)")


def _cname(s):
    """회사 이름 비교용 — 법인 표기 · 공백 · 점 · 괄호를 지운다."""
    return _norm(CORP_RE.sub("", str(s))).lower()


def _factories():
    """공장 등록현황(좌표가 붙은 것만) — pipeline/build_factory.py 산출. 없으면 빈 표."""
    global _FAC
    if _FAC is None:
        f = P / "factory.csv"
        if f.exists():
            d = pd.read_csv(f, encoding="utf-8-sig", dtype={"업종코드": str, "행정동": str, "법정동": str})
            d = d[d["위도"].notna()].copy()
            d["key"] = d["공장명"].map(_cname)
            _FAC = d.reset_index(drop=True)
        else:
            _FAC = pd.DataFrame(columns=["공장명", "주소", "도로명", "본번", "부번", "위도", "경도", "위치정확도", "key"])
    return _FAC


def factory_points():
    """지도에서 직장을 고를 때 누르는 점 (#77) — 위치를 찾은 등록 공장. 같은 자리(좌표가 같은 공장)는 한 점으로 묶고
    이름은 종업원이 가장 많은 공장 + '외 N곳'. 칸: lat · lon · name · n(그 자리 공장 수)."""
    f = _factories()
    if not len(f):
        return pd.DataFrame(columns=["lat", "lon", "name", "n"])
    f = f.assign(_n=pd.to_numeric(f["종업원수"], errors="coerce").fillna(0)).sort_values("_n", ascending=False)
    g = f.groupby([f["위도"].round(6), f["경도"].round(6)], sort=False)
    out = g.agg(name=("공장명", "first"), n=("공장명", "size")).reset_index()
    out.columns = ["lat", "lon", "name", "n"]
    out["name"] = out["name"].astype(str) + out["n"].map(lambda k: f" 외 {k - 1}곳" if k > 1 else "")
    return out[["lat", "lon", "name", "n"]]


def _fac_hit(rows, how, same_m=200.0):
    """공장 여러 줄 → 한 곳으로 모여 있으면 dict, 흩어져 있으면 None (같은 이름 공장이 여러 곳)."""
    lat0, lon0 = rows["위도"].median(), rows["경도"].median()
    dm = np.hypot((rows["위도"] - lat0) * 111_000, (rows["경도"] - lon0) * 88_600)
    if dm.max() > same_m:
        return None
    r = rows.iloc[0]
    exact = str(r.get("위치정확도", "")) in ("건물", "건물(본번)")
    more = f" 외 {len(rows) - 1}곳(같은 자리)" if len(rows) > 1 else ""
    return {"위도": float(lat0), "경도": float(lon0), "방식": how, "정확도": "높음" if exact else "보통",
            "설명": f"{r['공장명']} 공장 등록 주소 기준{more}",
            "행정동": (str(r.get("행정동")) or None) if pd.notna(r.get("행정동")) else None,
            "법정동": (str(r.get("법정동")) or None) if pd.notna(r.get("법정동")) else None}


def _factory_name(s):
    """회사 이름이 공장 등록현황의 공장명과 같으면 그 공장 위치 (#74). 이름의 일부만 같은 것은 고르지 않는다."""
    k = _cname(s)
    if len(k) < 2:
        return None
    f = _factories()
    rows = f[f["key"] == k]
    return _fac_hit(rows, "공장 이름") if len(rows) else None


def _factory_addr(road, no, sub):
    """도로명 + 건물번호가 등록 공장의 주소와 같으면 그 공장 건물 위치 (#74)."""
    f = _factories()
    rows = f[(f["도로명"] == road) & (f["본번"] == no)]
    if sub:
        exact = rows[rows["부번"] == sub]
        rows = exact if len(exact) else rows
    return _fac_hit(rows, "공장 주소") if len(rows) else None


def _norm(s):
    """정류장 이름 비교용 — 공백 · 점 · 괄호 · 가운뎃점을 지운다."""
    return re.sub(r"[\s.·,()\[\]\-]", "", str(s))


def _stops():
    """안산 안의 정차 정류장 + 행정동. 노선이 부천 · 서울까지 가서 TAGO 목록에 안산 밖 정류장도
    섞여 있다 — 동 경계(dong.geojson) 안에 있는 것만 쓴다."""
    global _STOPS
    if _STOPS is None:
        import geopandas as gpd
        s = pd.read_csv(P / "stops_firstbus.csv", encoding="utf-8-sig", dtype=str)
        s = s.dropna(subset=["gpslati", "gpslong"])
        s = s[~s["nodenm"].astype(str).str.contains("(미정차)", regex=False)].copy()  # route.is_stop 과 같은 기준
        s["위도"], s["경도"] = s["gpslati"].astype(float), s["gpslong"].astype(float)
        g = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s["경도"], s["위도"]), crs=4326)
        dong = gpd.read_file(BASE / "dong_sgis.geojson")[["ADM_NM", "geometry"]].to_crs(4326)
        g = gpd.sjoin(g, dong, how="inner", predicate="within")
        s = pd.DataFrame(g.drop(columns=["geometry", "index_right"]))
        s["key"] = s["nodenm"].map(_norm)
        _STOPS = s.reset_index(drop=True)
    return _STOPS


def _parse(s, dong):
    """입력 → (정류장 이름 후보 낱말, 동 이름 낱말). 행정구역 · 숫자만 있는 낱말은 뺀다."""
    names = set(dong["동명"].astype(str))
    words, dongs = [], []
    for t in str(s).replace("(", " ").replace(")", " ").split():
        for tail in TAIL:
            if t.endswith(tail) and len(t) > len(tail):
                t = t[: -len(tail)]
        if t in ADMIN or t.isdigit() or len(_norm(t)) < 2 or t in TAIL:
            continue
        if DONG_RE.fullmatch(t) and t in names:
            dongs.append(t)
            continue
        words.append(t)
    return words, dongs


def _stop_match(s, dong, same_m=200.0):
    """정류장 이름으로 위치를 찾는다. 찾은 정류장이 한 곳(상·하행 쌍 포함)에 모여 있을 때만.

    같은 이름이 여러 동에 있으면(한양대입구) 입력에 동 이름이 함께 있을 때 그 동으로 좁힌다.
    same_m — 이만큼 안에 모여 있으면 한 곳으로 본다. params.MIN_GAP(200m, 상·하행 쌍 간격 P90
    154m)과 같은 값이다(geocode 는 params 를 import 하지 않는 가벼운 모듈이라 값만 맞춘다).
    반환: (결과 dict 또는 None, 동 이름을 붙인 후보 목록)"""
    words, dongs = _parse(s, dong)
    if not words:
        return None, []
    st = _stops()
    tries = [_norm("".join(words))] + sorted({_norm(t) for t in words}, key=len, reverse=True)
    for q in tries:
        hit = st[st["key"] == q]
        if hit.empty:
            hit = st[st["key"].str.contains(q, regex=False)]
        if hit.empty:
            continue
        if dongs and hit["ADM_NM"].isin(dongs).any():
            hit = hit[hit["ADM_NM"].isin(dongs)]
        lat0, lon0 = hit["위도"].median(), hit["경도"].median()
        # 위경도 차를 m 로 — 안산 위도(37.3°)에서 경도 1° ≈ 88.6km, 위도 1° ≈ 111km
        dm = np.hypot((hit["위도"] - lat0) * 111_000, (hit["경도"] - lon0) * 88_600)
        # 입력과 가장 닮은 이름을 대표로 ('일성신약' → 일성신약옆건너편 보다 변전소.일성신약)
        names = sorted(dict.fromkeys(hit["nodenm"].astype(str)),
                       key=lambda n: -difflib.SequenceMatcher(None, q, _norm(n)).ratio())
        if dm.max() <= same_m:
            nm = names[0]
            n_same = int((hit["nodenm"] == nm).sum())
            more = (f" (같은 이름 {n_same}곳 — 상·하행)" if n_same > 1 and len(names) == 1 else
                    (f" (비슷한 이름 {len(names)}곳, 모두 {int(same_m)}m 안)" if len(names) > 1 else ""))
            return ({"위도": float(lat0), "경도": float(lon0), "방식": "정류장명", "정확도": "보통",
                     "설명": f"{nm} 정류장 위치 기준{more}",
                     "행정동": str(hit["ADM_NM"].mode().iat[0]), "법정동": None}, names)
        # 여러 곳에 흩어진 이름 — 하나로 정하지 않고 '동 + 이름' 후보를 돌려준다
        pairs = hit.groupby(["ADM_NM", "nodenm"]).size().reset_index()
        return None, [f"안산시 {r.ADM_NM} {r.nodenm} 정류장" for r in pairs.itertuples()]
    return None, []


def suggest(addr, k=5):
    """인식 실패 시 비슷한 입력 후보 — 같은 이름 정류장(동으로 구분) · 도로명 오타 · 정류장 · 동 이름.

    후보는 그대로 다시 넣으면 인식되는 형태로 만든다(화면에서 눌러 바로 다시 조회)."""
    idx, dong = _load()
    s = str(addr).strip()
    city = _city(s) or "안산"                      # 시를 안 적었으면 안산 이름으로 제안(#77 이전과 같음)
    pre = f"{city}시"
    out = []
    _, cands = _stop_match(s, dong)
    out += cands
    num = re.search(r"\d+", s)
    roads = idx.loc[idx["시군구"] == city, "도로명_짧게"].astype(str).unique().tolist()
    words, _ = _parse(s, dong)
    m = ROAD_RE.search(s)
    # 도로명 오타 — 건물번호가 있을 때만(번호를 지어내 붙이면 엉뚱한 곳을 가리킨다)
    for t in (([m.group(1)] if m else []) + words) if num else []:
        for r in difflib.get_close_matches(t, roads, n=2, cutoff=0.6):
            if r != t:
                out.append(f"{pre} {r} {num.group(0)}")
    if not cands:
        st = _stops()
        uniq = st["nodenm"].astype(str).unique().tolist()
        keys = [_norm(x) for x in uniq]
        for t in words:
            for key in difflib.get_close_matches(_norm(t), keys, n=2, cutoff=0.7):
                out.append(f"{uniq[keys.index(key)]} 정류장")
    # 회사 이름 오타 · 법인 표기 차이 (#74)
    fac = _factories()
    if len(fac) and not m and not cands:
        keys = fac["key"].unique().tolist()
        for key in difflib.get_close_matches(_cname(s), keys, n=3, cutoff=0.75):
            out.append(str(fac.loc[fac["key"] == key, "공장명"].iat[0]))
    dnames = dong.loc[dong["시군구"] == city, "동명"].astype(str).unique().tolist()
    for t in str(s).split():
        if len(t) >= 2 and t not in ADMIN:
            out += [f"{pre} {d}" for d in difflib.get_close_matches(t, dnames, n=2, cutoff=0.6)]
    # 후보 자체가 인식되는 것만 남긴다 — 눌렀는데 또 실패하면 안 된다
    ok = [x for x in dict.fromkeys(out) if x != s and geocode(x)]
    return ok[:k]


def _factory_dong(nm):
    """동 안 등록 공장의 종업원 가중 중심 — 직장을 동 이름만 넣었을 때 (#74). 공장이 없거나 종업원 합이 0 이면 None."""
    f = _factories()
    if not len(f):
        return None
    col = "행정동" if (f["행정동"] == nm).any() else ("법정동" if (f["법정동"] == nm).any() else None)
    if col is None:
        return None
    rows = f[f[col] == nm]
    w = pd.to_numeric(rows["종업원수"], errors="coerce").fillna(0).to_numpy(float)
    if w.sum() <= 0:
        return None
    return {"위도": float(np.average(rows["위도"], weights=w)), "경도": float(np.average(rows["경도"], weights=w)),
            "방식": "동 안 공장 중심", "정확도": "낮음",
            "설명": f"{nm} 공장들이 모인 곳 기준 (동 이름만 있어 등록 공장 {int((w > 0).sum()):,}곳의 분포로)",
            "행정동": nm if col == "행정동" else None, "법정동": nm if col == "법정동" else None}


#: 산단 이름 — 직장 칸에 회사 대신 산단 이름만 적은 경우 (#93). '반월동' 같은 동 이름과 겹치지 않게 뒤에 산단 · 공단 · 허브가 붙어야 한다
ZONE_BANWOL_RE = re.compile(r"(반월|안산)(국가)?(산업단지|산단|공단)|(안산|반월)?스마트허브")
ZONE_SIHWA_RE = re.compile(r"시화(국가)?(산업단지|산단|공단)|시흥스마트허브")


def _zone_name(s):
    """직장 칸에 산단 이름만 있을 때 (#93) — '반월공단' · '안산스마트허브' 는 반월산단(params.INDUSTRIAL 두 동) 등록 공장의
    종업원 가중 중심, '시화산단' · '시흥스마트허브' 는 시흥 정왕동 가운데. 회사 이름이나 주소를 넣으면 가까운 하차지를 더
    정확히 고르므로 정확도는 '낮음'. 전에는 '반월공단' 을 찾지 못해 빨간 오류가 떴다."""
    k = _norm(s)
    if ZONE_SIHWA_RE.search(k):
        _, dong = _load()
        c = dong[(dong["시군구"] == "시흥") & (dong["동명"] == "정왕동")]
        if not len(c):
            return None
        h = c.iloc[0]
        # 설명이 '시흥시' 로 시작해야 match.work_area 가 '시흥시 정왕동'(반월산단 밖)으로 읽는다
        return {"위도": float(h["위도"]), "경도": float(h["경도"]), "방식": "산단 이름", "정확도": "낮음",
                "설명": "시흥시 정왕동 가운데 기준 (시화산단 — 산단 이름만 있어 동 단위로)", "행정동": None, "법정동": "정왕동"}
    if ZONE_BANWOL_RE.search(k):
        import params as PM                          # 산단 범위는 한 곳(params)에서만 정한다
        f = _factories()
        rows = f[f["행정동"].isin(PM.INDUSTRIAL.value)] if len(f) else f
        w = pd.to_numeric(rows["종업원수"], errors="coerce").fillna(0).to_numpy(float) if len(rows) else np.zeros(0)
        if not len(rows) or w.sum() <= 0:
            return None
        lat, lon = float(np.average(rows["위도"], weights=w)), float(np.average(rows["경도"], weights=w))
        return {"위도": lat, "경도": lon, "방식": "산단 이름", "정확도": "낮음",
                "설명": f"반월산단 공장들이 모인 곳 기준 (산단 이름만 있어 등록 공장 {int((w > 0).sum()):,}곳의 분포로)",
                "행정동": _dong_at(lat, lon), "법정동": None}
    return None


_AREA = _DONG_POLY = None


def _area():
    """좌표로 받는 범위 — 색인 상가 점(안산 · 시흥)이 있는 위도 · 경도 범위. 밖이면 안산 · 시흥 주소가 아니다."""
    global _AREA
    if _AREA is None:
        idx, _ = _load()
        _AREA = (float(idx["위도"].min()), float(idx["위도"].max()), float(idx["경도"].min()), float(idx["경도"].max()))
    return _AREA


def _dong_at(lat, lon):
    """좌표가 든 안산 행정동 이름(dong.geojson) — 안산 밖이면 None."""
    global _DONG_POLY
    if _DONG_POLY is None:
        import geopandas as gpd
        _DONG_POLY = gpd.read_file(BASE / "dong_sgis.geojson")[["ADM_NM", "geometry"]].to_crs(4326)
    from shapely.geometry import Point
    hit = _DONG_POLY[_DONG_POLY.contains(Point(lon, lat))]
    return str(hit["ADM_NM"].iat[0]) if len(hit) else None


def _coord(s):
    """'위도, 경도' 글자 — 지도에서 고른 직장 (#77). 앞에 붙은 이름(예: 가까운 공장)은 설명에 남긴다."""
    m = COORD_RE.search(s)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    la0, la1, lo0, lo1 = _area()
    if not (la0 <= lat <= la1 and lo0 <= lon <= lo1):
        return None
    label = s[:m.start()].replace(PICK_LABEL, "").strip(" ·,")
    return {"위도": lat, "경도": lon, "방식": "지도", "정확도": "높음",
            "설명": "지도에서 고른 위치 기준" + (f" ({label})" if label else ""),
            "행정동": _dong_at(lat, lon), "법정동": None}


def _jibun_match(s, city):
    """지번 — 법정동 + 본번이 같은 상가가 있으면 그 자리 (#77). 부번까지 같으면 정확도 높음, 본번만 같으면 보통.
    지번은 도로처럼 번호 순서로 늘어서지 않아 본번이 다른 곳으로는 근사하지 않는다."""
    m = JIBUN_RE.search(s)
    if not m:
        return None
    dn, mt, bon, bu = m.group(1), int(bool(m.group(2))), int(m.group(3)), int(m.group(4) or 0)
    for t in _in_cities(_jibun(), city):
        c = t[(t["법정동명"] == dn) & (t["산"] == mt) & (t["지번본번지"] == bon)]
        if not len(c):
            continue
        gap = (c["지번부번지"] - bu).abs()
        hit = c.loc[gap.idxmin()]
        hb = int(hit["지번부번지"])
        pre = "" if hit["시군구"] == "안산" else f"{hit['시군구']}시 "
        num = f"{'산 ' if mt else ''}{bon}" + (f"-{hb}" if hb else "")
        return {"위도": float(hit["위도"]), "경도": float(hit["경도"]), "방식": "지번",
                "정확도": "높음" if hb == bu else "보통",
                "설명": f"{pre}{dn} {num}번지 기준" + ("" if hb == bu else f" (입력한 번지({bon}" + (f"-{bu}" if bu else "")
                                                       + ")와 본번만 같음)"),
                "행정동": hit.get("행정동명"), "법정동": dn}
    return None


def geocode(addr: str, role=None):
    """주소 문자열 → dict(위도, 경도, 방식, 정확도, 설명). 실패 시 None.

    순서: 좌표(지도에서 고른 곳, #77) → ⓪ 회사 이름(공장 등록현황, #74) → ① 도로명 + 건물번호(등록 공장 주소면 그
    건물, 아니면 상가 색인 근사) → ①-2 지번(#77) → ①-3 직장 칸의 산단 이름(#93) → ② 정류장 이름(#52) → ③ 동 이름(중심점, 정확도 낮음).
    role="work"(직장)이고 동 이름만 있으면 그 동 등록 공장의 종업원 가중 중심을 먼저 본다(#74) — 산단 동의 상가
    중심은 주거 · 상가 쪽이라 공장들과 수 km 떨어진다. 주소에 '시흥' 이 있으면 시흥 색인만, 시를 안 적었으면 안산
    다음 시흥 순서로 찾는다(#77)."""
    idx, dong = _load()
    s = str(addr).strip()
    if not s:
        return None
    city = _city(s)

    hit = _coord(s)
    if hit or COORD_RE.search(s):
        return hit

    # 0) 회사 이름 — 직장 주소는 몰라도 회사 이름은 안다 (#74)
    hit = _factory_name(s)
    if hit:
        return hit

    # 1) 도로명 + 건물번호
    m = ROAD_RE.search(s)
    if m:
        road, no = m.group(1), int(m.group(2))
        if city != "시흥":                            # 공장 등록현황은 안산 공장뿐
            hit = _factory_addr(road, no, int(m.group(3) or 0))
            if hit:
                return hit
        for t in _in_cities(idx, city):
            cand = t[t["도로명_짧게"] == road]
            if not len(cand):
                continue
            d = (cand["건물본번지"] - no).abs()
            hit = cand.loc[d.idxmin()]
            gap = int(d.min())
            pre = "" if hit["시군구"] == "안산" else f"{hit['시군구']}시 "
            return {"위도": float(hit["위도"]), "경도": float(hit["경도"]),
                    "방식": "도로명", "정확도": "높음" if gap <= 2 else ("보통" if gap <= 20 else "낮음"),
                    "설명": f"{pre}{road} {int(hit['건물본번지'])}번지 기준"
                            + ("" if gap == 0 else f" (입력한 {no}번지와 가장 가까운 번지)"),
                    "행정동": hit.get("행정동명"), "법정동": hit.get("법정동명")}

    # 1-2) 지번 — 네이버 지도 등에서 옮겨 적는 '정왕동 2640' (#77)
    hit = _jibun_match(s, city)
    if hit:
        return hit

    # 1-3) 직장 칸의 산단 이름 — '반월공단' · '시화산단' (#93). 정류장 이름보다 먼저 본다
    #      ('안산스마트허브' 는 초지동 행복주택 정류장 이름에도 들어 있어 그 정류장으로 잘못 찾았다)
    if role == "work":
        hit = _zone_name(s)
        if hit:
            return hit

    # 2) 정류장 이름 — 동 이름보다 훨씬 정확하다(동 중심점은 수 km 오차). 정류장 목록은 안산뿐
    if city != "시흥":
        hit, _ = _stop_match(s, dong)
        if hit:
            return hit

    # 3) 동 이름으로 대체 — 직장이면 그 동 공장 분포 먼저 (#74)
    if role == "work" and city != "시흥":
        for nm in DONG_RE.findall(s):
            hit = _factory_dong(nm)
            if hit:
                return hit
    for t in _in_cities(dong, city):
        for nm in DONG_RE.findall(s):
            for gubun in ("행정동", "법정동"):
                c = t[(t["구분"] == gubun) & (t["동명"] == nm)]
                if len(c):
                    h = c.iloc[0]
                    pre = "" if h["시군구"] == "안산" else f"{h['시군구']}시 "
                    return {"위도": float(h["위도"]), "경도": float(h["경도"]),
                            "방식": f"{gubun} 중심", "정확도": "낮음",
                            "설명": f"{pre}{nm} 가운데 기준 (번지를 찾지 못해 동 단위로)",
                            "행정동": nm if gubun == "행정동" else None,
                            "법정동": nm if gubun == "법정동" else None}
    return None


def coverage_report():
    """색인이 안산 주소를 얼마나 덮는지 — 한계를 수치로 보고."""
    idx, dong = _load()
    idx = idx[idx["시군구"] == "안산"]               # 인구 격자는 안산뿐 — 시흥 색인(#77)은 세지 않는다
    import geopandas as gpd
    g = gpd.read_file(BASE / "grid_1km.geojson")
    pts = gpd.GeoDataFrame(idx, geometry=gpd.points_from_xy(idx.경도, idx.위도), crs=4326)
    j = gpd.sjoin(pts, g[["GRID_CD", "총인구", "geometry"]], how="inner", predicate="within")
    covered = set(j["GRID_CD"])
    pop_all = g[g["총인구"] > 0]
    pop_cov = pop_all[pop_all["GRID_CD"].isin(covered)]
    return {
        "도로명_개수": int(idx["도로명_짧게"].nunique()),
        "주소점_개수": int(len(idx)),
        "인구격자_전체": int(len(pop_all)),
        "인구격자_색인보유": int(len(pop_cov)),
        "인구_커버율": round(float(pop_cov["총인구"].sum() / pop_all["총인구"].sum()), 4),
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    if mode == "build":
        build()
    else:
        print(json.dumps(coverage_report(), ensure_ascii=False, indent=2))
        print()
        for a in ["경기도 안산시 상록구 석호로 123", "안산시 단원구 광덕대로 200",
                  "안산시 상록구 사동 1234", "원곡동", "안산시 단원구 고잔로 50",
                  "서울시 강남구 테헤란로 1", "경기 시흥시 정왕동 2640", "경기도 시흥시 엠티브이북로 65",
                  "안산시 단원구 원시동 729-11", f"{PICK_LABEL} · 37.30451, 126.78012"]:
            r = geocode(a)
            if r:
                print(f"  {a:<28} → ({r['위도']:.5f}, {r['경도']:.5f}) "
                      f"[{r['방식']}/{r['정확도']}] {r['설명']}")
            else:
                print(f"  {a:<28} → 실패 (안산 주소가 아니거나 색인에 없음)")
