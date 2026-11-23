# -*- coding: utf-8 -*-
"""
인증키 API 수집 — SGIS(국가데이터처) · 브이월드(국토교통부 2D 데이터) · 행정안전부 CCTV정보 (수정사항 #17)
실행:  py -3.12 src/collect_api.py check          # 키 확인 — API 마다 한 번씩만 부른다
       py -3.12 src/collect_api.py                # 키가 있는 것 전부
       py -3.12 src/collect_api.py sgis vworld    # 골라서 (sgis · vworld · cctv)
출력:  data/api/raw/<sgis|vworld|cctv>/*  +  data/api/raw/MANIFEST.json (출처 · 받은 날 · 바이트 · sha256 · 키를 지운 주소)

인증키는 3안/.env 에 둔다(양식: .env.example). 코드 · 채팅 · 문서에 적지 않는다.
.env 와 data/api 는 공유본(build_share.py KEEP)과 드라이브 앱(build_app_folders.py NEVER)에 들어가지 않는다.

받는 것
  sgis    안산 25개 행정동의 행정동 경계 · 집계구 경계 · 집계구별 총조사 주요지표(인구 · 가구 · 주택 · 사업체 · 종사자)
  vworld  읍면동 · 건축물정보 · 도로명주소 건물/도로 · 표준 교통링크 · 용도지역 · 산업단지 · 아동안전지킴이집 (안산 사각형 안)
  cctv    행정안전부 CCTV정보 — 개방자치단체 안산시(3930000) 전수. #15 의 표준데이터 전국본은 500대에서 잘려 있었다

카카오 · 네이버는 여기 없다. 카카오는 로컬 API 응답을 따로 저장해 쓰는 것을 허용하지 않고(데브톡 FAQ 「데이터의 저장 사용」),
네이버 지역 검색은 한 번에 5건뿐이라 수집 수단이 아니다. 둘 다 실사용 앱에서 시민이 넣은 주소 · 장소를 그때그때 찾는 데에만 쓴다.
이 파일은 받기만 한다(원본 바이트 그대로). 정제 · 가공은 따로 한다.
"""
import datetime
import hashlib
import json
import math
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "api" / "raw"
ENV = ROOT / ".env"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
# 안산 24개 동을 덮는 사각형(위도 · 경도) — collect_public.BBOX · data/raw/overpass_쿼리.txt 와 같은 범위
BBOX = (37.2675, 126.7175, 37.3775, 126.9396)

KEYS = ("SGIS_KEY", "SGIS_SECRET", "VWORLD_KEY", "VWORLD_DOMAIN", "DATA_GO_KR_KEY")
NEED = {"sgis": ("SGIS_KEY", "SGIS_SECRET"), "vworld": ("VWORLD_KEY",), "cctv": ("DATA_GO_KR_KEY",)}
WHERE = {
    "sgis": "sgis.mods.go.kr → 개발지원센터 → 인증키 신청(서비스ID · 보안Key)",
    "vworld": "vworld.kr → 오픈API → 인증키 발급 — VWORLD_DOMAIN 에는 신청서에 등록한 서비스 URL 을 그대로(예: https://ph3kim-source.github.io, #41)",
    "cctv": "data.go.kr → 「행정안전부_CCTV정보 조회서비스」(15155042) 활용신청 → 일반 인증키(Decoding)",
}
LICENSE = {
    "sgis": "국가데이터처 통계지리정보서비스(SGIS) — 출처 표시",
    "vworld": "국토교통부 브이월드 2D 데이터 API — 공공누리 제1유형(출처 표시)",
    "cctv": "행정안전부 CCTV정보 조회서비스(공공데이터포털 15155042) — 이용허락범위 제한 없음",
}


def log(m):
    print(m, flush=True)


# ══ 공통 ════════════════════════════════════════════════════════════

def load_env(path=ENV, environ=None):
    """3안/.env 를 읽는다. 같은 이름의 환경변수가 있으면 그쪽이 이긴다. 빈 값은 없는 것으로 친다."""
    environ = os.environ if environ is None else environ
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in KEYS:
        if environ.get(k):
            env[k] = environ[k]
    return {k: v for k, v in env.items() if v}


def mask(text, secrets):
    """키 · 토큰을 *** 로 지운다(그대로 쓴 것과 주소용으로 바꾼 것 모두)."""
    for s in secrets:
        if s:
            for form in {s, urllib.parse.quote(s, safe=""), urllib.parse.quote_plus(s)}:
                text = text.replace(form, "***")
    return text


def build_url(url, params):
    return url + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe="():,")


def http_get(url, params, secrets=(), tries=3, timeout=90):
    """GET → (바이트, 키를 지운 주소). 4xx 는 바로 멈추고, 5xx · 끊김은 쉬었다가 다시 부른다."""
    full = build_url(url, params)
    shown = mask(full, secrets)
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(full, headers={"User-Agent": UA}), timeout=timeout) as r:
                return r.read(), shown
        except urllib.error.HTTPError as e:
            body = mask(e.read()[:300].decode("utf-8", "replace"), secrets)
            if e.code < 500:
                raise SystemExit(f"[X] HTTP {e.code} — {shown}\n    {body}")
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(5 * (k + 1))
    raise SystemExit(f"[X] 응답 없음 — {shown}")


GET = http_get   # 시험(tests/test_collect_api.py)에서 가짜 응답으로 바꿔 끼운다


def save(rel, data, source, url, **meta):
    p = RAW / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    mp = RAW / "MANIFEST.json"
    man = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    man[rel] = {"retrieved": datetime.date.today().isoformat(), "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "source": source, "url": url,
                "license": LICENSE[source], **meta}
    mp.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"    [v] {rel} · {len(data):,} bytes" + (f" · {meta['n']:,}건" if "n" in meta else ""))


# ══ SGIS — 집계구 ════════════════════════════════════════════════════
# 2025년 기관 개편으로 주소가 sgisapi.kostat.go.kr → sgisapi.mods.go.kr 로 바뀌었다(옛 주소는 302).

SGIS = "https://sgisapi.mods.go.kr/OpenAPI3"
SGIS_YEAR = 2024            # 총조사 주요지표 최신 연도(인구 · 가구 · 주택 2015~2024)
SGIS_BOUNDARY_YEAR = 2025   # 행정구역경계 최신 연도(2000~2025)


def sgis_dongs():
    """안산 행정동 SGIS 코드(8자리) — data/base/dong_sgis.geojson(SGIS 2025 2Q, 25개 동) 에서."""
    d = json.loads((ROOT / "data" / "base" / "dong_sgis.geojson").read_text(encoding="utf-8"))
    return sorted({f["properties"]["ADM_CD"] for f in d["features"]})


class Sgis:
    def __init__(self, env):
        self.key, self.secret = env["SGIS_KEY"], env["SGIS_SECRET"]
        self.token, self.t0 = None, 0.0

    def auth(self):
        b, _ = GET(f"{SGIS}/auth/authentication.json", {"consumer_key": self.key, "consumer_secret": self.secret},
                   secrets=(self.key, self.secret))
        d = json.loads(b)
        if d.get("errCd") != 0:
            raise SystemExit(f"[X] SGIS 인증 실패({d.get('errCd')}): {d.get('errMsg')} — .env 의 SGIS_KEY · SGIS_SECRET 확인")
        self.token, self.t0 = d["result"]["accessToken"], time.time()

    def call(self, path, **params):
        """(json, 바이트, 키를 지운 주소). 토큰은 4시간짜리 — 3시간 반이 지났거나 만료(-401)면 다시 받는다."""
        for attempt in range(2):
            if not self.token or time.time() - self.t0 > 3.5 * 3600:
                self.auth()
            b, shown = GET(f"{SGIS}/{path}", {"accessToken": self.token, **params},
                           secrets=(self.token, self.key, self.secret))
            d = json.loads(b)
            if d.get("errCd") == -401 and attempt == 0:
                self.token = None
                continue
            return d, b, shown
        raise SystemExit(f"[X] SGIS 토큰을 다시 받아도 -401 — {shown}")


def job_sgis(env):
    sg = Sgis(env)
    dongs = sgis_dongs()
    log(f"[SGIS] 안산 {len(dongs)}개 행정동 — 행정동 경계 · 집계구 경계 · {SGIS_YEAR}년 집계구 주요지표")
    for gu in sorted({c[:5] for c in dongs}):
        d, b, u = sg.call("boundary/hadmarea.geojson", year=SGIS_BOUNDARY_YEAR, adm_cd=gu, low_search=1)
        save(f"sgis/hadmarea_{SGIS_BOUNDARY_YEAR}_{gu}.geojson", b, "sgis", u,
             errCd=d.get("errCd"), n=len(d.get("features") or []))
    areas = rows = 0
    for cd in dongs:
        d, b, u = sg.call("boundary/statsarea.geojson", adm_cd=cd)
        n = len(d.get("features") or [])
        save(f"sgis/statsarea_{cd}.geojson", b, "sgis", u, errCd=d.get("errCd"), n=n)
        d, b, u = sg.call("stats/population.json", year=SGIS_YEAR, adm_cd=cd, low_search=1)
        m = len(d.get("result") or [])
        save(f"sgis/population_{SGIS_YEAR}_{cd}.json", b, "sgis", u, errCd=d.get("errCd"), n=m)
        areas, rows = areas + n, rows + m
        time.sleep(0.2)
    log(f"    집계구 경계 {areas:,}개 · 주요지표 {rows:,}행")


# ══ 브이월드 — 2D 데이터 API ═════════════════════════════════════════
# 158개 서비스 중 3안에 쓰는 것만. 전체 목록: vworld.kr/dev/v4dv_2ddataguide2_s001.do (POST pageIndex 1~16)

VW = "https://api.vworld.kr/req/data"
VW_LAYERS = {
    "LT_C_ADEMD_INFO": "읍면동 경계",
    "LT_C_BLDGINFO": "건축물정보 — 용도 · 층수(집계구 인구를 건물로 나눌 때)",
    "LT_C_SPBD": "도로명주소 건물 — 주소 입력 · 건물 위치",
    "LT_L_SPRD": "도로명주소 도로 — 대로 · 로 · 길",
    "LT_L_MOCTLINK": "표준 교통링크 — 도로 등급(가로등 구간 판정 보조)",
    "LT_C_UQ111": "도시지역 용도지역 — 주거 · 상업 · 공업",
    "LT_C_DAMDAN": "산업단지 경계 — 반월 · 시화",
    "LT_P_MGPRTFA": "아동안전지킴이집(경찰청, 2021)",
}
VW_STEP = 0.02    # 사각형 한 칸(도) — 약 1.8km × 2.2km
VW_PAGE = 1000    # 한 번에 받는 최대 개수(서비스 상한)


def tiles(bbox=BBOX, step=VW_STEP):
    """안산 사각형을 step 도 칸으로 나눈다 → [(서경, 남위, 동경, 북위), ...]. 칸끼리 겹치거나 비지 않는다."""
    s, w, n, e = bbox
    ny, nx = math.ceil(round((n - s) / step, 9)), math.ceil(round((e - w) / step, 9))
    return [(round(w + i * step, 6), round(s + j * step, 6), round(min(w + (i + 1) * step, e), 6),
             round(min(s + (j + 1) * step, n), 6)) for j in range(ny) for i in range(nx)]


def vw_box(env, layer, box):
    """한 칸의 모든 쪽 → 피처 목록. 데이터가 없는 칸(NOT_FOUND)은 빈 목록."""
    key = env["VWORLD_KEY"]
    feats, page = [], 1
    while True:
        b, u = GET(VW, {"service": "data", "version": "2.0", "request": "GetFeature", "format": "json",
                        "errorformat": "json", "size": VW_PAGE, "page": page, "data": layer,
                        "geomfilter": "BOX({},{},{},{})".format(*box), "geometry": "true", "attribute": "true",
                        "crs": "EPSG:4326", "key": key, "domain": env.get("VWORLD_DOMAIN", "")}, secrets=(key,))
        r = json.loads(b)["response"]
        if r.get("status") == "NOT_FOUND":
            return feats
        if r.get("status") != "OK":
            err = r.get("error") or {}
            raise SystemExit(f"[X] 브이월드 {layer} {err.get('code')}: {err.get('text')} — {u}")
        feats += r["result"]["featureCollection"]["features"]
        if page >= int((r.get("page") or {}).get("total", 1)):
            return feats
        page += 1


def job_vworld(env):
    boxes = tiles()
    log(f"[브이월드] {len(VW_LAYERS)}개 레이어 × 안산 사각형 {len(boxes)}칸")
    for layer, label in VW_LAYERS.items():
        feats = {}
        try:
            for box in boxes:
                for f in vw_box(env, layer, box):   # 칸 경계에 걸친 피처는 양쪽 칸에 다 나온다 → id 로 하나만
                    feats[f.get("id") or json.dumps(f.get("properties"), sort_keys=True, ensure_ascii=False)] = f
                time.sleep(0.1)
        except SystemExit as e:                     # 한 레이어가 막혀도 나머지는 받는다
            log(f"    {e}")
            continue
        data = json.dumps({"type": "FeatureCollection", "features": list(feats.values())},
                          ensure_ascii=False).encode("utf-8")
        save(f"vworld/{layer}.geojson", data, "vworld",
             f"{VW}?data={layer}&geomfilter=BOX(안산 사각형 {len(boxes)}칸)&crs=EPSG:4326", label=label, n=len(feats))


# ══ 행정안전부 CCTV정보 — 공공데이터포털 ═══════════════════════════

DGK_CCTV = "https://apis.data.go.kr/1741000/cctv_info/info"
ANSAN_OPN = "3930000"   # 개방자치단체코드 — #15 CCTV 표준데이터의 제공기관코드(경기도 안산시, 500행 전부)


def dgk_key(env):
    k = env["DATA_GO_KR_KEY"]
    return urllib.parse.unquote(k) if "%" in k else k   # Encoding 키를 넣었어도 Decoding 으로 바꿔 쓴다


def cctv_page(env, page, rows=100):
    key = dgk_key(env)
    b, u = GET(DGK_CCTV, {"serviceKey": key, "pageNo": page, "numOfRows": rows, "returnType": "json",
                          "cond[OPN_ATMY_GRP_CD::EQ]": ANSAN_OPN}, secrets=(key, env["DATA_GO_KR_KEY"]))
    try:
        d = json.loads(b)
    except json.JSONDecodeError:
        raise SystemExit("[X] CCTV 응답이 JSON 이 아님(활용신청 · 키 확인) — "
                         + mask(b[:300].decode("utf-8", "replace"), (key,)))
    hdr, body = d["response"]["header"], d["response"].get("body") or {}
    if str(hdr.get("resultCode")) not in ("0", "00", "000"):
        raise SystemExit(f"[X] CCTV {hdr.get('resultCode')}: {hdr.get('resultMsg')}")
    it = body.get("items") or []
    it = it.get("item", []) if isinstance(it, dict) else it
    return ([it] if isinstance(it, dict) else it), int(body.get("totalCount") or 0), u


def job_cctv(env):
    log(f"[CCTV] 행정안전부 CCTV정보 — 개방자치단체 {ANSAN_OPN}(안산시)")
    items, page = [], 1
    while True:
        it, total, u = cctv_page(env, page)
        items += it
        if not it or len(items) >= total:
            break
        page += 1
    data = json.dumps(items, ensure_ascii=False, indent=0).encode("utf-8")
    save(f"cctv/cctv_info_{ANSAN_OPN}.json", data, "cctv", u.replace(f"pageNo={page}", f"pageNo=1~{page}"),
         n=len(items), totalCount=total)


# ══ 키 확인 · 실행 ═══════════════════════════════════════════════════

def job_check(env):
    log(f"[키 확인] {ENV}")
    for name, need in NEED.items():
        miss = [k for k in need if k not in env]
        if miss:
            log(f"  [ ] {name:6s} 키 없음({', '.join(miss)}) — {WHERE[name]}")
            continue
        try:
            if name == "sgis":
                Sgis(env).auth()
                msg = "인증 성공(토큰 4시간)"
            elif name == "vworld":
                msg = f"읍면동 {len(vw_box(env, 'LT_C_ADEMD_INFO', (126.83, 37.31, 126.84, 37.32)))}개 응답"
            else:
                msg = f"안산 CCTV {cctv_page(env, 1, rows=1)[1]:,}건 조회 가능"
            log(f"  [v] {name:6s} {msg}")
        except SystemExit as e:
            log(f"  [X] {name:6s} {e}")


JOBS = {"sgis": job_sgis, "vworld": job_vworld, "cctv": job_cctv}


def main(argv):
    env = load_env()
    if argv[:1] == ["check"]:
        return job_check(env)
    names = argv or [n for n in JOBS if all(k in env for k in NEED[n])]
    if not names:
        log("[!] 3안/.env 에 키가 없습니다 — .env.example 을 .env 로 복사해 채운 뒤 "
            "py -3.12 src/collect_api.py check")
        return job_check(env)
    for n in names:
        if n not in JOBS:
            log(f"[건너뜀] {n} — 모르는 작업(sgis · vworld · cctv · check)")
            continue
        miss = [k for k in NEED[n] if k not in env]
        if miss:
            log(f"[건너뜀] {n} — 키 없음({', '.join(miss)}): {WHERE[n]}")
            continue
        JOBS[n](env)


if __name__ == "__main__":
    main(sys.argv[1:])
