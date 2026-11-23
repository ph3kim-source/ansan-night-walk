# -*- coding: utf-8 -*-
"""
공개 실데이터 수집 — 승인 · 인증키 없이 받을 수 있는 것만 (수정사항 #15)
실행:  python src/collect_public.py                  # 전부
       python src/collect_public.py lights korail    # 골라서 (lights · cctv · bells · osm · korail)
출력:  data/public/raw/*  +  data/public/raw/MANIFEST.json (출처 · 받은 날 · 바이트 · sha256 · 행 수)

받는 것
  lights  안산시 보안등 — 공공데이터포털 '전국보안등정보표준데이터'(15017320) 중 경기도 안산시 제공 파일
  cctv    전국CCTV표준데이터(15013094) 전국본에서 제공기관 '경기도 안산시' 행만        ★ 기관당 500행에서 잘려 있다
  bells   비상벨 위치 표준데이터(15028206) 전국본에서 '경기도 안산시' 행만            ★ 같은 500행 절단
  osm     OpenStreetMap(Overpass) — 경찰 · 119 시설, 철도역 위치
  korail  한국철도공사 「광역철도 시간대별 승하차인원」 최신 월 (info.korail.com 수송통계 게시판)
  accidents 전국교통사고다발지역표준데이터(15029185 · 한국도로교통공단) 전국본에서 시도시군구가 안산인 행만 (#26)
          사고유형은 보행노인 · 보행어린이 · 스쿨존어린이 · 자전거 4가지뿐이다(일반 보행자 · 무단횡단 다발지는 이 표에 없다)

이 파일은 받기만 한다(원본 바이트 그대로). 정제 · 가공은 public_data.py 가 한다.
공공데이터포털은 화면의 '다운로드' 버튼이 부르는 주소를 같은 순서로 부른다(로그인 불필요).
표준데이터 전국본은 화면에서 5만 행까지만 받게 돼 있어, 서버에 빈 페이지가 나올 때까지 끝까지 읽는다.
"""
import csv
import datetime
import hashlib
import http.cookiejar
import io
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "public" / "raw"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
OSM_UA = "ansan-night-walk-research/0.1 (public-data prototype)"
DGK = "https://www.data.go.kr"
# 안산 24개 동을 덮는 사각형(위도 · 경도) — data/raw/overpass_쿼리.txt 와 같은 범위
BBOX = (37.2675, 126.7175, 37.3775, 126.9396)

_cj = http.cookiejar.CookieJar()
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))


def log(m):
    print(m, flush=True)


def _req(url, data=None, headers=None, timeout=300):
    h = {"User-Agent": UA, **(headers or {})}
    body = urllib.parse.urlencode(data, doseq=True).encode() if isinstance(data, dict) else data
    with _op.open(urllib.request.Request(url, data=body, headers=h), timeout=timeout) as r:
        return r.read(), dict(r.headers)


def _json(url, params=None, **kw):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    b, _ = _req(url, headers={"Accept": "application/json"}, **kw)
    return json.loads(b.decode("utf-8-sig"))


def _save(name, data, **meta):
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / name).write_bytes(data)
    man = json.loads((RAW / "MANIFEST.json").read_text(encoding="utf-8")) if (RAW / "MANIFEST.json").exists() else {}
    man[name] = {"retrieved": datetime.date.today().isoformat(), "bytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest(), **meta}
    (RAW / "MANIFEST.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"    [v] {name} · {len(data):,} bytes")


# ══ 공공데이터포털 ═══════════════════════════════════════════════════
def dgk_institution_file(pk, keyword):
    """표준데이터 pk 의 기관별 업로드 파일 중 keyword 가 들어간 것 → (상세키, 파일 정보 dict)."""
    html = _req(f"{DGK}/tcs/dss/stdFileList.do?" + urllib.parse.urlencode(
        {"publicDataPk": pk, "searchKeyword2": keyword, "pageIndex": 1}))[0].decode("utf-8", "replace")
    keys = re.findall(r'data-public-pk="([^"]+)"', html)
    if not keys:
        return None, None
    det = _req(f"{DGK}/tcs/dss/selectDpkDetailInfo.do", data={"publicDataDetailPk": keys[0]})[0].decode("utf-8", "replace")
    m = re.search(r"fn_fileDataDown\('(\d+)',\s*'([^']+)',\s*'([^']+)',\s*'(\d+)'", det)
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", det))
    info = {k: (re.search(k + r"\s+(\S+)", txt) or [None, ""])[1] for k in ("수정일", "등록일", "전체 행 수")}
    return keys[0], {"atch": m.group(3), "sn": m.group(4), **info} if m else None


def dgk_download(pk, detail_pk, atch, sn, referer):
    """파일데이터 1건 — 다운로드 등록 → 횟수 제한 확인 → 파일."""
    _req(referer)
    ax = {"X-Requested-With": "XMLHttpRequest", "Referer": referer}
    j = json.loads(_req(f"{DGK}/tcs/dss/selectFileDataDownload.do", headers=ax, data={
        "publicDataDetailPk": detail_pk, "publicDataPk": pk, "atchFileId": atch, "fileDetailSn": sn,
        "publicDataTyCode": "PR0051"})[0].decode("utf-8-sig"))
    if not j.get("status"):
        raise SystemExit(f"[X] 다운로드 등록 실패: {j.get('error')}")
    lim = json.loads(_req(f"{DGK}/cmm/cmm/check-limit.json", headers=ax,
                          data={"atchFileId": j["atchFileId"], "fileDetailSn": j["fileDetailSn"]})[0].decode("utf-8-sig"))
    if lim.get("needCaptcha"):
        raise SystemExit("[X] 공공데이터포털이 보안문자를 요구합니다 — 브라우저에서 직접 받아 data/public/raw 에 두십시오")
    nm = (j.get("dataSetFileDetailInfo") or {}).get("dataNm") or "data"
    b, _ = _req(f"{DGK}/cmm/cmm/fileDownload.do?atchFileId={j['atchFileId']}&fileDetailSn={j['fileDetailSn']}"
                f"&dataNm={urllib.parse.quote(nm)}", headers={"Referer": referer})
    return b


def dgk_std_rows(pk, keep):
    """표준데이터 전국본을 끝까지 읽어 keep(행) 이 참인 행만 → (머리글, 행들, 기관별 행 수)."""
    h = _json(f"{DGK}/download/columList.json?pk={pk}&ext=CSV")
    t = h["tableVO"]
    codes = [c["columCode"] for c in h["columList"]]
    names = [c["columNm"] for c in h["columList"]]
    base = {"colNmList": t["colNmList"], "totalCount": h["totalCount"], "svcTableNm": t["svcTableNm"], "perPage": 10000}
    out, per_inst, page = [], {}, 1
    while True:
        rows = _json(f"{DGK}/download/standard.json", {**base, "page": page})
        if not rows:
            break
        for r in rows:
            inst = r.get("INSTT_NM") or ""
            per_inst[inst] = per_inst.get(inst, 0) + 1
            if keep(r):
                out.append(["" if r.get(c) is None else r.get(c) for c in codes])
        log(f"    {pk} page {page}: {len(rows):,}행 (누적 안산 {len(out):,})")
        page += 1
        time.sleep(1.0)
    return names, out, per_inst


def _csv_bytes(names, rows):
    s = io.StringIO()
    w = csv.writer(s)
    w.writerow(names)
    w.writerows(rows)
    return s.getvalue().encode("utf-8-sig")


def get_lights():
    log("[lights] 안산시 보안등 (전국보안등정보표준데이터 15017320 · 경기도 안산시 제공분)")
    dpk, f = dgk_institution_file("15017320", "안산")
    if not f:
        raise SystemExit("[X] 안산시 보안등 파일을 찾지 못했습니다")
    b = dgk_download("15017320", dpk, f["atch"], f["sn"], f"{DGK}/data/15017320/standard.do")
    _save("보안등_경기도안산시.csv", b, source="공공데이터포털 전국보안등정보표준데이터(15017320) · 제공기관 경기도 안산시",
          url=f"{DGK}/data/15017320/standard.do", detail_pk=dpk, portal_modified=f.get("수정일"),
          portal_rows=f.get("전체 행 수"), license="공공누리 · 이용허락범위 제한 없음")


def _ansan(r):
    return "안산" in (r.get("INSTT_NM") or "")


def get_std(pk, name, label):
    log(f"[{label}] {name} 전국본 → 경기도 안산시 행만 ({pk})")
    names, rows, per = dgk_std_rows(pk, _ansan)
    gg = {k: v for k, v in sorted(per.items()) if k.startswith("경기도")}
    _save(f"{label}_표준데이터_안산.csv", _csv_bytes(names, rows), source=f"공공데이터포털 {name}({pk}) 전국본 중 제공기관 경기도 안산시",
          url=f"{DGK}/data/{pk}/standard.do", rows=len(rows), national_rows=sum(per.values()),
          gyeonggi_rows_by_institution=gg,
          note="전국본의 기관별 행 수가 500 에서 잘린 기관이 많다(경기 시군 다수가 정확히 500) — 전수가 아니다",
          license="공공누리 · 이용허락범위 제한 없음")


def overpass(q, tries=3):
    """Overpass 는 공용 서버라 자주 바쁘다(504 · 시간 초과) — 서버를 바꿔 가며 쉬었다 다시."""
    eps = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter")
    for k in range(tries):
        for ep in eps:
            try:
                return _req(ep, data={"data": q}, headers={"User-Agent": OSM_UA}, timeout=200)[0]
            except Exception as e:
                log(f"    {ep} 실패: {e}")
        time.sleep(30 * (k + 1))
    raise SystemExit("[X] Overpass 서버 응답 없음 — 잠시 뒤 python src/collect_public.py osm")


def get_osm():
    s, w, n, e = BBOX
    log("[osm] 경찰 · 119 시설")
    q = (f"[out:json][timeout:180];(nwr[\"amenity\"=\"police\"]({s},{w},{n},{e});"
         f"nwr[\"amenity\"=\"fire_station\"]({s},{w},{n},{e}););out center tags;")
    _save("osm_police_fire.json", overpass(q), source="OpenStreetMap Overpass API (amenity=police|fire_station)",
          query=q, license="ODbL 1.0 © OpenStreetMap contributors")
    log("[osm] 철도역")
    q = (f"[out:json][timeout:180];(node[\"railway\"=\"station\"]({s - .07},{w - .02},{n + .02},{e + .01}););out body;")
    _save("osm_stations.json", overpass(q), source="OpenStreetMap Overpass API (railway=station)",
          query=q, license="ODbL 1.0 © OpenStreetMap contributors")


def get_korail():
    log("[korail] 광역철도 시간대별 승하차인원 (최신 월)")
    board = "https://info.korail.com/info/selectBbsNttList.do?bbsNo=425&key=867"
    html = _req(board)[0].decode("utf-8", "replace")
    ntt = re.findall(r"nttNo=(\d+)", html)
    if not ntt:
        raise SystemExit("[X] 코레일 게시판에서 글을 찾지 못했습니다")
    view = f"https://info.korail.com/info/selectBbsNttView.do?key=867&bbsNo=425&nttNo={ntt[0]}"
    v = _req(view)[0].decode("utf-8", "replace")
    for no in re.findall(r"downloadBbsFile\.do\?atchmnflNo=(\d+)", v):
        b, hd = _req(f"https://info.korail.com/info/downloadBbsFile.do?atchmnflNo={no}", headers={"Referer": view})
        cd = hd.get("Content-Disposition", "")
        fn = urllib.parse.unquote(cd.encode("latin-1").decode("utf-8", "replace")).split("filename=")[-1].strip('"; ')
        if "시간대별" in fn:
            ym = re.search(r"(\d{4})년\s*(\d{1,2})월", fn)
            tag = f"{ym.group(1)}{int(ym.group(2)):02d}" if ym else "latest"
            _save(f"korail_시간대별승하차_{tag}.xlsx", b, source="한국철도공사 수송통계 게시판(공공데이터포털 15154382 연결)",
                  url=view, original_name=fn, license="공공누리 · 이용허락범위 제한 없음")
            return
    raise SystemExit("[X] 시간대별 승하차 첨부를 찾지 못했습니다")


def get_accidents():
    """교통사고 다발지역 — 기관이 도로교통공단 하나라 제공기관이 아니라 '사고다발지역시도시군구'로 안산을 고른다."""
    log("[accidents] 전국교통사고다발지역표준데이터(15029185) 전국본 → 시도시군구가 안산인 행만")
    names, rows, per = dgk_std_rows("15029185", lambda r: "안산" in (r.get("CTPRVN_SIGNGU_NM") or ""))
    _save("교통사고다발지역_표준데이터_안산.csv", _csv_bytes(names, rows),
          source="공공데이터포털 전국교통사고다발지역표준데이터(15029185) — 한국도로교통공단, 시도시군구에 '안산'이 들어간 행",
          url=f"{DGK}/data/15029185/standard.do", rows=len(rows), national_rows=sum(per.values()),
          note="사고유형은 보행노인 · 보행어린이 · 스쿨존어린이 · 자전거 4가지뿐. 일반 보행자 · 무단횡단 · 사고 단위 좌표는 이 표에 없다",
          license="공공누리 · 이용허락범위 제한 없음")


JOBS = {"lights": get_lights,
        "cctv": lambda: get_std("15013094", "전국CCTV표준데이터", "CCTV"),
        "bells": lambda: get_std("15028206", "비상벨 위치 표준데이터", "비상벨"),
        "osm": get_osm, "korail": get_korail, "accidents": get_accidents}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for k in (sys.argv[1:] or list(JOBS)):
        JOBS[k]()
    log(f"\n[v] {RAW}")
