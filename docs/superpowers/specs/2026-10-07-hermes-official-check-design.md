# 공식 사이트 주간 확인 (Hermes) 설계

작성: 2026-10-07 · 대상 저장소: `junnnn103/ConferenceTracker` (master)

## 1. 목적

사이트의 일정은 지금 두 경로로만 새로워진다. 매주 월요일 GitHub Actions가
업스트림 두 저장소(`huggingface/ai-deadlines`, `ccfddl/ccf-deadlines`)를 받아
빌드하는 것, 그리고 대화 중에 사람이 공식 사이트를 보고 손으로 넣는 것.
후자는 넣은 시점에 멈춘다.

| 데이터 | 지금 | 문제 |
|---|---|---|
| `data/manual.yaml` (HRI, DIS 2027 등) | 한 번 적음 | 다시 확인하지 않는다 |
| `data/scraped/` (CHI, UIST, ISMAR, ACM MM, WACV) | 페이지를 한 번 저장 | 매주 그 저장본만 재검증한다. 새 CFP가 안 들어온다 |
| 나머지 학회의 포스터/LBW/워크숍 | 없음 | 한 번도 읽지 않았다 |
| 추정 회차 (ICML, ICIP 2027) | 예년 월 | 업스트림이 올려줄 때까지 기다리기만 한다 |
| TBA였던 마감 (ACL 2027 commitment) | 없음 | 공식 사이트에 올라와도 업스트림 경유로만 들어온다 |

이 설계는 **정보가 부족한 학회만 골라** 공식 사이트를 매주 읽고, 검증을 통과한
값을 사이트에 바로 반영한다. 읽기는 Hermes Agent(로컬, `gpt-6-luna`)가 맡는다.

## 2. 소유자가 정한 것

| 날짜 | 결정 |
|---|---|
| 2026-10-07 | 41개를 다 읽지 않고 정보가 부족한 학회만 읽는다 |
| 2026-10-07 | 부족 기준 A–E와 재확인 주기(§4)를 그대로 쓴다 |
| 2026-10-07 | 검증을 통과한 값은 **전부 바로 반영**한다 (회차·본 논문 마감 포함) |
| 2026-10-07 | `blocked`는 §6의 3단계를 모두 시도한 뒤에도 못 읽은 경우다 |
| 2026-09-14 | 추적하는 트랙은 워크숍, 풀페이퍼, 숏페이퍼, 포스터 넷뿐이다 |
| 2026-09-14 | 워크숍은 제안 마감이 아니라 채택 발표를 싣는다 |
| 2026-10-07 | 대표 마감 우선순위는 본 논문(초록 포함) → 포스터/LBW → 워크숍 채택 발표 |
| 2026-10-07 | 반영 전에 독립 검토를 둔다. 검토자는 Claude(`claude -p`). 추출자와 검토자의 해석이 갈린 항목은 반영하지 않고 알린다 |

"전부 바로 반영"에 대해 기록해 둔다. 회차와 본 논문 마감은 최우선 출처로
업스트림 값을 덮어쓴다. 예전 HRI 2026 사고(장소와 날짜가 통째로 틀린 채
배포)가 정확히 이 경로에서 났다. 소유자가 이 위험을 알고 바로 반영을 골랐으므로,
대신 §7의 게이트를 하위 일정보다 엄격하게 두고, §7a의 독립 검토를 거치게 하고,
모든 변경을 근거 링크와 함께 알린다(§10).

게이트만으로 부족한 이유도 기록해 둔다. 게이트는 "이 문장이 페이지에 실재하고
날짜가 그 문장에 있는가"를 본다. 지어낸 값은 막지만, 실재하는 문장을 잘못 해석한
것은 못 본다. 실제 사례: CHI 2027의 `"Thursday, October 1, 2026 : Organizer
submission deadline"`이 워크숍 제출 마감으로 해석되어 게이트를 통과했고,
2026-09부터 2026-10-07까지 사이트에 실려 있었다. 워크숍 제안 마감이었다.

## 3. 범위

### 하는 것
- 정보가 부족한 학회 선정, 공식 페이지 수집, 추출, 검증, 반영, 기록, 알림
- 새 출처 `official`과 그 병합 규칙
- 3단계 접속 시도와 `blocked` 기록

### 하지 않는 것
- GitHub Actions의 주간 빌드는 그대로 둔다. 업스트림 수집은 계속 Actions가 한다.
- 봇 차단을 뚫기 위한 실제 브라우저 연결 (2026-10-07 기준 필요한 사이트 0개)
- 추적 트랙 넷 이외의 트랙 (튜토리얼, 데모, 박사과정 컨소시엄 등)
- Mattermost 채널 설정 (§12 열린 항목)

## 4. 대상 선정 (`scripts/gaps.py`)

LLM 없이 규칙으로 고른다. 입력은 `docs/data/conferences.json`, 확인 기록
`data/official/checklog.yaml`, 오늘 날짜. 각 학회에 대해 `pickEdition`과 같은
규칙으로 표시 중인 회차를 고르고 아래를 판정한다.

| 기준 | 조건 | 다시 읽는 주기 |
|---|---|---|
| **A** | 회차가 추정(`source: estimated`)이거나 개최일이 없음 | 매주 |
| **B** | 추정이 아닌데 `paper`/`submission`/`abstract` 마감이 하나도 없음 | 매주 |
| **C** | 본 논문 마감이 모두 지났고, 개최 전이고, 포스터·LBW·워크숍 채택 발표가 없음 | 회차당 한 번. 결과가 `none`이면 그 회차는 다시 읽지 않고, `tba`면 매주 |
| **D** | 확인 기록에 `tba`로 남은 항목이 있음 | 매주, 채워질 때까지 |
| **E** | 표시 중인 회차의 출처가 `manual` | 4주마다. 단 마감이 30일 안에 있으면 매주 |

2026-10-07 기준 A 2개, B 8개, C 17개, E 6개, 중복 제외 29개. C 17개 중 다수는
NeurIPS·ICLR처럼 별도 포스터 제출 트랙이 없는 학회라, 한 번 `none`으로 기록되면
다시 읽지 않는다. 이후 주간 대상은 10개 안팎으로 예상한다.

**상한과 순서.** 한 번에 최대 12개. 순서는 A → B → D → E(마감 임박) → E → C,
같은 기준 안에서는 가장 오래 확인하지 않은 학회부터. 넘친 학회는 다음 주로 간다.
시간이 아니라 확인 기록으로 고르므로, 맥이 꺼져 한 주를 건너뛰어도 다음 실행이
밀린 대상을 그대로 이어받는다.

출력: 대상 목록 JSON (학회, 회차, 해당 기준, 후보 URL).

## 5. 데이터 흐름

```
월 06:00-09:00 KST  GitHub Actions (변경 없음)
                    업스트림 받아 빌드·커밋

월 10:00 KST        Hermes cron
  1 대상 선정       scripts/gaps.py                규칙
  2 페이지 수집     scripts/fetch_pages.py         규칙
  3 추출           Hermes (gpt-6-luna)            LLM, 받아 둔 텍스트만 읽음
  4 검증           scripts/validate_official.py   규칙 (게이트 + 해석 규칙)
  4a 독립 검토      scripts/review_official.py     Claude (claude -p), 답을 모른 채 다시 해석
  5 반영           build -> pytest -> node --test -> commit -> push
  6 기록·알림       checklog 갱신, 보고서 작성·전송
```

1, 2, 4, 5, 6은 저장소의 스크립트이고 테스트를 갖는다. Hermes는 3만, Claude는
4a만 한다. 4a를 부르고 결과를 비교하는 것은 스크립트다.
3에서 Hermes가 직접 웹을 받지 않는 이유는 둘이다.

- 같은 모델이 인용문과 그 근거 페이지를 둘 다 만들면 §7의 대조가 무의미해진다.
  근거 페이지는 반드시 스크립트가 받은 것이어야 한다.
- 2026-10-07 시험에서 Hermes가 링크를 따라다니느라 학회당 호출이 20–40번
  들었다. 텍스트를 넘겨주면 몇 번으로 줄어든다.

## 6. 페이지 수집 (`scripts/fetch_pages.py`)

학회·회차마다 아래를 시도한다.

1. **홈페이지** (`registry.yaml`의 `homepage`)
2. **회차 주소** (업스트림 데이터의 회차 `link`, 예: `chi2027.acm.org`)
3. **대체 주소**: 1, 2에서 받은 페이지가 하나도 없거나, 받은 페이지 어디에도 대상
   연도가 적혀 있지 않으면, Hermes에게 같은 학회의 그 연도 공식 주소를 찾게 하고
   (예: `www.siggraph.org` 대신 `s2027.siggraph.org`) 스크립트가 받는다.

1과 2는 둘 다 받는다. 하나가 열렸다고 멈추지 않는 이유: 홈페이지가 학회 본부
사이트인 경우가 많다. ACL의 홈페이지 `www.aclweb.org`는 열리지만 2027 일정은
`2027.aclweb.org`에만 있다. "열렸다"가 아니라 "대상 연도 정보가 있다"가 기준이다.

하위 페이지 탐색: 받은 페이지에서 같은 호스트의 링크 중 주소나 링크 문구에
`date`, `deadline`, `call`, `cfp`, `paper`, `poster`, `late-breaking`, `lbw`,
`workshop`, `important`가 든 것을 따라간다. 학회당 최대 8페이지.

3단계의 주소에는 제한을 둔다. http(s)만, 그리고 마감 모음 사이트(ccfddl,
ai-deadlines, wikicfp 등 목록으로 관리)는 받지 않는다. 공식 사이트를 읽는 것이
이 설계의 목적이기 때문이다.

3단계까지 실패하면 `blocked`로 기록한다. 2026-10-07 기준 41개 중 1단계 38개,
2단계 2개(CHI, CIKM), 3단계 1개(SIGGRAPH), `blocked` 0개.

출력 (gitignore, 실행마다 덮어씀):
- `data/official/raw/<abbr>-<year>.txt`: 받은 페이지마다 `===== <url> =====`
  머리줄 아래 태그를 벗긴 본문
- `data/official/raw/<abbr>-<year>.fetch.json`: 주소별 HTTP 결과

브라우저 식별 문자열(User-Agent)을 쓰고, 요청 사이에 1초 간격을 둔다.

## 7. 추출과 검증

### Hermes 추출 계약

입력은 §6의 `.txt` 파일뿐이다. 출력은 `data/official/raw/<abbr>-<year>.json`:

```json
{"abbr": "acl", "year": 2027,
 "edition": {"date_text": "August 17-22, 2027", "start": "2027-08-17",
             "end": "2027-08-22", "place": "Kyoto, Japan",
             "raw_text": "...", "url": "...", "confidence": "high"},
 "items": [{"type": "paper", "label": "ARR submission deadline (long & short papers)",
            "date": "2027-01-04 23:59:59", "timezone": "AoE",
            "confidence": "high", "raw_text": "...", "url": "..."}],
 "not_published": ["ARR commitment deadline: TBA"],
 "no_track": ["poster"]}
```

`type`은 `paper`, `short_paper`, `abstract`, `commitment`, `poster`, `lbw`,
`notification`(워크숍 채택 발표) 중 하나다. 워크숍 **제안** 마감, 튜토리얼, 데모,
카메라레디, 등록 마감은 뽑지 않는다. `no_track`은 해당 트랙이 그 학회에 아예 없다고
판단한 경우로, C 기준의 `none` 판정에 쓰인다. 지시문은 저장소의
`docs/hermes/official-check.md`에 두고 버전 관리한다.

### 검증 게이트 (`scripts/validate_official.py`)

모든 항목에 적용 (기존 `validate_scraped.py`와 같은 규칙):
1. `raw_text`가 **스크립트가 받은** 그 `url`의 본문에 있다. 비교할 때만 공백을
   모두 무시한다. 2026-10-07 시험에서 `2026: Paper`와 `2026 : Paper`의 차이
   하나로 실재하는 문장 셋이 떨어졌다.
2. 주장한 날짜가 `raw_text` 안에 적혀 있다.
3. `timezone: AoE`면 그 페이지에 AoE/Anywhere on Earth/UTC-12 표기가 있다.
4. 날짜가 개최일보다 늦지 않고, 개최일보다 18개월 넘게 앞서지 않는다.
5. `type`이 허용 목록에 있다. `confidence: low`는 반영하지 않는다.

회차와 본 논문 마감(`edition`, `paper`, `short_paper`, `abstract`, `commitment`)에는
추가로:
6. `confidence: high`만 받는다. `medium`도 반영하지 않는다.
7. `edition`의 개최일 범위가 `raw_text` 안에 적혀 있다 (시작일과 종료일 모두).
8. `edition`의 `place`가 공백·쉼표를 무시하고 `raw_text`에 들어 있다.
9. 연도가 대상 회차 연도와 같다.

해석 규칙 (게이트를 통과한 뒤 적용, LLM 없음):
10. **금지어**: `raw_text`에 `proposal`, `organizer`, `juror`, `reviewer`,
    `camera`, `registration`, `e-rights`, `approximately`가 있으면 `paper`,
    `short_paper`, `abstract`, `commitment`, `poster`, `lbw`가 될 수 없다.
    `approximately`는 어떤 타입으로도 반영하지 않는다. 2026-09의 CHI 오류는 이
    규칙만으로도 걸렸다.
11. **순서**: 같은 회차 안에서 `abstract` ≤ `paper` ≤ 결과 발표, 모든 마감 ≤ 개최일.
12. **연도**: `raw_text`가 있는 페이지 구간(앞뒤 1,500자)에 대상 연도가 적혀 있다.

반영하지 않은 항목은 버리지 않고 사유와 함께 보고서에 적는다. 특히 "approximately"
같은 근사값(CHI 2027 워크숍 논문 마감 Feb 11)은 사이트에는 싣지 않지만 보고서에서는
보여준다.

통과한 값은 `data/official/<abbr>.yaml`에 근거(`raw_text`, `url`)와 함께 쌓는다.
이 파일은 커밋한다.

## 7a. 독립 검토 (`scripts/review_official.py`)

§7을 통과해 **사이트를 바꾸게 될 모든 항목**을 반영 전에 Claude가 다시 해석한다.
바뀌는 것이 없는 항목(이미 같은 값이 실려 있음)은 검토하지 않는다.

**답을 보여주지 않는다.** 검토자에게 추출자의 `type`과 `label`을 주지 않는다.
주면 맞다고 도장만 찍기 쉽다. 검토자가 받는 것:
- 학회 이름, 대상 연도
- 스크립트가 받은 원문에서 `raw_text` 앞뒤 1,500자 (추출자가 아니라 스크립트의 텍스트)
- 기준 날짜 (그 문장에 들어 있는 날짜)

검토자가 답하는 것 (JSON):
```json
{"who_submits": "author | organizer | reviewer | none",
 "what": "paper | short_paper | abstract | commitment | poster | lbw | workshop_acceptance | workshop_paper | other",
 "event_year": 2027, "exact": true, "date": "2026-12-17"}
```
`edition` 항목이면 개최 시작일·종료일·장소를 따로 답한다.

**일치 판정.** 추출자의 `type`과 검토자의 `what`이 대응하고(`notification` ↔
`workshop_acceptance`), `who_submits`가 제출 타입이면 `author`, 날짜·연도가 같고,
`exact`가 참이면 일치. 하나라도 다르면 불일치.

- 일치 → 반영
- 불일치 → **반영하지 않고** 두 해석을 나란히 보고서에 적는다. 다음 주에 같은 값이
  다시 나와도 같은 판정이면 계속 보류한다. 소유자가 알림을 보고 판단할 몫이다.

이것이 "전부 바로 반영"의 유일한 예외다. 두 모델이 같은 원문을 다르게 읽었다면
원문이 애매하거나 한쪽이 틀린 것이라, 그 값을 사이트에 올리지 않는다.

**호출.** `claude -p`를 도구 없이, JSON 출력으로 부른다. 항목당 한 번, 짧은 발췌만
넣는다. 주당 수 건~20건 수준.

**도입 전 시험 (역검증).** 켜기 전에 정답을 아는 사례로 돌린다. 잡아야 할 것:
CHI 2027 10/1 Organizer submission deadline(워크숍 제출 마감이라고 주장), CHI 2027
"approximately Feb 11"(확정값이라고 주장). 통과시켜야 할 것: ACL 2027 ARR 1/4,
CHI 2027 12/17 워크숍 목록 공개, 지금 `data/scraped/`에 실린 10건. 잡아야 할 것을
모두 잡고 통과시켜야 할 것을 모두 통과시킬 때만 켠다. 결과는 구현 기록에 남긴다.

## 8. 병합: 새 출처 `official`

회차를 통째로 고르지 않고, **이미 고른 회차 위에 공식 값으로 확인된 칸만 덮어쓴다.**
통째로 바꾸면 ai-deadlines가 준 리뷰 공개일 같은 세부 일정을 잃는다.

`merge.py`에 `apply_official(edition, official)`을 둔다.
- `date_text`, `start`, `end`, `place`: 공식 값이 있으면 덮어쓴다.
- 마감: `paper`/`short_paper`/`abstract`/`commitment`/`poster`/`lbw`는 같은 타입이
  있으면 공식 값으로 바꾸고 없으면 더한다. `notification`은 같은 날짜·같은 라벨이
  없을 때만 더한다 (기존 `apply_scraped`와 같은 규칙).
- 대상 연도의 회차가 업스트림에도 manual에도 없으면 공식 값으로 새 회차를 만든다.
  개최일이 없으면 만들지 않는다.
- 공식 값과 원래 값이 다르면 둘 다 보고서에 적는다.

### 화면의 타입 처리

`short_paper`와 `commitment`를 본 논문 후보로 다룬다 (`docs/lib.js`의 `PAPER_TYPES`,
`scripts/models.py`의 `PAPER_TYPES`를 함께 고친다). ai-deadlines가 이미 쓰는
`commitment_deadline`도 같은 것으로 본다. 이게 없으면 ACL 2027처럼 ARR 마감(1/4)이
지난 뒤 commitment 마감이 올라와도 대표 마감으로 뜨지 않는다. ccfddl은 지금 EACL
commitment를 `paper`로 주고 있어 우연히 맞게 보일 뿐이다.

### 적용 순서

적용 순서는 `manual > ai-deadlines > ccfddl`로 회차를 고른 뒤 `official`을 덮고,
그다음 `cfp-scrape`를 채우고, 마지막에 예년 월 추정을 한다. E 기준(손으로 넣은 회차)도
같은 경로로 고쳐진다 - `official`이 `manual` 위에 덮인다.

추정 회차는 공식 값이 들어오면 자연히 사라진다. 추정은 개최일이 비어 있을 때만
붙기 때문이다.

## 9. 확인 기록 (`data/official/checklog.yaml`)

```yaml
acl/2027:
  last_checked: 2026-10-12
  access: ok            # ok | via_edition_link | via_alternate | blocked
  results:
    D: tba              # found | none | tba | blocked
  tba: ["ARR commitment deadline"]
  next_due: 2026-10-19
```

`gaps.py`가 읽고, 실행 마지막 단계가 쓴다. 저장소에 커밋한다. 다음 확인일은 §4의
주기로 계산한다.

## 10. 보고와 알림

실행마다 보고서를 만든다. 내용:
- 반영한 변경: 학회, 항목, 이전 값 → 새 값, 근거 문장과 주소
- 공식 값과 업스트림 값이 달랐던 곳
- 반영하지 않은 항목과 사유 (근사값, 신뢰도, 게이트 탈락, 해석 규칙)
- **추출자와 검토자의 해석이 갈려 보류한 항목**: 두 해석과 원문 발췌를 나란히
- `blocked`, `tba`로 남은 것
- 14일 안의 대표 마감

보고서는 로컬 파일 `~/.hermes/reports/conference-tracker/<YYYY-MM-DD>.md`로 남기고
(저장소 밖), Mattermost 채널이
정해지면 그 채널로도 보낸다. 바뀐 것이 없고 실패도 없으면 보내지 않는다.

## 11. 실패 처리

| 상황 | 동작 |
|---|---|
| 맥이 꺼져 실행이 빠짐 | 다음 실행이 확인 기록 기준으로 밀린 대상을 잡는다 |
| 사이트 접속 실패 | §6의 3단계를 모두 시도, 그래도 실패면 `blocked` 기록 후 다음 주 재시도 |
| Hermes 추출 실패·형식 오류 | 그 학회만 건너뛰고 기록은 갱신하지 않는다 (다음 주 재시도) |
| 게이트 탈락 | 반영하지 않고 보고서에 사유 |
| 테스트 실패 | push하지 않는다. 보고서에 실패를 적고 알린다 |
| 검토자 호출 실패 (Claude 로그인 만료, 한도 등) | 검토가 필요한 항목은 그 주에 반영하지 않는다. 검토 없이 반영하는 경로는 두지 않는다 |
| 검토자와 불일치 | 반영하지 않고 보고서에 두 해석을 적는다 (§7a) |
| push 충돌 | `git pull --rebase`. `docs/data/conferences.json`은 파생 파일이므로 손으로 병합하지 않고 빌드로 다시 만든다 |
| Actions와 동시 실행 | Hermes의 push가 `data/**`를 건드리면 Actions가 다시 돌지만, 같은 입력이라 결과가 같고 커밋도 생기지 않는다 |
| 구독 사용 한도 | 학회당 몇 번 호출로 줄이고 상한 12개를 둔다. 한도 초과로 실패하면 남은 학회는 다음 주로 |

## 12. 준비 작업과 열린 항목

준비 작업 (구현 계획에 포함):
- 프로젝트 `.venv` 생성. OS 업그레이드로 로컬 Python 패키지와 `gh`가 사라졌다.
  Hermes cron은 이 가상환경의 Python으로 스크립트를 돌린다.
- Hermes cron 등록: 매주 월 10:00 KST, 작업 디렉터리는 저장소, 사전 스크립트로
  1–2단계를 돌려 대상 목록을 지시문에 넣는다.
- `claude -p`가 cron 환경(대화형 터미널 없음)에서 로그인된 상태로 도는지 확인한다.

열린 항목:
- **Mattermost 채널.** 상태 화면에는 설정됨으로 나오지만 보낼 수 있는 채널이 아직
  없다(`hermes send --list`). 정해질 때까지 보고서는 로컬 파일로만 남긴다.
- **Hermes cron의 시간대.** 로컬 시각(KST)으로 해석하는지 구현 때 확인한다.

## 13. 테스트

- `gaps.py`: 기준 A–E 각각, 재확인 주기, `none` 이후 제외, 상한과 순서
- `fetch_pages.py`: 가짜 fetch 함수를 주입해 3단계 순서, 하위 페이지 탐색 상한,
  모음 사이트 차단, `blocked` 판정
- `validate_official.py`: 공통 게이트 1–5와 엄격 게이트 6–9 각각의 통과·탈락.
  공백 차이는 통과하고 다른 문장은 탈락하는지
- `apply_official`: 칸 덮어쓰기, 세부 일정 보존, 새 회차 생성 조건, manual 위에
  덮이는지, 추정 회차가 사라지는지
- 화면 타입: `commitment`/`commitment_deadline`/`short_paper`가 본 논문 후보로
  대표 마감이 되는지 (JS와 Python 양쪽)
- 수집: 홈페이지가 열려도 대상 연도가 없으면 회차 주소·대체 주소로 가는지
- 끝단 테스트: 2026-10-07 시험에서 받은 ACL·CHI 페이지를 고정 입력으로, 추출 JSON을
  손으로 만든 고정값으로 두고 2–6단계를 돌린다. LLM은 부르지 않는다.
- 해석 규칙 10–12 각각의 통과·탈락. CHI 10/1 사례가 금지어 규칙에 걸리는지
- `review_official.py`: 검토자 호출은 주입한 가짜 함수로 대체. 검토자에게 추출자의
  `type`/`label`이 넘어가지 않는지, 일치·불일치 판정, 호출 실패 시 반영하지 않는지
- §7a의 역검증은 실제 Claude를 부르는 별도 스크립트로 돌리고 결과를 기록한다
  (단위 테스트에는 넣지 않는다 - 네트워크와 구독에 의존하므로)
- 이 프로젝트의 관례대로, 새 테스트마다 해당 코드를 되돌려 실패하는지 확인한다.
