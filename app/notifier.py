"""메인 오케스트레이션.

흐름: 민간분양 공고 조회 → 관심지역 매칭 → (신규만) 분양가·주변시세 비교 →
      점수 산출 → 카카오톡 '나에게 보내기' → 알림 기록 저장.

환경변수
  DRY_RUN=1  : 카카오 발송 없이 콘솔 출력만 (최초 테스트용)
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta

from . import applyhome, kakao, realprice, scoring, shorten, state
from .config import Config

KAKAO_TEXT_LIMIT = 200
MAX_TYPE_LINES = 12      # 타입이 너무 많으면 상위 N개만 표시


def _match_region(notice: dict, regions: list[dict]) -> dict | None:
    addr = (notice.get("HSSPLY_ADRES") or "") + " " + (notice.get("HOUSE_NM") or "")
    for region in regions:
        if any(kw in addr for kw in region["address_keywords"]):
            return region
    return None


def _int(v) -> int:
    try:
        return int(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0


def _type_lines(models: list[dict]) -> list[str]:
    """주택형별: 전용면적·총세대(일반+특공)·분양가·평단가 한 줄씩 (전용면적 오름차순).

    SUPLY_HSHLDCO = 일반공급, SPSPLY_HSHLDCO = 특별공급 → 총세대 = 둘의 합.
    """
    rows = []
    for m in models:
        area = scoring._exclusive_area(m)
        amount = scoring._offer_amount(m)          # 만원
        if not (area and amount):
            continue
        suffix = re.sub(r"^[0-9.]+", "", str(m.get("HOUSE_TY", ""))).strip()  # 'A','B'...
        gen = _int(m.get("SUPLY_HSHLDCO"))         # 일반공급
        special = _int(m.get("SPSPLY_HSHLDCO"))    # 특별공급
        rows.append((area, suffix, gen, special, amount))
    rows.sort(key=lambda r: (r[0], r[1]))

    lines = []
    for area, suffix, gen, special, amount in rows[:MAX_TYPE_LINES]:
        unit = round(amount / area)
        total = gen + special
        lines.append(
            f"·{area:.0f}㎡{suffix} {total}세대(일반{gen}/특공{special}) "
            f"{amount/10000:.1f}억({unit}만/㎡)"
        )
    if len(rows) > MAX_TYPE_LINES:
        lines.append(f"…외 {len(rows) - MAX_TYPE_LINES}개 타입(공고문 참고)")
    return lines


_RCEPT_FIELDS = [
    ("RCEPT_BGNDE", "RCEPT_ENDDE"),                     # 일반 분양(1순위)
    ("SUBSCRPT_RCEPT_BGNDE", "SUBSCRPT_RCEPT_ENDDE"),   # 무순위/재공급
    ("GNRL_RCEPT_BGNDE", "GNRL_RCEPT_ENDDE"),
    ("CNTRCT_CNCLS_BGNDE", "CNTRCT_CNCLS_ENDDE"),
]


def _parse_date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _receipt_dates(notice: dict) -> tuple[date | None, date | None]:
    """청약접수 (시작일, 종료일)을 date로. 공고 종류마다 필드명이 달라 순서 탐색."""
    for b, e in _RCEPT_FIELDS:
        if notice.get(b) or notice.get(e):
            return _parse_date(notice.get(b)), _parse_date(notice.get(e))
    return None, None


def _rcept(notice: dict) -> str:
    """접수기간 + 긴급도(D-day) 문자열."""
    bgn, end = _receipt_dates(notice)
    if not (bgn or end):
        return "공고문 참고"
    span = f"{bgn or '?'}~{end or '?'}" if bgn != end else f"{bgn}"
    today = date.today()
    tag = ""
    if end and end < today:
        tag = " (마감)"
    elif bgn and bgn > today:
        tag = f" (D-{(bgn - today).days})"
    elif (bgn and bgn <= today) and (end and end >= today):
        tag = " 🔴오늘마감" if end == today else " 🔴접수중"
    return span + tag


def _build_messages(notice: dict, region: dict, ev: dict,
                    models: list[dict], kind: str = "민간분양") -> list[str]:
    """연속 발송할 카카오 메시지 목록(각 200자 이내). 1통=요약, 2통+=타입별 분양가."""
    name = notice.get("HOUSE_NM", "(공고명 미상)")
    if len(name) > 30:
        name = name[:29] + "…"
    households = notice.get("TOT_SUPLY_HSHLDCO", "-")
    rcept = _rcept(notice)

    if ev["score"] is not None:
        head = f"🎯 {ev['score']}/100 ({ev['confidence']})"
    else:
        head = f"🎯 점수 미산정 ({ev['reason']})"

    # --- 1통: 요약 ---
    summary = [
        f"🏠[{kind}] {name}",
        f"📍{region['name']} · 총 {households}세대",
        head,
        f"💰{ev['reason']}",
        f"🗓접수 {rcept}",
    ]
    hmpg = (notice.get("HMPG_ADRES") or "").strip()
    if hmpg.startswith("http"):
        disp = hmpg if (hmpg.isascii() and len(hmpg) <= 30) else shorten.shorten(hmpg)
        summary.append(f"🔗분양홈 {disp}")
    pblanc_url = (notice.get("PBLANC_URL") or "").strip()
    if pblanc_url.startswith("http"):
        summary.append(f"📄공고문 {shorten.shorten(pblanc_url)}")

    messages = _pack("\n".join(summary), None)

    # --- 2통+: 타입별 분양가 ---
    tlines = _type_lines(models)
    if tlines:
        header = f"🏷{name} 타입별 분양가"
        messages += _pack("\n".join(tlines), header)
    return messages


def _pack(body: str, header: str | None) -> list[str]:
    """본문을 200자 이내 메시지들로 분할. header가 있으면 각 조각 앞에 붙임."""
    prefix = (header + "\n") if header else ""
    out, cur = [], []
    cur_len = len(prefix)
    for line in body.split("\n"):
        add = len(line) + (1 if cur else 0)
        if cur and cur_len + add > KAKAO_TEXT_LIMIT:
            out.append(prefix + "\n".join(cur))
            cur, cur_len = [line], len(prefix) + len(line)
        else:
            cur.append(line)
            cur_len += add
    if cur:
        out.append(prefix + "\n".join(cur))
    return out


def run() -> None:
    cfg = Config()
    dry = os.environ.get("DRY_RUN") == "1"

    since = (date.today() - timedelta(days=cfg.filters["recent_days"])).isoformat()
    f = cfg.filters

    # (공고 dict, source, 종류라벨) 통합 목록
    records: list[tuple[dict, str, str]] = []

    if f.get("include_private", True):
        print(f"[1] 민간분양 공고 조회 (모집공고일 >= {since}) ...")
        priv = applyhome.fetch_private_apt_notices(
            cfg.applyhome_key, f["house_secd"], f["house_dtl_secd"], since)
        print(f"    민간분양 APT: {len(priv)}건")
        records += [(n, "apt", "민간분양") for n in priv]

    if f.get("include_unranked", True) or f.get("include_resupply", True):
        print(f"[2] 무순위/재공급 공고 조회 (모집공고일 >= {since}) ...")
        remndr = applyhome.fetch_remndr_notices(cfg.applyhome_key, since)
        # HOUSE_SECD: 04=무순위, 06=불법행위 재공급
        kept = 0
        for n in remndr:
            secd = str(n.get("HOUSE_SECD"))
            if secd == "04" and f.get("include_unranked", True):
                records.append((n, "remndr", n.get("HOUSE_SECD_NM") or "무순위"))
                kept += 1
            elif secd == "06" and f.get("include_resupply", True):
                records.append((n, "remndr", n.get("HOUSE_SECD_NM") or "불법행위 재공급"))
                kept += 1
        print(f"    무순위/재공급: {kept}건")

    print(f"    합계 {len(records)}건 대상으로 관심지역 매칭 시작")

    seen = state.load_seen(cfg.state_path)
    trade_cache: dict[str, list[dict]] = {}
    new_refresh: str | None = None
    access_token: str | None = None
    sent = 0

    for notice, source, kind in records:
        region = _match_region(notice, cfg.regions)
        if region is None:
            continue

        # 공고번호+종류로 중복키 (같은 단지의 분양/무순위가 따로 알림되도록 source 포함)
        pblanc_no = f"{source}:{notice.get('PBLANC_NO') or notice.get('HOUSE_MANAGE_NO')}"
        if pblanc_no in seen:
            continue

        # 접수 마감 지난 공고는 알림 제외 (청약 불가)
        _, end = _receipt_dates(notice)
        if cfg.filters.get("skip_closed", True) and end and end < date.today():
            seen.add(pblanc_no)        # 다시 평가하지 않도록 기록만
            continue

        print(f"[*] 신규 [{kind}] {notice.get('HOUSE_NM')} ({region['name']})")

        # 분양가(주택형별)
        models = applyhome.fetch_supply_models(
            cfg.applyhome_key,
            str(notice.get("HOUSE_MANAGE_NO")),
            str(notice.get("PBLANC_NO") or notice.get("HOUSE_MANAGE_NO")),
            source=source,
        )
        # 주변 실거래가 (지역별 1회만 조회 후 캐시). lawd_cd는 문자열 또는 리스트 허용.
        codes = region["lawd_cd"]
        if isinstance(codes, str):
            codes = [codes]
        cache_key = ",".join(codes)
        if cache_key not in trade_cache:
            merged: list[dict] = []
            for c in codes:
                merged += realprice.fetch_trades(
                    cfg.realprice_key, c, cfg.scoring["trade_months"])
            trade_cache[cache_key] = merged
        trades = trade_cache[cache_key]

        ev = scoring.evaluate(notice, models, trades, cfg.scoring, region)

        if ev["score"] is not None and ev["score"] < cfg.scoring["notify_min_score"]:
            print(f"    점수 {ev['score']} < 알림 기준 → 스킵")
            seen.add(pblanc_no)
            continue

        messages = _build_messages(notice, region, ev, models, kind=kind)
        for i, m in enumerate(messages, 1):
            print(f"    --- 메시지 {i}/{len(messages)} ({len(m)}자) ---")
            print("    " + m.replace("\n", "\n    "))

        if dry:
            print("    (DRY_RUN: 발송 생략)")
        else:
            if access_token is None:
                access_token, new_refresh = kakao.refresh_access_token(
                    cfg.kakao_rest_key, cfg.kakao_refresh_token,
                    cfg.kakao_client_secret)
            for m in messages:                       # 버튼 없음(본문 링크) → PC 호환
                kakao.send_text(access_token, m)
            print(f"    ✅ 카카오톡 {len(messages)}통 발송 완료")

        seen.add(pblanc_no)
        sent += 1

    state.save_seen(cfg.state_path, seen)
    print(f"[완료] 신규 알림 {sent}건. 누적 기록 {len(seen)}건.")

    # refresh_token rotation → GitHub Actions에서 Secret 갱신용 출력
    if new_refresh:
        gh_out = os.environ.get("GITHUB_OUTPUT")
        print(f"::add-mask::{new_refresh}")
        if gh_out:
            with open(gh_out, "a", encoding="utf-8") as f:
                f.write(f"new_refresh_token={new_refresh}\n")


if __name__ == "__main__":
    run()
