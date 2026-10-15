# KRX 종가 텔레그램 알림

매 KRX 거래일 15:35(한국시간) 이후 등록된 종목의 당일 종가와 전 거래일 대비 등락률을 키움 REST API로 확인해 텔레그램으로 보냅니다.

- KODEX 미국머니마켓액티브 (`0048J0`)
- TIGER 미국초단기(3개월이하)국채 (`0046A0`)
- TIGER 미국달러단기채권액티브 (`329750`)

조회에 실패한 종목도 메시지에서 빠뜨리지 않고 `확인불가`로 표시합니다. 한국거래소 휴장일에는 전송하지 않습니다.

## 텔레그램에서 종목 관리

`주식종가 알리미`와의 개인 채팅에 아래처럼 보냅니다.

```text
추가 005930 삼성전자
삭제 005930
목록
도움말
```

- 추가할 때는 **종목코드 6자리와 종목명**을 함께 입력합니다.
- 같은 코드를 다시 추가하면 중복 등록되지 않습니다.
- 최대 10개까지 등록할 수 있습니다. 키움 조회가 고정 IP 중계를 거쳐 순차 실행되므로 종목이 많을수록 알림이 늦어질 수 있습니다.
- 명령은 GitHub Actions가 주기적으로 확인하므로 답장이 오기까지 보통 몇 분 걸릴 수 있습니다.
- 변경 사항은 `watchlist.json`에 저장되어 다음 종가 알림부터 사용됩니다.
- 등록된 개인 채팅에서 보낸 명령만 처리하고, 다른 사용자의 메시지는 무시합니다.

## 무료 구성과 동작 방식

PC를 계속 켜 두지 않아도 됩니다.

1. 기존 cron-job.org 작업이 15:35 KST에 GitHub Actions의 `repository_dispatch`를 호출합니다.
2. GitHub 무료 호스팅 실행기가 거래일 여부를 판단합니다.
3. 텔레그램 종목 관리 작업은 GitHub에서 5분마다 실행되며 PC를 켜 둘 필요가 없습니다.
4. 키움은 허용된 IP에서만 호출할 수 있으므로, GitHub가 cron-job.org에 몇 분짜리 임시 조회 작업 하나를 만듭니다.
5. 그 작업 하나를 차례로 갱신해 같은 실행 노드에서 키움 토큰과 `ka10086` 일별주가를 조회하고 당일·전 거래일 종가를 비교합니다. 키움의 토큰 발급 IP와 조회 IP가 같아야 하는 제약을 지키기 위한 방식입니다.
6. GitHub가 결과의 날짜·가격·등락률을 검증한 뒤 텔레그램을 보내고 임시 작업과 실행 기록을 삭제합니다.

cron-job.org가 분 단위로 실행되므로 알림은 보통 15:35보다 몇 분 늦게 도착합니다. 데이터는 당일 장 마감 후 키움이 제공한 종가입니다.

## 1. 키움 허용 IP 등록

키움 REST API 포털의 허용 IP 목록에 다음 cron-job.org 공식 실행 노드 5개를 등록합니다.

```text
116.203.134.67
116.203.129.16
23.88.105.37
128.140.8.200
91.99.23.109
```

프로그램은 실행 직전에 cron-job.org의 현재 노드 목록을 다시 확인합니다. 여기에 없는 새 IP가 발견되면 App Key와 Secret을 보내지 않고, 모든 종목을 `확인불가`로 알립니다. cron-job.org의 노드가 변경된 경우 새 IP를 키움에 먼저 등록한 다음 코드의 허용 목록도 갱신해야 합니다.

## 2. 기존 15:35 호출 작업 유지

기존 cron-job.org 작업은 시간대를 `Asia/Seoul`, 실행 시각을 평일 `15:35`로 유지하고 아래 GitHub API를 POST 호출합니다.

```text
POST https://api.github.com/repos/hjhj202608-cell/stock_price/dispatches
Accept: application/vnd.github+json
Authorization: Bearer <기존 GitHub fine-grained token>
Content-Type: application/json

{"event_type":"krx_close_1535"}
```

실제 휴장일 판정은 GitHub 안에서 다시 하므로 평일 중 휴장일에는 알림을 보내지 않습니다.

## 3. cron-job.org API Key 만들기

cron-job.org 콘솔의 **Settings → API keys**에서 API Key를 하나 만듭니다. 이 키는 GitHub의 유동 IP에서 사용되므로 cron-job.org 쪽 IP 제한은 설정하지 않습니다. 대신 아래 GitHub Secret에만 보관합니다.

기존의 15:35 GitHub 호출 작업은 그대로 둡니다. 이 API Key는 그 호출용 토큰과 별개로, GitHub가 짧은 키움 조회 작업을 만들고 지우는 데만 사용됩니다.

## 4. GitHub Secrets 등록

저장소의 **Settings → Secrets and variables → Actions → New repository secret**에서 아래 5개를 등록합니다.

| 이름 | 값 |
|---|---|
| `CRONJOB_API_KEY` | cron-job.org에서 만든 API Key |
| `KIWOOM_APP_KEY` | 키움 REST API App Key |
| `KIWOOM_APP_SECRET` | 키움 REST API Secret Key |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 메시지를 받을 채팅 ID |

키 값은 코드나 채팅에 붙여 넣지 마세요. GitHub Secret 입력 화면에 직접 넣는 것이 안전합니다.

텔레그램 연결만 빠르게 확인하려면 Actions에서 `Telegram connection diagnostic`
워크플로를 수동 실행합니다. 이 진단은 메시지를 보내지 않고 봇 토큰과 대상 채팅
접근 권한만 확인합니다.

## 보안상 알아둘 점

- 장기 보관 장소는 GitHub Secrets뿐입니다.
- 실행 중 App Key와 Secret은 HTTPS로 cron-job.org의 임시 작업 설정에 전달됩니다.
- 임시 작업은 결과 수집 직후 삭제되며, 각 실행 예약은 실행되지 못해도 5분 후 만료되도록 설정됩니다.
- cron-job.org는 기존 작업을 보통 다른 노드로 옮기지 않는다고 안내하지만 이를 영구 보장하지는 않습니다. 실행 중 노드가 바뀌어 키움이 거부하면 그날 가격은 `확인불가`로 전송됩니다.
- 키움 접근 토큰은 GitHub 로그 마스킹 대상에 추가됩니다.
- GitHub 호스팅 실행기의 유동 IP를 키움 허용 목록에 대량 등록하지 않습니다.
- 워크플로 권한은 저장소 내용 읽기만 허용합니다.

## 수동 점검

GitHub 저장소의 **Actions → KRX close price Telegram alert → Run workflow**로 수동 실행할 수 있습니다. 거래일 15:35 KST 이전에는 안전하게 종료되므로, 실제 전체 점검은 거래일 장 마감 뒤 실행합니다.

로컬 테스트:

```bash
python -m pytest -q
```
