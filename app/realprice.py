"""국토교통부 아파트 매매 실거래가 조회 (상세 버전, XML).

엔드포인트: apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

import requests

URL = ("http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/"
       "getRTMSDataSvcAptTradeDev")
TIMEOUT = 15


def _recent_yyyymm(months: int) -> list[str]:
    """오늘 기준 최근 N개월의 YYYYMM 목록(현재월 포함)."""
    today = date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(months):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return out


def _fetch_month(service_key: str, lawd_cd: str, deal_ymd: str) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        params = {"serviceKey": service_key, "LAWD_CD": lawd_cd,
                  "DEAL_YMD": deal_ymd, "pageNo": page, "numOfRows": 100}
        r = requests.get(URL, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        root = ET.fromstring(r.text)

        code = root.findtext(".//resultCode")
        if code not in (None, "00", "000"):
            msg = root.findtext(".//resultMsg") or r.text[:200]
            raise RuntimeError(f"실거래가 API 오류({code}): {msg}")

        items = root.findall(".//item")
        for it in items:
            def g(tag: str) -> str:
                return (it.findtext(tag) or "").strip()
            try:
                amount = int(g("dealAmount").replace(",", "") or 0)
                area = float(g("excluUseAr") or 0)
            except ValueError:
                continue
            if amount <= 0 or area <= 0:
                continue
            rows.append({
                "apt": g("aptNm"),
                "umd": g("umdNm"),
                "area": area,                     # 전용면적(㎡)
                "amount": amount,                 # 거래금액(만원)
                "unit": round(amount / area, 1),  # 평단가(만원/㎡)
                "floor": g("floor"),
                "build_year": g("buildYear"),
                "date": f"{g('dealYear')}-{int(g('dealMonth') or 0):02d}-"
                        f"{int(g('dealDay') or 0):02d}",
            })
        total = int(root.findtext(".//totalCount") or 0)
        if page * 100 >= total or not items:
            break
        page += 1
    return rows


def fetch_trades(service_key: str, lawd_cd: str, months: int) -> list[dict]:
    """최근 N개월 시군구 전체 실거래 목록."""
    all_rows: list[dict] = []
    for ymd in _recent_yyyymm(months):
        try:
            all_rows.extend(_fetch_month(service_key, lawd_cd, ymd))
        except Exception as e:
            print(f"  [경고] 실거래가 {lawd_cd}/{ymd} 조회 실패: {e}")
    return all_rows
