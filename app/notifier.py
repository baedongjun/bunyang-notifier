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


def _type_lines(models: list[dict]) -> list[str]:
    """주택형별: 전용면적·세대수·분양가·평단가 한 줄씩 (전용면적 오름차순)."""
    rows = []
    for m in models:
        area = scoring._exclusive_area(m)
        amount = scoring._offer_amount(m)          # 만원
        if not (area and amount):
            continue
        suffix = re.sub(r"^[0-9.]+", "", str(m.get("HOUSE_TY", ""))).strip()  # 'A','B'...
        try:
            hh = int(str(m.get("SUPLY_HSHLDCO", "0")).replace(",", ""))
        except ValueError:
            hh = 0
        rows.append((area, suffix, hh, amount))
    rows.sort(key=lambda r: (r[0], r[1]))

    lines = []
    for area, suffix, hh, amount in rows[:MAX_TYPE_LINES]:
        unit = round(amount / area)
        lines.append(
            f"·{area:.0f}㎡{suffix} {hh}세대 {amount/10000:.1f}억({unit}만/㎡)"
        )
    if len(rows) > MAX_TYPE_LINES:
        lines.append(f"…외 {len(rows) - MAX_TYPE_LINES}개 타입(공고문 참고)")
    return lines


def _build_messages(notice: dict, region: dict, ev: dict,
                    models: list[dict]) -> list[str]:
    """연속 발송할 카카오 메시지 목록(각 200자 이내). 1통=요약, 2통+=타입별 분양가."""
    name = notice.get("HOUSE_NM", "(공고명 미상)")
    if len(name) > 30:
        name = name[:29] + "…"
    households = notice.get("TOT_SUPLY_HSHLDCO", "-")
    rcept = f"{notice.get('RCEPT_BGNDE', '?')}~{notice.get('RCEPT_ENDDE', '?')}"

    if ev["score"] is not None:
        head = f"🎯 {ev['score']}/100 ({ev['confidence']})"
    else:
        head = f"🎯 점수 미산정 ({ev['reason']})"

    # --- 1통: 요약 ---
    summary = [
        f"🏠[민간분양] {name}",
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
    print(f"[1] 민간분양 공고 조회 (모집공고일 >= {since}) ...")
    notices = applyhome.fetch_private_apt_notices(
        cfg.applyhome_key,
        cfg.filters["house_secd"],
        cfg.filters["house_dtl_secd"],
        since,
    )
    print(f"    전체 민간분양 APT 공고: {len(notices)}건")

    seen = state.load_seen(cfg.state_path)
    trade_cache: dict[str, list[dict]] = {}
    new_refresh: str | None = None
    access_token: str | None = None
    sent = 0

    for notice in notices:
        region = _match_region(notice, cfg.regions)
        if region is None:
            continue

        pblanc_no = str(notice.get("PBLANC_NO") or notice.get("HOUSE_MANAGE_NO"))
        if pblanc_no in seen:
            continue

        print(f"[*] 관심지역 신규 공고: {notice.get('HOUSE_NM')} ({region['name']})")

        # 분양가(주택형별)
        models = applyhome.fetch_supply_models(
            cfg.applyhome_key,
            str(notice.get("HOUSE_MANAGE_NO")),
            pblanc_no,
        )
        # 주변 실거래가 (지역별 1회만 조회 후 캐시)
        lawd = region["lawd_cd"]
        if lawd not in trade_cache:
            trade_cache[lawd] = realprice.fetch_trades(
                cfg.realprice_key, lawd, cfg.scoring["trade_months"])
        trades = trade_cache[lawd]

        ev = scoring.evaluate(notice, models, trades, cfg.scoring, region)

        if ev["score"] is not None and ev["score"] < cfg.scoring["notify_min_score"]:
            print(f"    점수 {ev['score']} < 알림 기준 → 스킵")
            seen.add(pblanc_no)
            continue

        messages = _build_messages(notice, region, ev, models)
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
