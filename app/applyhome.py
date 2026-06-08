"""청약홈 분양정보 조회 (한국부동산원, 공공데이터포털).

- getAPTLttotPblancDetail : APT 분양 공고 목록
- getAPTLttotPblancMdl    : 주택형별 분양가(공급금액)
"""
from __future__ import annotations

import requests

BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
DETAIL_URL = f"{BASE}/getAPTLttotPblancDetail"
MDL_URL = f"{BASE}/getAPTLttotPblancMdl"

TIMEOUT = 15


def _get(url: str, service_key: str, conds: dict, per_page: int = 100) -> list[dict]:
    """odcloud 공통 GET — data 배열을 페이지네이션으로 모두 수집."""
    rows: list[dict] = []
    page = 1
    while True:
        params = {"serviceKey": service_key, "page": page, "perPage": per_page,
                  "returnType": "JSON"}
        params.update(conds)
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        body = r.json()
        if "data" not in body:
            raise RuntimeError(f"예상치 못한 응답: {str(body)[:300]}")
        data = body["data"]
        rows.extend(data)
        total = body.get("totalCount", len(rows))
        if page * per_page >= total or not data:
            break
        page += 1
    return rows


def fetch_private_apt_notices(service_key: str, house_secd: str,
                              house_dtl_secd: str, since_date: str) -> list[dict]:
    """민간분양(민영) APT 공고 목록.

    since_date: 'YYYY-MM-DD' — 모집공고일이 이 날짜 이후인 공고만.
    """
    conds = {
        "cond[HOUSE_SECD::EQ]": house_secd,
        "cond[HOUSE_DTL_SECD::EQ]": house_dtl_secd,
        "cond[RCRIT_PBLANC_DE::GTE]": since_date,
    }
    return _get(DETAIL_URL, service_key, conds)


def fetch_supply_models(service_key: str, house_manage_no: str,
                        pblanc_no: str) -> list[dict]:
    """주택형별 공급정보(분양가 포함). SUPLY_AMOUNT(만원), EXCLUSE_AR(전용㎡)."""
    conds = {
        "cond[HOUSE_MANAGE_NO::EQ]": house_manage_no,
        "cond[PBLANC_NO::EQ]": pblanc_no,
    }
    try:
        return _get(MDL_URL, service_key, conds)
    except Exception:
        # 분양가 조회 실패해도 공고 알림 자체는 진행
        return []
