# -*- coding: utf-8 -*-
"""
경로 탐색 — '우회 예산' 방식. 근거 없는 가중치를 남기지 않기 위한 구조.

문제
----
기획 원안은 "최단경로를 쓰되 활성도 높은 노드를 경유하도록 보정"이라고 했다.
이것을 그대로 코드로 옮기면 반드시 이런 모양이 된다.

    cost(e) = len(e) × (1 + α · dark(e))          # α = 어두운 길을 얼마나 싫어하는가

α 는 근거를 댈 수 없다. α=1 과 α=5 의 추천 경로가 다르고, 어느 쪽이 옳은지 말할 방법이 없다.
4안이 집객력 가중합을 폐기한 것과 똑같은 함정이다.

해결
----
α 를 고정하지 않는다. 대신 시민이 화면에서 정하는 값을 받는다.

    "최단거리보다 몇 % 더 걸어도 괜찮으신가요?"   →  δ (우회 예산)

그리고 δ 를 다 쓰는 가장 큰 α 를 이분탐색으로 역산한다.

    maximize α   s.t.   실제거리(α) ≤ 최단거리 × (1 + δ)

α 는 더 이상 파라미터가 아니라 δ 의 함수다. 근거가 필요한 상수가 0개가 된다.
δ 는 사용자가 정하므로 근거가 필요 없다(등급 X).

결과도 이 구조에서 자동으로 검증 가능한 형태로 나온다.
    "3분 더 걸어서, 혼자 걷는 구간을 420m → 90m 로 줄였습니다"
거리·시간·저활성 노출이 전부 숫자라 사후에 맞는지 틀린지 확인할 수 있다.

α 의 단조성
-----------
α 가 커지면 어두운 간선의 비용이 단조 증가하므로 최적경로의 '실제 길이'도
넓은 의미에서 단조 증가한다. 완전한 단조는 아니지만(이산 경로 전환) 이분탐색으로
충분히 수렴하며, 마지막에 예산 초과 여부를 직접 확인해 넘으면 α 를 낮춘다.
"""
import numpy as np
import networkx as nx


def build(cells, edges):
    G = nx.Graph()
    G.add_nodes_from(range(len(cells)))
    for u, v, L, d in zip(edges["u"], edges["v"], edges["len_m"], edges["dark"]):
        G.add_edge(int(u), int(v), len_m=float(L), dark=float(d))
    return G


def _path(G, s, t, alpha):
    for _, _, a in G.edges(data=True):
        a["w"] = a["len_m"] * (1 + alpha * a["dark"])
    return nx.shortest_path(G, s, t, weight="w")


def _stat(G, path, dark_thr):
    """경로 요약: 길이 / 저활성 노출 / 최장 연속 저활성 구간."""
    L = expo = run = worst = 0.0
    for u, v in zip(path[:-1], path[1:]):
        a = G[u][v]
        L += a["len_m"]
        if 1 - a["dark"] < dark_thr:
            expo += a["len_m"]
            run += a["len_m"]
            worst = max(worst, run)
        else:
            run = 0.0
    return {"len_m": L, "dark_m": expo, "worst_run_m": worst}


def plan(G, s, t, detour, dark_thr, alpha_max=50.0, iters=18):
    """우회 예산 detour(=δ) 안에서 저활성 노출이 가장 적은 경로.

    반환: dict(base=최단경로 요약, best=추천경로 요약, path=[node...], alpha=역산된 α)
    """
    base_p = _path(G, s, t, 0.0)
    base = _stat(G, base_p, dark_thr)
    budget = base["len_m"] * (1 + detour)

    lo, hi = 0.0, float(alpha_max)
    best_p, best_a = base_p, 0.0
    if _stat(G, _path(G, s, t, hi), dark_thr)["len_m"] <= budget:
        best_p, best_a, lo = _path(G, s, t, hi), hi, hi      # 예산이 남아돈다
    else:
        for _ in range(int(iters)):
            mid = (lo + hi) / 2
            p = _path(G, s, t, mid)
            if _stat(G, p, dark_thr)["len_m"] <= budget:
                lo, best_p, best_a = mid, p, mid
            else:
                hi = mid

    best = _stat(G, best_p, dark_thr)
    return {"base": base, "base_path": base_p, "best": best,
            "path": best_p, "alpha": best_a, "budget_m": budget}
