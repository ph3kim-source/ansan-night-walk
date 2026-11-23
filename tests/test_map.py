# -*- coding: utf-8 -*-
"""안산 밤길지도(html) 검증 (수정사항 #21) — py -3.12 -m pytest tests/test_map.py -q
지도는 파일 하나라 밖으로 돌기 쉽다 — 공개 자료만 들어 있어야 한다. 화면 문구에 '안전' · '안심' 이 없어야 한다(CLAUDE.md 0절)."""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def test_template_has_no_forbidden_words():
    t = (ROOT / "src" / "map_template.html").read_text(encoding="utf-8")
    assert re.findall("안전|안심", t) == []
    assert "공식 서비스 아님" in t and "공식 서비스가 아닙니다" in t        # 시청 지도로 읽히지 않게


def test_build_map_public_layers_only(tmp_path, monkeypatch):
    import build_map as BM
    monkeypatch.setattr(BM, "OUT", tmp_path)
    BM.main()
    html = (tmp_path / "안산_밤길지도.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r"const DATA = (\{.*?\});\n", html, re.S).group(1))
    assert set(data) == {"walk", "police", "station", "anchor", "light", "cctv", "bell", "dong", "meta"}
    assert {w["k"] for w in data["walk"]} == {"major", "lit", "dark"} and len(data["walk"]) > 100
    assert all(1 <= w["i"] <= 100 for w in data["walk"])                    # 사람 수가 아니라 순위(상위 %)
    assert len(data["dong"]) == 24
    assert "data/real" not in html and "terms.npz" not in html               # 민간 실데이터가 섞이지 않았다
    assert (tmp_path / "지도_열기.bat").read_bytes().startswith(b"@echo off\r\n")
