"""긴 URL을 짧게 (카카오 text 본문 200자 제한 대응).

TinyURL 무료 API 사용(인증 불필요). 실패하면 원본 URL 그대로 반환.
"""
from __future__ import annotations

import requests

API = "https://tinyurl.com/api-create.php"
TIMEOUT = 8


def shorten(url: str) -> str:
    if not url or not url.startswith("http"):
        return url
    try:
        r = requests.get(API, params={"url": url}, timeout=TIMEOUT)
        r.raise_for_status()
        short = r.text.strip()
        return short if short.startswith("http") else url
    except Exception:
        return url  # 단축 실패 시 원본 사용
