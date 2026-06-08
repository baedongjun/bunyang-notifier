"""설정 로딩 — config.yaml + 환경변수(API 키, 카카오 토큰)."""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """추가 의존성 없이 .env 파일을 환경변수로 로드 (로컬 실행 편의)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and val and key not in os.environ:
            os.environ[key] = val


class Config:
    def __init__(self, path: Path | None = None):
        _load_dotenv()
        path = path or (ROOT / "config.yaml")
        with open(path, "r", encoding="utf-8") as f:
            self._raw = yaml.safe_load(f)

        # --- config.yaml ---
        self.regions: list[dict] = self._raw["regions"]
        self.filters: dict = self._raw["filters"]
        self.scoring: dict = self._raw["scoring"]

        # --- 환경변수(.env 또는 GitHub Secrets) ---
        # 공공데이터포털 인증키 (청약홈/실거래가 공용 — 보통 같은 계정의 키 하나로 둘 다 신청)
        self.applyhome_key: str = _env("DATA_GO_KR_KEY")
        self.realprice_key: str = os.environ.get("REALPRICE_KEY") or self.applyhome_key

        # 카카오
        self.kakao_rest_key: str = _env("KAKAO_REST_API_KEY")
        self.kakao_client_secret: str = os.environ.get("KAKAO_CLIENT_SECRET", "")
        self.kakao_refresh_token: str = _env("KAKAO_REFRESH_TOKEN")

        # 중복 알림 방지용 상태 파일
        self.state_path: Path = ROOT / "state" / "seen.json"


def _env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"환경변수 {name} 가 설정되지 않았습니다. "
            f"로컬은 .env, GitHub Actions는 Repository Secrets에 등록하세요."
        )
    return val
