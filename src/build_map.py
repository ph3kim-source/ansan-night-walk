# -*- coding: utf-8 -*-
"""
안산 밤길지도 — 공개 자료만 담은 지도 한 장(html) 만들기 (수정사항 #21)
실행:  py -3.12 src/build_map.py            → html/안산_밤길지도.html · html/지도_열기.bat
보기:  html/지도_열기.bat 더블클릭(이 PC 127.0.0.1:8787) — 카카오 JavaScript 키가 없으면 OpenStreetMap 바탕으로 뜬다

· 화면 구성은 서울시 '스마트서울맵' 테마지도(이동약자 산책로 지도)의 틀을 따랐다 — 왼쪽 레이어 목록 · 위 '현 지도의 콘텐츠 수'와
  주소/장소 이동 · 오른쪽 도구 막대 · 아래 가운데 주소. 그쪽 코드 · 그림 · 이름은 쓰지 않았다(src/map_template.html 은 새로 짰다)
· **공개 자료만 담는다** — 파일 하나라 밖으로 돌기 쉽다. 민간 비개방 자료(활성도 · 사람 수)는 넣지 않는다(CLAUDE.md §6)
· 역 귀갓길 = #15 의 '역에서 내려 걸어서 집 가는 밤 흐름'(코레일 하차 × 보행망 최단경로 × 집 쪽 안분). 블록(교차로 사이) 단위,
  큰길(가로등 구간) · 보안등 있는 골목 · 보안등 없는 골목으로 나눈다. 사람 수 대신 '흐름 상위 N%'(1 = 가장 많이 지나는 1%)만 보인다
· '안산시 공식 서비스 아님' 문구를 지우지 않는다 — 시청 지도로 읽히면 안 된다(tests/test_map.py 가 확인)
"""
import json
import pathlib
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import params as PM  # noqa: E402
import night_core as NC  # noqa: E402

PROC = ROOT / "data" / "processed"
PUB = ROOT / "data" / "public" / "derived"
OUT = ROOT / "html"
TEMPLATE = ROOT / "src" / "map_template.html"
PORT = 8787


def chains(G, eids):
    """블록의 간선들을 이어진 좌표 줄로 — links() 블록은 갈래 없는 사슬이지만, 남는 간선은 따로 줄을 만든다."""
    adj = defaultdict(list)
    for e in eids:
        adj[G.u[e]].append((G.v[e], e))
        adj[G.v[e]].append((G.u[e], e))
    left, out = set(int(e) for e in eids), []
    while left:
        ends = [n for n, lst in adj.items() if sum(e in left for _, e in lst) == 1]
        cur = ends[0] if ends else G.u[next(iter(left))]
        seq = [cur]
        while True:
            nxt = [(n, e) for n, e in adj[cur] if e in left]
            if not nxt:
                break
            n, e = nxt[0]
            left.discard(e)
            seq.append(n)
            cur = n
        out.append(np.round(G.lonlat[seq][:, ::-1], 5).tolist())          # [위도, 경도]
    return out


def walk_layer(G):
    ep = pd.read_csv(PUB / "edge_public.csv")
    f = ep[["f22", "f23", "f24"]].sum(axis=1).to_numpy()                 # 밤 10시~막차 그 간선을 지나는 사람/밤
    lit = ep["lights_n"].to_numpy() > 0
    major = ep["major"].to_numpy(bool)
    lab = G.links()
    L = G.length
    df = pd.DataFrame({"b": lab, "L": L, "fL": f * L, "maj": major * L, "lit": lit & ~major, "e": np.arange(G.m)})
    g = df.groupby("b")
    blk = pd.DataFrame({"len": g["L"].sum(), "flow": g["fL"].sum() / g["L"].sum(), "maj": g["maj"].sum() / g["L"].sum(),
                        "anylit": g["lit"].any(), "edges": g["e"].apply(list)})
    lim = PM.MAP_WALK_MIN.value
    blk = blk[(blk["flow"] >= lim["flow"]) & (blk["len"] >= lim["len_m"])].copy()
    blk["kind"] = np.where(blk["maj"] >= 0.5, "major", np.where(blk["anylit"], "lit", "dark"))
    # 사람 수 대신 순위 — 그린 블록 중 흐름 상위 몇 %인가(1 = 가장 많이 지나는 1%)
    blk["idx"] = np.maximum(1, np.ceil(100 * (1 - blk["flow"].rank(pct=True)) + 1e-9)).astype(int)
    feats = [{"k": r.kind, "i": int(r.idx), "m": int(round(r.len)), "p": chains(G, r.edges)} for r in blk.itertuples()]
    return feats, blk


def cell(v):
    """표시용 문자열 — 2015.0 같은 정수 실수는 2015 로."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return str(int(v))
    return str(v)


def pts(df, cols, nd=5):
    d = df.dropna(subset=["lat", "lon"])
    return [[round(float(r["lat"]), nd), round(float(r["lon"]), nd)] + [cell(r[c]) for c in cols]
            for r in d.to_dict("records")]


def dongs():
    import geopandas as gpd
    d = gpd.read_file(PROC / "dong.geojson").to_crs(5179)
    d["geometry"] = d.geometry.simplify(15)
    d = d.to_crs(4326)
    name = "ADM_NM" if "ADM_NM" in d.columns else d.columns[0]
    feats = []
    for r in d.itertuples():
        geom = r.geometry
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        rings = [np.round(np.asarray(p.exterior.coords)[:, ::-1], 5).tolist() for p in polys]
        feats.append({"n": str(getattr(r, name)), "r": rings})
    return feats


def main():
    nodes = pd.read_csv(PROC / "nodes.csv", encoding="utf-8-sig")
    edges = pd.read_csv(PROC / "edges.csv")
    G = NC.NightGraph(nodes, edges)
    walk, blk = walk_layer(G)
    police = pd.read_csv(PUB / "police.csv", encoding="utf-8-sig")
    police = police[police["night_open"].astype(bool)]
    st = pd.read_csv(PUB / "stations.csv", encoding="utf-8-sig")
    st["night"] = st["night"].round().astype(int)
    st["ind"] = np.where(st["industrial"].astype(bool), "산업단지역", "")
    anc = pd.read_csv(PROC / "anchors.csv", encoding="utf-8-sig")
    anc = anc[anc["kind"] == "앵커"]
    lights = pd.read_csv(PUB / "lights.csv", encoding="utf-8-sig")
    cctv = pd.read_csv(PUB / "cctv.csv", encoding="utf-8-sig")
    bells = pd.read_csv(PUB / "bells.csv", encoding="utf-8-sig")
    rep = json.loads((PUB / "report.json").read_text(encoding="utf-8"))
    month = str(st["month"].iloc[0]) if len(st) else ""
    data = {
        "walk": walk,
        "police": pts(police, ["name", "kind"]),
        "station": pts(st, ["station", "line", "night", "ind"]),
        "anchor": pts(anc, ["name", "biz"]),
        "light": pts(lights, ["보안등위치명", "설치형태", "설치연도"]),
        "cctv": pts(cctv, ["설치목적구분", "카메라대수"]),
        "bell": pts(bells, ["설치위치", "설치장소유형"]),
        "dong": dongs(),
        "meta": {"month": month, "lights_date": rep.get("lights", {}).get("기준일", ""),
                 "walk_min": PM.MAP_WALK_MIN.value["flow"], "walk_len": PM.MAP_WALK_MIN.value["len_m"],
                 "built": pd.Timestamp.now().strftime("%Y-%m-%d")},
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")   # 스크립트가 끊기지 않게
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", blob)
    OUT.mkdir(exist_ok=True)
    (OUT / "안산_밤길지도.html").write_text(html, encoding="utf-8")
    bat = ("@echo off\r\nchcp 65001 >nul\r\ncd /d \"%~dp0\"\r\n"
           "rem 안산 밤길지도 - 이 PC에서만 열린다(127.0.0.1). 카카오 · 브이월드 바탕은 각 사이트에 http://localhost:{p} 를 등록해야 뜬다(키가 없으면 OpenStreetMap)\r\n"
           "start \"\" http://localhost:{p}/안산_밤길지도.html\r\n"
           "py -3.12 -m http.server {p} --bind 127.0.0.1\r\n").format(p=PORT)
    (OUT / "지도_열기.bat").write_bytes(bat.encode("utf-8"))
    kinds = blk["kind"].value_counts().to_dict()
    print(f"[v] html/안산_밤길지도.html · {len(html) / 1e6:.2f} MB · 귀갓길 블록 {len(walk):,}개 {kinds} · "
          f"길이 {blk['len'].sum() / 1000:,.0f}km · 지구대 {len(data['police'])} · 역 {len(data['station'])} · "
          f"심야 업종 {len(data['anchor']):,} · 보안등 {len(data['light']):,} · CCTV {len(data['cctv'])} · 비상벨 {len(data['bell'])}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
