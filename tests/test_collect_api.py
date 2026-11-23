# -*- coding: utf-8 -*-
"""인증키 API 수집기 검증 (수정사항 #17) — py -3.12 -m pytest tests/test_collect_api.py -q
네트워크를 쓰지 않는다. collect_api.GET 을 가짜 응답으로 바꿔 끼우고, 저장은 임시 폴더에 한다."""
import json
import pathlib
import sys
import urllib.parse

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import collect_api as CA  # noqa: E402

KEY = "ab+c/d=XYZ"          # Decoding 키처럼 + / = 가 든 가짜 키


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(CA, "RAW", tmp_path / "raw")
    return tmp_path / "raw"


def fake(handler):
    """handler(url, params) → dict. 진짜 http_get 처럼 (바이트, 키를 지운 주소)를 돌려준다."""
    def get(url, params, secrets=(), **_):
        return json.dumps(handler(url, params)).encode("utf-8"), CA.mask(CA.build_url(url, params), secrets)
    return get


def test_load_env(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# 주석\nSGIS_KEY = "abc"\nVWORLD_KEY=\nDATA_GO_KR_KEY=k+/=\n', encoding="utf-8")
    env = CA.load_env(p, environ={"VWORLD_KEY": "vw", "UNRELATED": "x"})
    assert env == {"SGIS_KEY": "abc", "DATA_GO_KR_KEY": "k+/=", "VWORLD_KEY": "vw"}


def test_mask_hides_raw_and_encoded_key():
    url = CA.build_url("https://x/y", {"serviceKey": KEY, "pageNo": 1}) + "&raw=" + KEY
    out = CA.mask(url, (KEY,))
    assert KEY not in out and urllib.parse.quote(KEY, safe="") not in out
    assert out.count("***") == 2


def test_tiles_cover_bbox_without_overlap():
    t = CA.tiles()
    s, w, n, e = CA.BBOX
    assert (min(b[0] for b in t), min(b[1] for b in t)) == (w, s)
    assert max(b[2] for b in t) == pytest.approx(e) and max(b[3] for b in t) == pytest.approx(n)
    area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in t)
    assert area == pytest.approx((e - w) * (n - s))           # 빈 곳 · 겹친 곳 없음
    assert len(t) == 6 * 12                                    # 0.11° ÷ 0.02 → 6줄, 0.2221° ÷ 0.02 → 12칸


def test_vworld_pages_dedup_and_not_found(raw, monkeypatch):
    """칸 1은 2쪽, 칸 2는 칸 1과 겹친 피처 하나, 나머지 칸은 NOT_FOUND → 피처 3개로 합쳐진다."""
    monkeypatch.setattr(CA, "VW_LAYERS", {"LT_C_TEST": "시험"})
    monkeypatch.setattr(CA, "tiles", lambda: [(0, 0, 1, 1), (1, 0, 2, 1), (2, 0, 3, 1)])
    monkeypatch.setattr(CA.time, "sleep", lambda s: None)
    feat = lambda i: {"type": "Feature", "id": f"LT_C_TEST.{i}", "properties": {"i": i}, "geometry": None}  # noqa: E731

    def handler(url, p):
        assert p["key"] == KEY and p["data"] == "LT_C_TEST" and p["size"] == CA.VW_PAGE
        box, page = p["geomfilter"], p["page"]
        if box == "BOX(0,0,1,1)":
            fs = [feat(1), feat(2)] if page == 1 else [feat(3)]
            return {"response": {"status": "OK", "page": {"total": "2", "current": str(page)},
                                 "result": {"featureCollection": {"features": fs}}}}
        if box == "BOX(1,0,2,1)":
            return {"response": {"status": "OK", "page": {"total": "1"},
                                 "result": {"featureCollection": {"features": [feat(2)]}}}}
        return {"response": {"status": "NOT_FOUND"}}

    monkeypatch.setattr(CA, "GET", fake(handler))
    CA.job_vworld({"VWORLD_KEY": KEY, "VWORLD_DOMAIN": "http://localhost"})
    out = json.loads((raw / "vworld" / "LT_C_TEST.geojson").read_text(encoding="utf-8"))
    assert sorted(f["id"] for f in out["features"]) == ["LT_C_TEST.1", "LT_C_TEST.2", "LT_C_TEST.3"]
    man = (raw / "MANIFEST.json").read_text(encoding="utf-8")
    assert KEY not in man and json.loads(man)["vworld/LT_C_TEST.geojson"]["n"] == 3


def test_vworld_error_skips_layer(raw, monkeypatch, capsys):
    """키 오류 같은 거절은 그 레이어만 건너뛰고 원인을 찍는다(파일을 만들지 않는다)."""
    monkeypatch.setattr(CA, "VW_LAYERS", {"LT_C_BAD": "시험"})
    monkeypatch.setattr(CA, "tiles", lambda: [(0, 0, 1, 1)])
    monkeypatch.setattr(CA, "GET", fake(lambda u, p: {"response": {"status": "ERROR", "error": {
        "code": "INVALID_KEY", "text": "등록되지 않은 인증키입니다."}}}))
    CA.job_vworld({"VWORLD_KEY": KEY})
    assert "INVALID_KEY" in capsys.readouterr().out
    assert not (raw / "vworld" / "LT_C_BAD.geojson").exists()


def test_sgis_reauth_once_on_401(monkeypatch):
    calls = []

    def handler(url, p):
        calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("authentication.json"):
            return {"errCd": 0, "result": {"accessToken": f"T{calls.count('authentication.json')}"}}
        if p["accessToken"] == "T1":
            return {"errCd": -401, "errMsg": "인증정보가 존재하지 않습니다"}
        return {"errCd": 0, "result": [{"adm_cd": "3109151001", "tot_ppltn": "500"}]}

    monkeypatch.setattr(CA, "GET", fake(handler))
    sg = CA.Sgis({"SGIS_KEY": "sgis-service-id-0001", "SGIS_SECRET": "sgis-secret-key-0002"})
    d, b, shown = sg.call("stats/population.json", year=2024, adm_cd="31091510", low_search=1)
    assert d["result"][0]["tot_ppltn"] == "500"
    assert calls == ["authentication.json", "population.json", "authentication.json", "population.json"]
    assert "T2" not in shown                                   # 토큰도 주소에서 지운다


def test_cctv_pages_until_total_and_no_key_in_manifest(raw, monkeypatch):
    rows = [{"MNG_NO": str(i), "WGS84_LAT": "37.3", "WGS84_LOT": "126.8"} for i in range(250)]

    def handler(url, p):
        assert url == CA.DGK_CCTV and p["serviceKey"] == KEY and p["cond[OPN_ATMY_GRP_CD::EQ]"] == CA.ANSAN_OPN
        a = (p["pageNo"] - 1) * p["numOfRows"]
        return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                             "body": {"totalCount": 250, "items": {"item": rows[a:a + p["numOfRows"]]}}}}

    monkeypatch.setattr(CA, "GET", fake(handler))
    CA.job_cctv({"DATA_GO_KR_KEY": urllib.parse.quote(KEY, safe="")})   # Encoding 키를 넣어도 된다
    out = json.loads((raw / "cctv" / f"cctv_info_{CA.ANSAN_OPN}.json").read_text(encoding="utf-8"))
    assert len(out) == 250 and out[-1]["MNG_NO"] == "249"
    man = (raw / "MANIFEST.json").read_text(encoding="utf-8")
    assert KEY not in man and urllib.parse.quote(KEY, safe="") not in man and "pageNo=1~3" in man
