# 민간분양 카카오톡 알림 🏠

관심지역(기본: **용인 수지·기흥·처인, 화성 동탄**)의 **민간분양(민영주택)** 공고를 자동 수집하고,
분양가를 **주변 아파트 실거래가**와 비교해 청약 매력도를 **0~100점**으로 매겨
매일 **카카오톡(나에게 보내기)** 으로 알려줍니다. GitHub Actions에서 무료로 24시간 자동 실행됩니다.

```
청약홈 분양정보 API ─┐
                     ├─ 민간분양만 필터 → 분양가 vs 주변 실거래가 비교 → 점수화 → 카카오톡 알림
국토부 실거래가 API ─┘                          ▲ 매일 09:00(KST) GitHub Actions cron
```

---

## 점수는 어떻게 매겨지나

핵심 지표는 **안전마진(%)** = `(주변 시세 평단가 − 분양 평단가) / 분양 평단가 × 100`

| 안전마진 | 점수 | 의미 |
|---|---|---|
| +40% 이상 | 100 | 시세보다 한참 싸게 분양 → 강력 추천 |
| +20~30% | 82~92 | 시세차익 양호 |
| +10% | 70 | 무난 |
| 0% | 55 | 시세와 비슷 |
| 음수 | 38↓ | 분양가가 시세보다 비쌈 → 신중 |

- 세대수 700↑ +5점 / 300↑ +2점 (환금성 가점)
- 비교 실거래 표본 수에 따라 신뢰도(높음/보통/데이터부족) 표기
- 임계값·가중치는 [`config.yaml`](config.yaml)의 `scoring`에서 자유롭게 조정

---

## 폴더 구조

```
bunyang-notifier/
├─ config.yaml              ← 관심지역·필터·점수 설정 (여기를 주로 수정)
├─ app/
│  ├─ notifier.py           ← 메인 (python -m app.notifier)
│  ├─ applyhome.py          ← 청약홈 분양정보/분양가 조회
│  ├─ realprice.py          ← 국토부 실거래가 조회
│  ├─ scoring.py            ← 분양가 vs 시세 점수 산출
│  ├─ kakao.py              ← 카카오톡 나에게 보내기 + 토큰 갱신
│  └─ state.py              ← 중복 알림 방지 기록
├─ tools/
│  ├─ get_kakao_token.py    ← 카카오 refresh_token 최초 발급 도우미
│  └─ check_fields.py       ← 민영/국민 구분 코드 확인용
├─ .github/workflows/notify.yml  ← 매일 자동 실행
└─ state/seen.json          ← 이미 알린 공고 기록
```

---

## 설치 (한 번만)

### 1단계. 공공데이터포털 인증키 발급
1. https://www.data.go.kr 회원가입/로그인
2. 아래 **두 API 모두 [활용신청]** (보통 즉시 자동승인):
   - **한국부동산원_청약홈 분양정보 조회 서비스** (일련번호 15098547)
   - **국토교통부_아파트 매매 실거래가 상세 자료** (일련번호 15126468)
3. 마이페이지 → 인증키에서 **일반 인증키(Decoding)** 복사 → `DATA_GO_KR_KEY`
   - 두 API 키가 같으면 하나만, 다르면 실거래가 키는 `REALPRICE_KEY`에 별도 등록
   - ⚠️ 키 발급 후 **10~60분 뒤** 활성화됩니다

### 2단계. 카카오 앱 + refresh_token 발급
1. https://developers.kakao.com → 내 애플리케이션 → **애플리케이션 추가**
2. **앱 키**에서 `REST API 키` 확인
3. **카카오 로그인 → 활성화** ON, **Redirect URI**에 `https://localhost:5000/oauth` 등록
4. **카카오 로그인 → 동의항목**에서 **카카오톡 메시지 전송(talk_message)** 사용 설정
5. (선택) **보안 → Client Secret** 발급 후 사용함 설정
6. 로컬에서 토큰 발급:
   ```bash
   pip install -r requirements.txt
   # tools/get_kakao_token.py 상단의 REST_API_KEY(, CLIENT_SECRET) 채우고 실행
   python tools/get_kakao_token.py
   ```
   → 출력된 **REFRESH_TOKEN** 복사

### 3단계. 로컬 테스트 (선택, 강력 권장)
```bash
copy .env.example .env      # (Mac/Linux: cp)
# .env 에 키들 채우고 DRY_RUN=1 유지
python tools/check_fields.py   # 민영주택 코드값이 config의 house_dtl_secd(01)와 맞는지 확인
python -m app.notifier         # 발송 없이 콘솔로 결과 미리보기
```
`DRY_RUN=1`을 지우고 다시 실행하면 실제로 카카오톡이 옵니다.

### 4단계. GitHub에 올려 자동화
1. 이 폴더를 **GitHub 비공개 저장소**로 push
2. 저장소 **Settings → Secrets and variables → Actions → New repository secret** 에 등록:

   | Secret 이름 | 값 |
   |---|---|
   | `DATA_GO_KR_KEY` | 공공데이터포털 키 |
   | `REALPRICE_KEY` | (실거래가 키가 다를 때만) |
   | `KAKAO_REST_API_KEY` | 카카오 REST API 키 |
   | `KAKAO_CLIENT_SECRET` | (Client Secret 사용 시) |
   | `KAKAO_REFRESH_TOKEN` | 2단계에서 받은 refresh_token |
   | `GH_PAT` | (선택) refresh_token 자동 갱신용 PAT |

3. **Actions 탭 → bunyang-notify → Run workflow** 로 첫 수동 실행 → 카카오톡 도착 확인
4. 이후 매일 09:00(KST) 자동 실행

---

## 자주 묻는 것

- **알림이 너무 잦거나 적어요** → `config.yaml`의 `filters.recent_days`, `scoring.notify_min_score` 조정. 예: `notify_min_score: 70` 이면 70점 이상만 알림.
- **다른 지역 추가** → `config.yaml`의 `regions`에 `address_keywords` + `lawd_cd`(법정동 시군구 5자리) 추가. 코드는 https://www.code.go.kr/stdcode/regCodeL.do 에서 조회.
- **점수가 '데이터부족'으로 나와요** → 해당 시군구의 최근 실거래가 적은 경우. `scoring.trade_months`를 늘리거나 `min_trades`를 낮추세요.
- **refresh_token이 만료돼요(2개월)** → 워크플로가 매일 도는 한 자동 갱신됩니다. `GH_PAT`를 등록하면 새 토큰이 Secret에 자동 저장돼 무기한 운영 가능. 안 하면 2개월마다 2단계만 다시 하면 됩니다.
- **공공분양도 받고 싶어요** → `config.yaml`의 `filters.house_dtl_secd`를 `03`(국민주택)으로 바꾸거나, 필터를 빼도록 코드 수정.

---

## ⚠️ 주의 / 한계

- **분양가(`SUPLY_AMOUNT`)는 공고가 청약홈에 상세 등록된 뒤에야 조회**됩니다. 모집공고 직후엔 '분양가 정보 없음'으로 나올 수 있어, 다음 실행에서 점수가 채워집니다(공고는 그래도 알림).
- 실거래가는 **시군구 단위 평균 비교**이며 단지별 입지/브랜드/연식 차이는 반영하지 않습니다. 점수는 **참고용 1차 스크리닝**이며 최종 판단은 직접 확인하세요.
- 청약홈 데이터셋의 코드값(민영/국민 구분 등)은 가끔 바뀝니다. 이상하면 `tools/check_fields.py`로 재확인하세요.
- 카카오 '나에게 보내기'는 **본인 계정에만** 전송됩니다(개인용). 타인 발송은 카카오 비즈니스 채널이 필요합니다.
