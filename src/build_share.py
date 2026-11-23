# -*- coding: utf-8 -*-
"""
공유 시연판 만들기 — ../3안_공유 (GitHub: ph3kim-source/ansan-night-walk)
실행:  python src/build_share.py

2안·4안과 같은 방식이다. 원본(3안)을 고치고 이 스크립트로 다시 만든다. 공유본을 직접 고치지 않는다.
담는 것: 시연 앱 실행과 가상 데이터 재생성에 필요한 코드·데이터 / 빼는 것: 연구 문서 · 작업 지침 · 로컬 실행 파일
★ 공유본은 GitHub 공개 저장소다 — data/proto 가 민간 실데이터로 적재돼 있으면 멈춘다(public_safe, #19).
  민간 실데이터 결과(data/real) · 원본 · API 원본(data/api) · .env 는 KEEP 에 넣지 않는다.
"""
import json
import os
import pathlib
import shutil
import stat

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "3안_공유"

KEEP = [
    "src/params.py", "src/score.py", "src/route.py", "src/osm.py", "src/prep.py", "src/validate.py", "src/alloc.py",
    "src/gen_docs.py", "src/app.py", "src/night_core.py", "src/geocode.py", "src/synth_inventory.py",
    "src/ingest_inventory.py", "src/proto_ui.py", "src/proto_app.py", "src/proto_pages", "src/build_share.py",
    "src/collect_public.py", "src/public_data.py", "src/validate_public.py", "src/collect_api.py", ".env.example",
    "tests/test_proto.py", "tests/test_alloc.py", "tests/test_public.py", "tests/test_collect_api.py",
    "tests/test_private.py",                       # 배포 차단 시험(실데이터 화면 시험은 실데이터가 없으면 건너뜀)
    "src/build_map.py", "src/map_template.html", "tests/test_map.py", "html",   # 밤길지도(#21) — 공개 자료만
    "src/build_app.py", "src/app", "src/build_runs.py", "tests/test_app.py",   # 시민용 웹 지도 앱(#24) — 임의값 판 · 공개 자료만
    "data/processed", "data/proto", "data/synthetic", "data/base", "data/bus", "data/geocode", "data/public",
    "data/raw/overpass_쿼리.txt", "data/raw/overpass_건물.txt",
]

PAGES_INDEX = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>안산 밤길 — 시연판</title><meta http-equiv="refresh" content="0; url=html/app/"></head>
<body style="font-family:sans-serif;padding:24px">
<p><a href="html/app/">안산 밤길 시민 앱으로 이동</a> (시연판 · 가상 데이터 · 안산시 공식 서비스 아님)</p>
<p><a href="html/%EC%95%88%EC%82%B0_%EB%B0%A4%EA%B8%B8%EC%A7%80%EB%8F%84.html">안산 밤길지도</a></p>
</body></html>
"""

README = """# 안산 밤길 — 시연판

밤에 걸어서 집에 갈 때 최단 경로 대신 사람이 다니고 가게가 문을 연 길을 고를 수 있게 하는
서비스 아이디어(3안)의 프로토타입입니다.

⚠️ 사람 수 · 카드 결제 · 이동 값은 가상 데이터입니다. 안산시 민간데이터(통신 · 카드 · 신용)
규격(파일명 · 컬럼명 · 코드값)을 따라 임의로 만든 값이며 실제 분포가 아닙니다. 안산시 공식 서비스가 아닙니다.
보안등(안산시 2022-12) · 역 시간대별 하차(코레일) · 지구대 위치(OpenStreetMap)는 공개 실데이터입니다
(`python src/collect_public.py` → `python src/public_data.py`). CCTV · 비상벨은 공개된 일부만 있어 지도에 표시만 합니다.

## 바로 열어 보기

**https://ph3kim-source.github.io/ansan-night-walk/** — 시민용 웹 지도 앱(시연판 · 가상 데이터)이 열립니다.
휴대폰에서는 이 주소를 연 뒤 브라우저 메뉴의 '홈 화면에 추가'로 앱처럼 설치할 수 있습니다(설치형 웹앱).
밤길지도는 `html/안산_밤길지도.html` 입니다.

## 둘러보기

**시민용 웹 지도 앱** — `html/app/` (밤길앱_열기.bat 또는 아래 명령)
- 밤길: 지도에서 출발 · 도착을 누르면 길을 세 가지(추천 경로 · 빠른 길 · 사람 많은 길 우선)로 보여 줍니다.
  추천 경로는 조금만 더 걸어 사람이 드문 구간을 줄인 길입니다. 요일 · 시각을 고를 수 있습니다.
- 러닝: 몇 분 달릴지 고르면 그 시간에 맞는 코스 3개를 '이런 분께'와 함께 추천합니다.
  달린 길이 지도에 그림이 되는 드로잉 런 12개(고래 · 토끼 · 고양이 · 물고기 · 거북이 · 공룡 · 꽃게 · 포도 · 갈매기 · 초승달 · 별 · 하트)와
  차가 다니지 않는 길 위주 코스 8개(산길 · 농로가 많은 코스는 밤에 어두울 수 있다고 알림). 휴대폰 GPS로 완주하면 뱃지(기록은 휴대폰 안에만).
  코스 목록은 낮 · 밤 기준이 다르고, 어르신 · 어린이 보행 사고가 잦았던 곳(도로교통공단)을 지나면 알립니다.
  코스는 시연용 예시입니다 — 운영할 때는 주민이 추천한 길을 담당자가 직접 확인한 뒤 올리는 방식을 생각하고 있습니다.
- 경로 계산은 브라우저 안에서 합니다(서버 없음).

**담당자 화면(Streamlit)** — 보안등 대조 · 개선 우선 구간, 시민 화면 검토(밤길 · 막차), 데이터 출처

## 로컬 실행

    python -m http.server 8787 --directory html      # 시민 앱: http://localhost:8787/app/
    pip install -r requirements.txt
    streamlit run src/proto_app.py                    # 담당자 화면

가상 데이터를 다시 만들려면 `python src/synth_inventory.py` → `python src/ingest_inventory.py`.
실데이터가 들어오면 `python src/ingest_inventory.py <원본 폴더>` 로 바꿔 끼웁니다(화면 코드는 그대로).

## 배포 설정

시작 파일 `src/proto_app.py`, 파이썬 3.12. 비밀 설정은 없습니다.

## 폴더

| 폴더 | 내용 |
|---|---|
| `html/app/` · `src/app/` · `src/build_app.py` | 시민용 웹 지도 앱(만든 결과 · 화면 코드 · 만드는 코드) |
| `src/build_runs.py` | 러닝 코스(드로잉 런 · 차 없는 길) 만들기 |
| `src/proto_app.py` · `src/proto_pages/` | 담당자 화면 |
| `data/proto/` | 앱이 읽는 계산 결과 |
| `data/synthetic/` | 가상 데이터 원천(인벤토리 규격 그대로) |
| `data/base/` · `data/bus/` · `data/geocode/` | 공개 기초 데이터 |
| `data/processed/` | 100m 점수 격자 · OSM 보행망 |

이 저장소는 원본 프로젝트에서 `src/build_share.py` 로 만든 복사본입니다. 고칠 때는 원본을 고치고 다시 만듭니다.

## 자료

통계청 SGIS(행정동 경계 · 1km 격자 인구), 국토교통부 TAGO(버스 노선 · 정류장), 소상공인시장진흥공단 상가(상권)정보,
행안부 동별 내 · 외국인 인구(주민등록), 공공데이터포털 안산시 보안등 · CCTV · 비상벨 표준데이터,
한국철도공사 광역철도 시간대별 승하차인원, 한국도로교통공단 전국교통사고다발지역표준데이터,
보행망 · 건물 · 경찰 시설 · 역 · 지도 © OpenStreetMap contributors (ODbL 1.0).
시민 앱 바탕지도: 브이월드(국토교통부) 일반 · 야간 배경지도(공공누리 제1유형) — 불러오지 못하면 OpenStreetMap.
"""

REQ = """streamlit==1.55.0
geopandas==1.1.1
pyogrio==0.11.1
shapely==2.1.2
pyproj==3.7.2
pandas==2.3.3
numpy==2.3.5
scipy==1.16.2
networkx==3.6.1
pydeck==0.9.1
plotly==6.7.0
"""

CONFIG = """[client]
toolbarMode = "minimal"

[browser]
gatherUsageStats = false
"""

GITIGNORE = """__pycache__/
.pytest_cache/
*.lock
.streamlit/secrets.toml
.env
data/api/
"""

# 데이터 파일은 줄바꿈 변환 없이 바이트 그대로
GITATTR = """*.csv -text
*.geojson -text
*.json -text
*.gz binary
*.npz binary
"""


TEXT_SUFFIX = (".py", ".html", ".md", ".txt", ".toml", ".example")


def text_leaks(root=ROOT, keep=None):
    """민간 실데이터로 잰 값이 공유 파일의 글자(코드 · 주석 · 문구)에 들어 있는가 → [(파일, 값)] (#22).
    값 목록은 data/real/share_block.txt — 실데이터가 있는 PC 에만 있고 공유본에는 안 실린다. 없으면 볼 것이 없다.
    data/ · html/ 은 숫자 표라 오탐이 많아 보지 않는다(html 지도는 tests/test_map.py 가 공개 자료만인지 본다)."""
    root = pathlib.Path(root)
    keep = KEEP if keep is None else keep
    blk = root / "data" / "real" / "share_block.txt"
    if not blk.exists():
        return []
    marks = [s.strip() for s in blk.read_text(encoding="utf-8-sig").splitlines() if s.strip() and not s.strip().startswith("#")]
    hits = []
    for rel in keep:
        if rel.startswith(("data/", "html")):
            continue
        p = root / rel
        for f in (sorted(p.rglob("*")) if p.is_dir() else [p]):
            if f.is_file() and f.suffix in TEXT_SUFFIX and "__pycache__" not in f.parts:
                t = f.read_text(encoding="utf-8", errors="replace")
                hits += [(f.relative_to(root).as_posix(), m) for m in marks if m in t]
    return hits


def public_safe(root=ROOT, keep=None):
    """공개 저장소에 실어도 되는가(#19 · #22). 아니면 SystemExit — 무엇이 문제인지 적는다."""
    keep = KEEP if keep is None else keep
    bad = [k for k in keep if k.split("/")[0] in (".env",) or k.startswith(("data/real", "data/api"))]
    if bad:
        raise SystemExit(f"[X] KEEP 에 비공개 경로가 있습니다: {bad}")
    leaks = text_leaks(root, keep)
    if leaks:
        raise SystemExit("[X] 민간 실데이터로 잰 값이 공유 파일 글자에 있습니다(data/real/share_block.txt 목록) — 내부 기록으로 옮기십시오: "
                         + " · ".join(f"{f} '{m}'" for f, m in leaks[:12]))
    rep = pathlib.Path(root) / "data" / "proto" / "ingest_report.json"
    meta = json.loads(rep.read_text(encoding="utf-8")).get("_meta", {}) if rep.exists() else {}
    if meta.get("synthetic") is not True:
        raise SystemExit("[X] data/proto 가 임의값이 아닙니다(ingest_report _meta.synthetic) — 공개 저장소에 실을 수 없습니다. "
                         "`py -3.12 src/ingest_inventory.py` 로 임의값을 다시 적재한 뒤 빌드하십시오")


def _writable(func, path, exc):
    """Windows '읽기 전용' 표시가 붙은 파일 · 폴더는 지우지 못한다(#23 — .streamlit 폴더에서 멈췄다) → 표시를 풀고 다시."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main():
    public_safe()
    keep_git = OUT / ".git"
    if OUT.exists():                                   # .git 만 남기고 다시 만든다
        for p in OUT.iterdir():
            if p != keep_git:
                if p.is_dir():
                    shutil.rmtree(p, onexc=_writable)
                else:
                    os.chmod(p, stat.S_IWRITE)
                    p.unlink()
    OUT.mkdir(exist_ok=True)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    for rel in KEEP:
        src, dst = ROOT / rel, OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=ign)
        else:
            shutil.copy2(src, dst)
    (OUT / "README.md").write_text(README, encoding="utf-8")
    (OUT / "requirements.txt").write_text(REQ, encoding="utf-8")
    (OUT / ".streamlit").mkdir(exist_ok=True)
    (OUT / ".streamlit" / "config.toml").write_text(CONFIG, encoding="utf-8")
    (OUT / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (OUT / ".gitattributes").write_text(GITATTR, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")              # GitHub Pages(#40) — 파일을 가공하지 않고 그대로 낸다
    (OUT / "index.html").write_text(PAGES_INDEX, encoding="utf-8")     # 저장소 첫 주소 → 시민 앱
    files = [p for p in OUT.rglob("*") if p.is_file() and ".git" not in p.parts]
    mb = sum(p.stat().st_size for p in files) / 1e6
    big = max(files, key=lambda p: p.stat().st_size)
    print(f"[v] {OUT} · 파일 {len(files)}개 · {mb:.1f}MB · 가장 큰 파일 {big.relative_to(OUT)} "
          f"{big.stat().st_size / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
