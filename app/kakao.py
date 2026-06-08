"""카카오톡 '나에게 보내기' 발송 + access_token 갱신.

- refresh_token만 보관(매 실행 access_token 재발급)
- refresh_token rotation 시 새 값을 호출측에 반환
"""
from __future__ import annotations

import json

import requests

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TIMEOUT = 10


def refresh_access_token(rest_key: str, refresh_token: str,
                         client_secret: str = "") -> tuple[str, str | None]:
    """(access_token, 새 refresh_token 또는 None) 반환."""
    data = {
        "grant_type": "refresh_token",
        "client_id": rest_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        data["client_secret"] = client_secret
    r = requests.post(TOKEN_URL, data=data, timeout=TIMEOUT)
    r.raise_for_status()
    body = r.json()
    return body["access_token"], body.get("refresh_token")


def _post(access_token: str, template: dict) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    data = {"template_object": json.dumps(template, ensure_ascii=False)}
    r = requests.post(SEND_URL, headers=headers, data=data, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()  # {"result_code": 0}


def send_text(access_token: str, text: str, link_url: str = "",
              button_title: str = "") -> dict:
    """text 템플릿으로 나에게 보내기. text는 최대 200자.

    button_title을 비우면 버튼을 만들지 않습니다 → PC 카카오톡에서
    '모바일에서 확인해주세요' 문구가 뜨지 않음(링크는 본문에 텍스트로 넣을 것).
    """
    template = {
        "object_type": "text",
        "text": text[:200],
        # 버튼이 없을 땐 빈 link 객체 → 메시지에 별도 액션이 붙지 않음
        "link": {"web_url": link_url, "mobile_web_url": link_url} if link_url else {},
    }
    if button_title:
        template["button_title"] = button_title
    return _post(access_token, template)
