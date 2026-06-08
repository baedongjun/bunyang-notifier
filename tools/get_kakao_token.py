"""카카오 refresh_token 최초 1회 발급 도우미 (로컬 PC에서 실행).

사용법
  1) 카카오 디벨로퍼스에서 앱 생성 → REST API 키 확인
     → 카카오 로그인 활성화 → Redirect URI 등록(아래 REDIRECT_URI와 동일하게)
     → 동의항목에서 '카카오톡 메시지 전송(talk_message)' 사용 설정
  2) .env 에 KAKAO_REST_API_KEY (필요시 KAKAO_CLIENT_SECRET) 채우고 실행:
        python tools/get_kakao_token.py
  3) 출력된 URL을 브라우저로 열어 로그인/동의 → 리다이렉트된 주소의 code= 값 복사
  4) 터미널에 code 붙여넣기 → refresh_token 출력됨 → .env / GitHub Secret 에 저장
"""
import os
import sys
from pathlib import Path

import requests

# app.config 의 .env 로더를 재사용 (KAKAO_REST_API_KEY 등을 환경변수로 로드)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import _load_dotenv  # noqa: E402

_load_dotenv()

REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")
CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "")
# 카카오 디벨로퍼스에 등록한 Redirect URI 와 반드시 동일해야 함
REDIRECT_URI = os.environ.get("KAKAO_REDIRECT_URI", "https://localhost:5000/oauth")


def main():
    if not REST_API_KEY:
        sys.exit(".env 에 KAKAO_REST_API_KEY 를 먼저 채워주세요.")

    auth_url = (
        "https://kauth.kakao.com/oauth/authorize"
        f"?client_id={REST_API_KEY}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code&scope=talk_message"
    )
    print("\n[1] 아래 URL을 브라우저로 여세요 (로그인 + '카카오톡 메시지 전송' 동의):\n")
    print(auth_url)
    print("\n[2] 동의 후 주소창이 "
          f"{REDIRECT_URI}?code=XXXX 로 바뀝니다. (페이지는 안 열려도 정상)")
    code = input("\n[3] 주소창의 code= 뒤 값을 붙여넣으세요: ").strip()

    data = {
        "grant_type": "authorization_code",
        "client_id": REST_API_KEY,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    if CLIENT_SECRET:
        data["client_secret"] = CLIENT_SECRET

    r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=10)
    r.raise_for_status()
    body = r.json()

    print("\n===== 발급 완료 =====")
    print("ACCESS_TOKEN  :", body["access_token"][:20], "... (6시간 유효, 저장 불필요)")
    print("REFRESH_TOKEN :", body["refresh_token"])
    print("=====================")
    print("\n위 REFRESH_TOKEN 을 GitHub Secret 'KAKAO_REFRESH_TOKEN' 에 저장하세요.")


if __name__ == "__main__":
    main()
