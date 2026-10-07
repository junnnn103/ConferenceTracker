# ConferenceTracker 공식 사이트 확인 (Hermes 지시문)

작업 디렉터리는 저장소 루트다. Python은 반드시 `.venv/bin/python`을 쓴다.
설계: `docs/superpowers/specs/2026-10-07-hermes-official-check-design.md`

## 하는 일

1. 위 사전 스크립트 출력(그리고 `data/official/raw/worklist.json`)이 이번 주 대상이다.
2. `access=needs_alternate`인 대상: 그 학회의 **그 연도 공식 사이트** 주소를 찾는다
   (예: `www.siggraph.org` 대신 `s2027.siggraph.org`). 웹 검색은 주소를 찾는 데만 쓴다.
   찾으면 직접 읽지 말고 이렇게 받게 한다:
   `.venv/bin/python -m scripts.fetch_pages --target <key> <year> --urls <주소1> [<주소2> ...]`
   못 찾으면 건너뛴다.
3. `access`가 `needs_alternate`도 `blocked`도 아닌 **모든** 대상 - 즉 `ok`, `via_edition_link`,
   그리고 2단계에서 `--urls`로 다시 받은 `via_alternate` - 에 대해
   `data/official/raw/<key>-<year>.txt`**만** 읽고
   `data/official/raw/<key>-<year>.json`을 아래 형식으로 쓴다.
4. 마지막에 `.venv/bin/python -m scripts.official_run apply`를 실행한다.
5. 최종 응답은 한 줄: `apply 종료 코드 <n>`. 결과를 요약하지 않는다 - 보고서는 스크립트가 보낸다.

## 추출 JSON 형식

```json
{"abbr": "<key>", "year": 2027,
 "edition": {"date_text": "August 17-22, 2027", "start": "2027-08-17", "end": "2027-08-22",
             "place": "Kyoto, Japan", "raw_text": "<개최일과 장소가 함께 든 원문 문장>",
             "url": "<그 문장이 있는 섹션 주소>", "confidence": "high"},
 "items": [{"type": "paper", "label": "<페이지의 표현 그대로>", "date": "2027-01-04 23:59:59",
            "timezone": "AoE", "confidence": "high", "raw_text": "<원문 문장 그대로>", "url": "<섹션 주소>"}],
 "not_published": ["<TBA·미공개로 적힌 항목>"],
 "no_track": ["<이 학회에 아예 없는 트랙: poster | lbw | workshop>"]}
```

## 규칙

- 사전 스크립트 출력이 `준비 실패`로 시작하면(예: `준비 실패: git pull 실패 ...`, `준비 실패: master 브랜치가 아님 ...`)
  아무것도 하지 말고 그 줄을 그대로 답하고 멈춘다. 알림은 스크립트가 이미 보냈다.
- 쓰는 파일은 `data/official/raw/<key>-<year>.json` **하나뿐**이다. `data/official/*.yaml`,
  `checklog.yaml`, `docs/**` 등 다른 파일은 절대 고치지 않는다. git 명령은 실행하지 않는다.

- `type`은 다음 중 하나만: `paper`(본 논문), `short_paper`, `abstract`, `commitment`(ARR commitment),
  `poster`, `lbw`(late-breaking work), `notification`(어떤 워크숍이 채택됐는지 공개되는 날,
  또는 워크숍 논문 저자 통보일).
- 싣지 않는 것: 워크숍 **제안** 마감(organizer가 내는 것), 튜토리얼, 데모, 박사과정 컨소시엄,
  카메라레디, 등록 마감, 리뷰어·심사위원 관련 날짜.
- `raw_text`는 `.txt`에서 그대로 복사한다. 고치거나 요약하지 않는다. `url`은 그 문장이 든
  `===== <url> =====` 섹션의 주소다. `.txt`에 없는 주소를 쓰지 않는다.
- 날짜를 추측하지 않는다. "approximately", "TBA" 같은 값은 `items`에 넣지 말고 `not_published`에 적는다.
- `timezone`은 그 페이지가 AoE / Anywhere on Earth / UTC-12를 밝힌 경우에만 `"AoE"`. 아니면 넣지 않는다.
- `edition`은 페이지가 개최일과 장소를 함께 밝힌 경우에만. 아니면 `null`.
- 확실하지 않으면 `confidence`를 `medium`이나 `low`로 둔다. 회차·본 논문은 `high`만 반영된다.
- 마감 모음 사이트(ccfddl, ai-deadlines, wikicfp 등)의 값은 근거로 쓰지 않는다.
