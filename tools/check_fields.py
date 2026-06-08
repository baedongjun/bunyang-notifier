"""민영/국민 구분 코드(HOUSE_DTL_SECD) 실제 값 확인용 일회성 스크립트.

청약홈 데이터셋은 코드값이 가끔 바뀌므로, 인증키 발급 후 한 번 실행해
config.yaml 의 house_dtl_secd 값이 맞는지 확인하세요.

사용: .env 에 DATA_GO_KR_KEY 채운 후  python tools/check_fields.py
"""
import os
import sys
from pathlib import Path

import requests

# app.config 의 .env 로더 재사용
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import _load_dotenv  # noqa: E402

_load_dotenv()

URL = ("https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/"
       "getAPTLttotPblancDetail")


def main():
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        raise SystemExit("환경변수 DATA_GO_KR_KEY 를 설정하세요.")

    r = requests.get(URL, params={"serviceKey": key, "page": 1, "perPage": 20,
                                  "returnType": "JSON"}, timeout=15)
    r.raise_for_status()
    data = r.json().get("data", [])
    print(f"표본 {len(data)}건의 주택구분/상세구분 분포:\n")
    seen = {}
    for d in data:
        k = (d.get("HOUSE_SECD"), d.get("HOUSE_SECD_NM"),
             d.get("HOUSE_DTL_SECD"), d.get("HOUSE_DTL_SECD_NM"))
        seen[k] = seen.get(k, 0) + 1
    for (hs, hsn, hd, hdn), cnt in sorted(seen.items()):
        print(f"  HOUSE_SECD={hs}({hsn})  HOUSE_DTL_SECD={hd}({hdn})  → {cnt}건")
    print("\n→ '민영주택' 으로 표시된 행의 HOUSE_DTL_SECD 값을 config.yaml 에 넣으세요.")


if __name__ == "__main__":
    main()
