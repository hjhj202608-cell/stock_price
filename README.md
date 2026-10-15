# KRX 15:30 종가 텔레그램 알림

cron-job.org가 GitHub `repository_dispatch`를 호출하면, 고정 공인 IP의 GitHub Actions self-hosted runner가 키움 REST API에서 아래 ETF의 당일 KRX 15:30 최종 1분봉 체결가를 확인해 텔레그램으로 보냅니다.

- `0048J0` KODEX 미국머니마켓액티브
- `0046A0` TIGER 미국초단기(3개월이하)국채
- `329750` TIGER 미국달러단기채권액티브

KRX 휴장일에는 전송하지 않습니다. 개장일에 키움 인증 또는 개별 종목 조회가 실패하면 해당 가격을 `확인불가`로 전송합니다.

## 중요한 네트워크 제약

키움 REST API는 등록한 IP(최대 10개)에서만 인증할 수 있습니다. 표준 GitHub-hosted runner의 IP는 고정되지 않으므로 사용할 수 없습니다. 권장 구성은 집/사무실의 고정 공인 IP 또는 고정 IP VPS에 self-hosted runner를 설치하고, GitHub에 `self-hosted`, `linux`, `x64`, `kiwoom` 라벨을 부여한 뒤 그 공인 IP를 키움에 등록하는 것입니다.

대안은 GitHub Enterprise Cloud의 static-IP larger runner지만 개인 저장소 용도에는 비용과 구성이 과합니다. 무료 표준 runner의 광범위한 IP 대역을 키움 허용 목록에 넣는 방식은 10개 제한 및 주소 변경 때문에 안정적이지 않습니다.

## GitHub Secrets

저장소 `Settings → Secrets and variables → Actions`에 다음 Repository secrets를 추가합니다. 값은 파일이나 소스에 커밋하지 않습니다.

- `KIWOOM_APP_KEY`
- `KIWOOM_APP_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## cron-job.org 설정

기존 방식대로 평일 한국시간 15:35에 아래 GitHub API를 POST 호출합니다. cron-job.org의 시간대는 `Asia/Seoul`로 설정합니다.

```text
POST https://api.github.com/repos/hjhj202608-cell/stock_price/dispatches
Accept: application/vnd.github+json
Authorization: Bearer <GitHub fine-grained token>
Content-Type: application/json

{"event_type":"krx_close_1535"}
```

워크플로는 dispatch의 event type을 제한하지 않아 기존 cron-job.org의 event type이 달라도 계속 실행됩니다.

## 중복·오작동 방지

- 실행 시각이 15:35 KST 이전이면 종료합니다.
- `exchange_calendars`의 XKRX 일정으로 개장일을 확인합니다.
- 키움 `ka10080` 1분봉에서 날짜와 시간이 정확히 당일 `15:30:00`인 행만 인정합니다.
- `concurrency`로 중복 실행을 직렬화합니다.
- GitHub Actions 권한은 `contents: read`만 부여합니다.

## 로컬 검증

```bash
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pytest -q
```

실제 키움/텔레그램 호출은 Secrets와 키움 허용 IP가 있어야 검증할 수 있습니다.
