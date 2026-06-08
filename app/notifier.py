"""메인 오케스트레이션.

흐름: 민간분양 공고 조회 → 관심지역 매칭 → (신규만) 분양가·주변시세 비교 →
      점수 산출 → 카카오톡 '나에게 보내기' → 알림 기록 저장.

환경변수
  DRY_RUN=1  : 카카오 발송 없이 콘솔 출력만 (최초 테스트용)
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from . import applyhome, kakao, realprice, scoring, state
from .config import Config


def _match_region(notice: dict, regions: list[dict]) -> dict | None:
    addr = (notice.get("HSSPLY_ADRES") or "") + " " + (notice.get("HOUSE_NM") or "")
    for region in regions:
        if any(kw in addr for kw in region["address_keywords"]):
            return region
    return None


def _build_message(notice: dict, region: dict, ev: dict) -> str:
    name = notice.get("HOUSE_NM", "(공고명 미상)")
    households = notice.get("TOT_SUPLY_HSHLDCO", "-")
    rcept = f"{notice.get('RCEPT_BGNDE', '?')}~{notice.get('RCEPT_ENDDE', '?')}"

    if ev["score"] is not None:
        head = f"🎯 {ev['score']}/100 ({ev['confidence']})"
    else:
        head = f"🎯 점수 미산정 ({ev['reason']})"

    lines = [
        f"🏠[민간분양] {name}",
        f"📍{region['name']}",
        head,
        f"💰{ev['reason']}",
        f"🗓접수 {rcept} | 🏢{households}세대",
    ]
    return "\n".join(lines)


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

        msg = _build_message(notice, region, ev)
        link = notice.get("PBLANC_URL") or "https://www.applyhome.co.kr"
        print("    " + msg.replace("\n", "\n    "))

        if dry:
            print("    (DRY_RUN: 발송 생략)")
        else:
            if access_token is None:
                access_token, new_refresh = kakao.refresh_access_token(
                    cfg.kakao_rest_key, cfg.kakao_refresh_token,
                    cfg.kakao_client_secret)
            kakao.send_text(access_token, msg, link_url=link)
            print("    ✅ 카카오톡 발송 완료")

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
