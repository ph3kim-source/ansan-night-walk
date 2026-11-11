# -*- coding: utf-8 -*-
"""
야간 활성도 점수 — 가중치를 쓰지 않는다.

기획 원안
---------
    활성도 = (22~02시 유동인구 밀도) + (반경 100m 내 결제 가맹점 수 × 가중치)

이 식에는 근거를 댈 수 없는 수가 최소 두 개 있다.
  ① 두 항을 더하려면 단위가 같아야 하는데 '명'과 '개'다 → 암묵적 정규화 상수
  ② 명시된 '가중치'
4안에서 이것과 같은 모양의 가중합(집객력 = w1·상가 + w2·노선 + w3·수요 - w4·거리)을 쓴 결과,
가중치를 흔들자 집결지의 50~85%가 뒤바뀌어 방식 자체를 폐기한 전례가 있다.

3안의 정의
----------
    활성도 = min( 분위(야간 유동인구), 분위(심야 앵커 접근성) )

'사람도 있고, 문 연 가게도 있어야 환한 길이다. 둘 중 하나라도 없으면 아니다.'
연언(AND)이므로 두 항을 더할 필요가 없고, 따라서 가중치도 정규화 상수도 없다.
min 은 둘 중 나쁜 쪽을 따르므로 안전 방향으로 보수적이다.

왜 분위(percentile)인가
-----------------------
통신·카드 값은 표본을 모집단으로 확대한 추정 가중치다(인벤토리 Q-21).
절대값 비교가 금지돼 있으므로 순위로만 다룬다.

심야 앵커에 유흥업소를 넣지 않는 이유
-------------------------------------
안산 상가 34,489곳 중 심야에 결제가 일어나는 업종을 세면
유흥 계열 1,913곳 > 심야 앵커(편의점·주유소·PC방) 1,021곳으로 1.87배다.
'결제가 발생한 가맹점 수'를 그대로 더하면 점수 1위는 유흥가가 된다.
유흥가는 심야 활성도가 가장 높은 곳이지만, 그것이 '안전한 길'이라는 근거는 없다.
→ 업종 필터는 선택이 아니라 필수다. (src/validate.py::e_nightlife 에서 재현)
"""
import numpy as np
import pandas as pd


def pct(s):
    """분위 정규화 0~1. 동점은 평균 순위."""
    return pd.Series(s).rank(pct=True).to_numpy()


def cell_score(cells, flow_col="pop_night", anchor_col="anchor_d", anchor_is_distance=True):
    """셀별 야간 활성도.

    flow_col          야간 유동인구 (프로토타입: 1km 격자 인구 안분 / 실데이터: DS-032·014)
    anchor_col        심야 앵커 지표 (프로토타입: 최근접 거리 / 실데이터: DS-054 결제건수)
    anchor_is_distance  거리는 작을수록 좋으므로 부호를 뒤집는다
    """
    f = pct(cells[flow_col])
    a = pct(-cells[anchor_col] if anchor_is_distance else cells[anchor_col])
    return np.minimum(f, a), f, a


def edge_score(cells, edges, act):
    """간선 활성도 = 양 끝 셀의 평균. 어두움 = 1 - 활성도."""
    e = edges.copy()
    e["act"] = (act[e["u"].to_numpy()] + act[e["v"].to_numpy()]) / 2
    e["dark"] = 1 - e["act"]
    return e


def dark_threshold(edges, q):
    """저활성(빨간 구간) 임계. 길이 가중 분위."""
    o = edges.sort_values("act")
    cum = o["len_m"].cumsum() / o["len_m"].sum()
    return float(o.loc[cum >= q, "act"].iloc[0])
