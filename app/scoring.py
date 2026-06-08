"""분양가 vs 주변 실거래가 비교 → 청약 매력도 점수(0~100).

핵심 아이디어
-------------
'안전마진(%)' = (주변 시세 평단가 - 분양 평단가) / 분양 평단가 × 100
  → 분양가가 주변 시세보다 쌀수록(=안전마진 큼) 당첨 즉시 시세차익 기대 → 고점.
  → 분양가가 시세보다 비싸면(안전마진 음수) 저점/비추천.

점수는 안전마진을 기본축으로 하고, 세대수(환금성)와 데이터 신뢰도로 가감합니다.
모든 임계값은 직관적으로 조정 가능합니다.
"""
from __future__ import annotations

import re
from statistics import median


def _exclusive_area(model: dict) -> float | None:
    """전용면적(㎡). 청약홈 APT Mdl은 HOUSE_TY(예: '084.6388A')에 전용면적을 담고 있음.

    실거래가(전용면적 기준)와 공정 비교를 위해 공급면적(SUPLY_AR)이 아닌 전용면적 사용.
    """
    ty = str(model.get("HOUSE_TY", ""))
    m = re.match(r"\s*([0-9]+\.?[0-9]*)", ty)
    if m:
        try:
            area = float(m.group(1))
            if area > 0:
                return area
        except ValueError:
            pass
    # 혹시 전용면적 필드가 별도로 오는 데이터셋 대비 폴백
    for key in ("EXCLUSE_AR", "EXCLU_AR"):
        try:
            area = float(str(model.get(key, "")).replace(",", ""))
            if area > 0:
                return area
        except (TypeError, ValueError):
            continue
    return None


def _offer_amount(model: dict) -> float | None:
    """분양 최고금액(만원). APT Mdl은 LTTOT_TOP_AMOUNT."""
    for key in ("LTTOT_TOP_AMOUNT", "SUPLY_AMOUNT"):
        try:
            amount = float(str(model.get(key, "")).replace(",", ""))
            if amount > 0:
                return amount
        except (TypeError, ValueError):
            continue
    return None


def _offer_unit_price(models: list[dict]) -> tuple[float | None, float, float]:
    """주택형별 공급정보 → 대표 분양 평단가(만원/㎡, 전용기준)와 전용면적 min/max."""
    units, areas = [], []
    for m in models:
        amount = _offer_amount(m)
        area = _exclusive_area(m)
        if amount and area:
            units.append(amount / area)
            areas.append(area)
    if not units:
        return None, 0.0, 0.0
    return round(median(units), 1), min(areas), max(areas)


def _market_unit_price(trades: list[dict], area_min: float, area_max: float,
                       tolerance: float, umd_keywords: list[str] | None) -> tuple[float | None, int]:
    """비교 대상 실거래의 평단가 중앙값과 표본 수.

    분양 전용면적 범위 ±tolerance 안에 드는 거래만, (동탄 등) 동 키워드가 있으면 해당 동만.
    """
    lo = area_min * (1 - tolerance)
    hi = area_max * (1 + tolerance)
    sample = []
    for t in trades:
        if not (lo <= t["area"] <= hi):
            continue
        if umd_keywords and not any(k in t["umd"] for k in umd_keywords):
            continue
        sample.append(t["unit"])
    if not sample:
        return None, 0
    return round(median(sample), 1), len(sample)


def _safety_margin_to_score(margin_pct: float) -> int:
    """안전마진(%) → 0~100 기본 점수 (구간 매핑)."""
    table = [
        (40, 100), (30, 92), (20, 82), (10, 70),
        (0, 55), (-10, 38), (-20, 22), (-1e9, 10),
    ]
    for threshold, score in table:
        if margin_pct >= threshold:
            return score
    return 10


def evaluate(notice: dict, models: list[dict], trades: list[dict],
             scoring_cfg: dict, region: dict) -> dict:
    """공고 1건에 대한 점수 산출 결과 dict 반환."""
    offer_unit, a_min, a_max = _offer_unit_price(models)
    market_unit, n = _market_unit_price(
        trades, a_min, a_max,
        scoring_cfg["area_tolerance"], region.get("umd_keywords"),
    )

    result = {
        "offer_unit": offer_unit,       # 분양 평단가(만원/㎡)
        "market_unit": market_unit,     # 시세 평단가(만원/㎡)
        "n_trades": n,
        "margin_pct": None,
        "score": None,
        "confidence": "낮음",
        "reason": "",
    }

    if offer_unit is None:
        result["reason"] = "분양가 정보 없음(공고 초기일 수 있음)"
        return result
    if market_unit is None or n < scoring_cfg["min_trades"]:
        result["reason"] = f"비교할 주변 실거래 부족(표본 {n}건)"
        result["confidence"] = "데이터부족"
        return result

    margin = (market_unit - offer_unit) / offer_unit * 100
    score = _safety_margin_to_score(margin)

    # 보정: 세대수 많으면 환금성 가점, 표본 충분하면 신뢰 가점
    try:
        households = int(str(notice.get("TOT_SUPLY_HSHLDCO", "0")).replace(",", ""))
    except ValueError:
        households = 0
    if households >= 700:
        score = min(100, score + 5)
    elif households >= 300:
        score = min(100, score + 2)

    if n >= 15:
        result["confidence"] = "높음"
    elif n >= scoring_cfg["min_trades"]:
        result["confidence"] = "보통"

    result["margin_pct"] = round(margin, 1)
    result["score"] = score
    result["reason"] = (
        f"분양 {offer_unit:.0f} vs 시세 {market_unit:.0f} 만원/㎡ "
        f"(안전마진 {margin:+.1f}%, 표본 {n}건)"
    )
    return result
