// DOM에 의존하지 않는 순수 로직. node --test로 검증한다.
//
// D-day와 회차 선택을 브라우저의 현재 날짜로 계산하는 것이 핵심이다.
// 빌드가 며칠 밀려도 표시가 어긋나지 않아야 하기 때문이다.

const MS_PER_DAY = 86400000;
const GRADE_RANK = { 최우수: 0, 우수: 1 };
// BK(한국정보과학회) 등급. 회사 등급과 별개 기준이라 회사 등급이 같은 학회들
// 사이의 우선순위를 가르는 2차 기준으로만 쓴다 - sortKey의 "grade" 케이스 참고.
const BK_RANK = { S: 0, A: 1 };

// primary_deadline을 고를 때 "본 논문 마감"으로 인정하는 타입.
// 우선순위가 있는 단계별 폴백이다 - 평평한 집합이 아니다. "submission"은
// ECCV의 튜토리얼/워크숍/AI Art 제출처럼 논문과 무관한 트랙에도 쓰이므로,
// "paper" 타입이 하나라도 있으면 그것만 후보로 삼고 "submission"은 "paper"가
// 전혀 없는 학회(ICASSP, INTERSPEECH 등)에서만 대신 쓴다.
// scripts/models.py의 PAPER_TYPES/SUBMISSION_FALLBACK_TYPES와 반드시 같아야
// 한다 — 여기서 다르게 고르면 build가 계산한 primary_deadline과 브라우저가
// 고르는 다음 회차가 서로 다른 기준으로 어긋나게 된다.
const PAPER_TYPES = ["paper"];
const SUBMISSION_FALLBACK_TYPES = ["submission"];
// abstract는 본 논문의 선행 조건이다. 많은 학회가 초록을 먼저 등록해야
// 본문을 낼 수 있게 해서(17개 학회가 본 논문 1주 전후로 abstract를 둔다),
// 실제로 먼저 닥치는 마감은 abstract 쪽이다.
const ABSTRACT_TYPES = ["abstract"];
// 본 논문 다음에도 여전히 "낼 수 있는" 트랙들. 논문 마감이 지나도 포스터나
// 워크숍은 몇 주 더 열려 있는 일이 흔하다(CHI 2027은 본 논문 9/10, 워크숍
// 10/1, 포스터 이듬해 1/21). 이걸 후보에서 빼면 아직 낼 곳이 있는 학회가
// "마감됨"으로 보인다.
// workshop 제안 마감은 뺀다. 그건 워크숍을 열려는 조직위가 내는 것이지
// 논문을 내는 사람의 마감이 아니다. 대신 "어떤 워크숍이 채택됐는지" 알려주는
// notification이 참가자에게 의미 있는 날짜라, 그 값이 있으면 그것을 쓴다
// (workshopNotification 참고).
const LATE_SUBMISSION_TYPES = [
  "poster",
  "lbw",
  "demo",
  "tutorial",
  "doctoral_consortium",
];

/** 워크숍 채택 결과 발표일. 라벨에 workshop이 들어간 notification을 찾는다. */
function workshopNotifications(deadlines) {
  return deadlines.filter(
    (d) => d.type === "notification" && /workshop/i.test(d.label || ""),
  );
}

/**
 * D-day를 셀 후보. 제출 계열만 센다.
 *
 * 같은 deadlines 배열에 등록/리뷰공개/통보/camera-ready 같은 행정 일정이
 * 섞여 있어서, 타입을 가리지 않으면 "다음 마감"이 제출과 무관한 통보일로
 * 뽑힌다. 반대로 논문 마감 하나만 보면 뒤에 남은 포스터·워크숍을 놓친다.
 *
 * 그래서 두 단계로 나눈다. 먼저 본 논문 계열(paper, 없으면 submission)을
 * 보고, 그것이 전부 지났으면 후발 제출 트랙을 본다. 순서를 이렇게 둔 이유는
 * 논문 마감이 아직 남아 있을 때 워크숍 마감이 더 이르다고 해서 그걸
 * 대표로 보여주면 정작 중요한 쪽을 가리기 때문이다.
 */
function paperCandidates(deadlines, now) {
  const papers = deadlines.filter((d) => PAPER_TYPES.includes(d.type));
  const main = papers.length > 0
    ? papers
    : deadlines.filter((d) => SUBMISSION_FALLBACK_TYPES.includes(d.type));

  // now가 없으면(정렬 등 시점 무관 호출) 기존대로 본 논문 계열만 돌려준다.
  if (!now) return main;

  const today = startOfDay(now);
  const mainOpen = main.filter((d) => startOfDay(d.date) >= today);

  if (mainOpen.length > 0) {
    // 본 논문이 아직 남았다면, 그보다 앞선 abstract가 있는지 먼저 본다.
    // 초록을 놓치면 본문을 아예 못 내므로 그쪽이 실질적인 마감이다.
    const earliestMain = mainOpen
      .map((d) => startOfDay(d.date))
      .reduce((a, b) => Math.min(a, b));
    const abstracts = deadlines.filter(
      (d) =>
        ABSTRACT_TYPES.includes(d.type) &&
        startOfDay(d.date) >= today &&
        startOfDay(d.date) <= earliestMain,
    );
    return abstracts.length > 0 ? abstracts : main;
  }

  const late = deadlines.filter((d) => LATE_SUBMISSION_TYPES.includes(d.type));
  const lateOpen = late.filter((d) => startOfDay(d.date) >= today);
  if (lateOpen.length > 0) return lateOpen;

  // 남은 제출 트랙이 없으면 워크숍 채택 발표를 본다 - 참가를 저울질하는
  // 사람에게는 그것이 다음에 확인할 날짜다.
  const wsOpen = workshopNotifications(deadlines).filter(
    (d) => startOfDay(d.date) >= today,
  );
  if (wsOpen.length > 0) return wsOpen;

  // 전부 지났으면 본 논문 계열을 그대로 둔다 - 셀이 "마감됨"으로 보여야 하고,
  // 그 기준은 후발 트랙의 마지막 날이 아니라 본 논문 마감이다.
  return main;
}

/**
 * 날짜를 하루 단위 UTC 타임스탬프로 정규화한다.
 *
 * 두 입력의 의미가 다르므로 처리도 달라야 한다. 마감 문자열
 * ("2026-11-01T23:59:59"처럼 오프셋이 없는 것)은 발표된 달력 날짜이므로
 * 앞 10자(연-월-일)만 읽어 UTC로 고정한다 - JS의 기본 파싱에 맡기면
 * 오프셋 없는 시각을 뷰어의 로컬 시간대로 해석해서, 예를 들어 서부 미국
 * 뷰어는 같은 마감을 하루 늦은 날짜로 보게 된다. 반대로 now는 뷰어 자신의
 * '오늘'이므로 로컬 달력 날짜(getFullYear/getMonth/getDate)를 그대로 쓴다.
 */
function startOfDay(value) {
  if (typeof value === "string") {
    const [y, m, d] = value.slice(0, 10).split("-").map(Number);
    return Date.UTC(y, m - 1, d);
  }
  return Date.UTC(value.getFullYear(), value.getMonth(), value.getDate());
}

/** 오늘부터 대상 날짜까지의 일수. 과거면 음수, 입력이 없으면 null. */
export function dayDelta(isoDate, now) {
  if (!isoDate) return null;
  return Math.round((startOfDay(isoDate) - startOfDay(now)) / MS_PER_DAY);
}

/**
 * 종료일이 오늘 이후인 회차 중 가장 이른 것. 없으면 가장 최근에 지난 회차.
 *
 * 날짜가 없어도 아직 지나지 않은 마감(primary_deadline)이 있는 회차는
 * '차기' 후보로 인정한다 - scripts/merge.py의 select_editions와 같은
 * 규칙이다. build가 이미 직전 1개/차기 1개로 추려서 넘기지만, 브라우저는
 * 자신의 '오늘'로 다시 골라야 날짜 경계를 넘어가도 어긋나지 않으므로
 * 여기서도 같은 기준을 써야 한다 - 안 그러면 MLSys처럼 날짜 없이 마감만
 * 확정된 회차가 브라우저에서 다시 탈락하고, 이미 끝난 이전 회차가 대신
 * 뽑혀 종료된 것처럼 보인다.
 */
/** 추정 회차가 가리키는 달의 1일. 확정 일정이 없을 때의 정렬/비교 기준이다. */
export function estimatedStart(edition) {
  if (!edition || !edition.estimated_month) return null;
  return Date.UTC(edition.year, edition.estimated_month - 1, 1);
}

export function pickEdition(editions, now) {
  if (!editions || editions.length === 0) return null;
  const dated = editions.filter((e) => e.end || e.start);
  const undatedWithDeadline = editions.filter(
    (e) => !(e.end || e.start) && e.primary_deadline
  );
  const hasEstimate = editions.some((e) => !(e.end || e.start) && e.estimated_month);
  if (dated.length === 0 && undatedWithDeadline.length === 0 && !hasEstimate) {
    return editions[editions.length - 1];
  }

  const today = startOfDay(now);
  // 확정 일정도 마감도 없지만 예년 기준 개최월이 붙은 회차(ICML 2027처럼
  // 아직 아무 소스에도 안 올라온 다음 회차)도 '차기' 후보로 본다. 이게
  // 없으면 이미 끝난 지난 회차가 계속 대표로 뽑혀 행이 회색으로 남는다.
  const estimated = editions.filter(
    (e) => !(e.end || e.start) && !e.primary_deadline && e.estimated_month
  );
  const upcoming = [
    ...dated
      .filter((e) => startOfDay(e.end || e.start) >= today)
      .map((e) => [startOfDay(e.start || e.end), e]),
    ...undatedWithDeadline
      .filter((e) => startOfDay(e.primary_deadline) >= today)
      .map((e) => [startOfDay(e.primary_deadline), e]),
    ...estimated
      .filter((e) => estimatedStart(e) >= today)
      .map((e) => [estimatedStart(e), e]),
  ].sort((a, b) => a[0] - b[0]);
  if (upcoming.length > 0) return upcoming[0][1];

  if (dated.length > 0) {
    return dated
      .slice()
      .sort((a, b) => startOfDay(a.end || a.start) - startOfDay(b.end || b.start))
      .pop();
  }
  return editions[editions.length - 1];
}

/**
 * 화면에 대표로 보여줄 마감. 아직 지나지 않은 것 중 가장 이른 것을 고른다.
 *
 * 롤링 마감을 쓰는 학회(UbiComp은 연 4회)에서 build가 계산해 둔
 * primary_deadline은 "가장 늦은 라운드"라, 학회가 끝난 뒤 날짜가 대표로 뜬다.
 * 연구자에게 쓸모 있는 값은 다음에 닥칠 마감이므로 브라우저에서 고른다.
 *
 * 후보는 논문 마감 타입(paper, 없으면 submission)으로 한정한다 — 실제
 * 데이터에는 같은 deadlines 배열에 등록/리뷰공개/통보/camera-ready 같은
 * 행정 일정도 섞여 있어서(WACV, SIGGRAPH, ECCV), 타입을 가리지 않고
 * 날짜순으로만 고르면 "다음 마감"이 논문 제출과 무관한 통보일이나
 * camera-ready로 뽑힐 수 있다. paperCandidates가 paper/submission 사이의
 * 우선순위까지 가려낸다 — ECCV의 AI Art Submission처럼 무관한 트랙에도
 * "submission" 타입이 쓰이기 때문이다.
 */
export function nextDeadline(edition, now) {
  const deadlines = edition?.deadlines ?? [];
  const all = paperCandidates(deadlines, now);
  if (all.length === 0) {
    // 두 경우는 답이 다르다. deadlines가 아예 비어 있으면(마감 배열 없이
    // primary_deadline만 있는 소스) primary_deadline으로 합성해서 보여주는
    // 수밖에 없고, 그래도 안전하다 - extraDeadlines가 뺄 실제 항목이 배열에
    // 없기 때문이다. 하지만 deadlines에 항목은 있는데 그중 paper/submission
    // 타입이 하나도 없다면(예: notification과 camera_ready만 있는 경우),
    // primary_deadline으로 합성한 객체는 deadlines의 그 무엇과도 같은 참조가
    // 아니라서 extraDeadlines가 아무것도 못 빼고, 셀에 뜬 마감이 펼침
    // 목록에도 중복으로 나타난다. 게다가 notification/camera_ready 날짜를
    // "제출마감"이라 부르는 것 자체가 틀렸다 - paper-over-submission
    // 우선순위와 같은 판단이다. 이 경우 null을 돌려주면 셀은 미정으로
    // 뜨고, 모든 단계가 그대로 펼침 목록에 남는다.
    if (deadlines.length > 0) return null;
    return edition?.primary_deadline
      ? { type: "paper", label: "Paper", date: edition.primary_deadline }
      : null;
  }
  const today = startOfDay(now);
  const sorted = all.slice().sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return sorted.find((d) => startOfDay(d.date) >= today) ?? sorted[sorted.length - 1];
}

// AoE(Anywhere on Earth)는 UTC-12다. 논문 마감은 거의 다 이 기준이라
// (전체 마감 236건이 AoE 표기) 한국에서 보면 실제 여유가 하루 더 있다 -
// AoE 9월 18일 23:59는 KST로 9월 19일 20:59까지다. 시차를 모르고 AoE
// 날짜를 그대로 읽으면 하루를 손해 본다.
const AOE_TIMEZONES = new Set(["AoE", "AOE", "UTC-12"]);
const KST_OFFSET_HOURS = 9;
const AOE_OFFSET_HOURS = -12;

/** 이 마감이 AoE 기준인가. */
export function isAoeDeadline(deadline) {
  return AOE_TIMEZONES.has((deadline?.timezone || "").trim());
}

/**
 * AoE 마감을 KST 시각으로 옮긴다.
 *
 * 마감 문자열("2026-09-18T23:59:59")에는 오프셋이 없고 그 자체가 AoE 벽시계
 * 시각이다. UTC로 되돌린 뒤(+12h) KST로 옮긴다(+9h) - 합쳐서 21시간이라
 * 대개 날짜가 하루 밀린다.
 */
export function toKst(isoDate) {
  const [datePart, timePart = "00:00:00"] = String(isoDate).split("T");
  const [y, m, d] = datePart.split("-").map(Number);
  const [hh, mm, ss] = timePart.split(":").map((v) => Number(v) || 0);
  const utcMs = Date.UTC(y, m - 1, d, hh, mm, ss);
  return new Date(utcMs + (KST_OFFSET_HOURS - AOE_OFFSET_HOURS) * 3600 * 1000);
}

/**
 * 마감 하나를 화면에 표시할 값으로 바꾼다.
 *
 * 제출마감 칸과 펼침 목록이 같이 쓴다. 예전에는 펼침 목록이 app.js에서
 * 따로 날짜를 만들었는데, 그 쪽만 두 가지가 어긋나 있었다 - AoE->KST 환산을
 * 하지 않아 같은 마감이 칸에서는 Jan 12, 펼침에서는 Jan 11로 보였고,
 * new Date(stage.date)로 곧바로 파싱해 시간 없는 날짜가 뷰어 시간대에 따라
 * 하루 당겨졌다(KST에서 2027-02-16이 Feb 15로). 두 곳이 각자 날짜를 만들면
 * 한 쪽만 고쳐지므로 계산을 여기 하나로 모은다.
 */
export function formatStage(deadline, now) {
  // AoE 마감은 KST로 옮겨 보여준다. 한국에서 실제로 낼 수 있는 시각이
  // 하루 뒤이므로, AoE 날짜를 그대로 띄우면 없는 마감 압박을 만든다.
  const aoe = isAoeDeadline(deadline);
  const shownDate = aoe ? toKst(deadline.date).toISOString() : deadline.date;
  const delta = dayDelta(shownDate, now);
  // startOfDay는 마감의 달력 날짜를 UTC 자정으로 고정해 두므로, 이걸 다시
  // UTC로 표시하면 뷰어의 시간대와 무관하게 항상 같은 날짜가 나온다.
  // new Date(shownDate)를 곧바로 넘기면 오프셋 없는 시각이 로컬로 파싱되어
  // 자정 근처 마감(예: 23:59:59)이 시간대에 따라 하루 밀려 보일 수 있다.
  const text = new Date(startOfDay(shownDate)).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  if (delta >= 0) {
    return { state: "upcoming", text, dday: `D-${delta}`, label: deadline.label, aoe };
  }
  // 이미 지난 마감에는 D-day를 붙이지 않는다. 남은 제출 트랙이 하나도 없어
  // 이 회차에 더 낼 곳이 없다는 뜻이고, "며칠 전에 끝났는지"는 셀에 이미
  // 취소선과 날짜로 드러난다. D+ 숫자는 아직 셀 것이 있다는 오해만 준다.
  return { state: "past", text, dday: "", label: deadline.label, aoe };
}

/** 제출마감 셀에 표시할 값. */
export function formatDeadline(edition, now) {
  const chosen = nextDeadline(edition, now);
  if (!chosen) return { state: "unknown", text: "미정", dday: "", label: "", aoe: false };
  return formatStage(chosen, now);
}

/**
 * 회차의 모든 단계를 시간순으로 돌려준다. 셀에 뜨는 주 마감을 포함해
 * 아무것도 빼지 않는다 - 토글을 펼쳤을 때 보여줄 전체 일정표다.
 *
 * 예전 이름은 extraDeadlines였고 nextDeadline이 고른 항목을 뺐다. 그런데
 * ECCV(12단계 중 11개만 노출), UbiComp(4개 중 3개), WACV(11개 중 10개)처럼
 * 뺀 항목이 하필 가장 중요한 '본 마감'이라, 펼쳤을 때 일정표에 정작 지금
 * 다가오는 마감이 빠진 구멍이 생겼다. 어느 게 대표인지는 렌더러가
 * isFeaturedDeadline로 표시만 하고, 목록 자체는 항상 전부를 보여준다.
 *
 * now를 받지 않는다 - 정렬은 날짜값 비교만으로 끝나고 '오늘'과 무관하며,
 * 무엇을 뺄지 판단하던 로직(그게 now를 썼던 유일한 이유)이 이제 없다.
 */
export function allDeadlines(edition) {
  if (!edition || !edition.deadlines) return [];
  return edition.deadlines
    .slice()
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}

/**
 * 이 단계가 셀에 뜨는 대표 마감(nextDeadline이 고른 바로 그 항목)인지
 * 판단한다. 날짜 값이 아니라 참조 동일성으로 비교한다 - 같은 시각에 걸린
 * 서로 다른 두 단계가 있어도(예: HRI 2027의 Short Contributions와
 * alt.HRI가 둘 다 10-01) 날짜만으로는 어느 쪽이 대표인지 구분할 수 없기
 * 때문이다. extraDeadlines가 쓰던 것과 같은 판단 기준을 그대로 옮겼다.
 *
 * nextDeadline은 edition.deadlines가 완전히 비어 있을 때만 primary_deadline
 * 으로 새 객체를 합성해 돌려준다 - 그 객체는 deadlines의 어떤 원소와도
 * 동일한 참조가 아니므로 이 함수는 항상 false를 돌려주게 된다. 이 함수를
 * 부르는 쪽(allDeadlines가 목록을 채운 경우)은 deadlines가 비어 있지
 * 않다는 뜻이라 그 경로를 절대 타지 않아야 맞지만, 가정에 기대는 대신
 * 여기서 단언해 어긋나면 콘솔에 드러나게 한다.
 */
export function isFeaturedDeadline(deadline, edition, now) {
  console.assert(
    (edition?.deadlines?.length ?? 0) > 0,
    "isFeaturedDeadline: edition.deadlines가 비어 있다 - nextDeadline이 " +
      "합성한 객체와 비교하게 되어 항상 false만 나온다. allDeadlines가 이미 " +
      "빈 목록을 돌려줘야 할 상황인데 이 함수가 불렸다는 뜻이다."
  );
  return deadline === nextDeadline(edition, now);
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/**
 * 개최일 표시. 소스가 준 원문이 있으면 그대로 쓴다.
 *
 * 확정 일정이 없고 예년 기준 월만 아는 회차는 "July, 2027 (미정)"으로
 * 보여준다 - 그냥 "미정"이라고만 두면 대략 언제인지조차 알 수 없는데,
 * 매년 같은 달에 열리는 학회라 그 정보는 이미 갖고 있다. (미정)을 반드시
 * 붙여 확정 일정과 구별한다.
 */
export function formatDateRange(edition) {
  if (!edition) return "미정";
  if (edition.date_text) return edition.date_text;
  if (!edition.start && edition.estimated_month) {
    return `${MONTH_NAMES[edition.estimated_month - 1]}, ${edition.year} (미정)`;
  }
  if (!edition.start) return "미정";
  return edition.end && edition.end !== edition.start
    ? `${edition.start} ~ ${edition.end}`
    : edition.start;
}

/** BK 등급 표시 텍스트. BK 목록에 없는 학회는 "-"로 표시해 값이 아직 없는
 * 상태(undefined)와 구분한다 - "-"가 없으면 '확인 안 됨'과 헷갈린다. */
export function bkGradeLabel(conf) {
  return conf.bk_grade ?? "-";
}

/**
 * SR(회사) 등급. 26년 우수 학회 List에 없으면 "-".
 *
 * BK 목록에만 있고 회사 목록에는 없는 학회가 있다(EACL, CSCW). 그런 행에서
 * conf.grade는 빈 문자열인데, 이걸 그대로 배지에 넣으면 글자 없는 은색
 * 배지가 떠서 "우수"처럼 보인다 - BK 쪽과 똑같이 "-"로 세운다.
 */
export function srGradeLabel(conf) {
  return conf.grade || "-";
}

/** SR 등급을 배지 시각 클래스로 매핑한다. bkGradeBadgeClass와 짝이다. */
export function srGradeBadgeClass(conf) {
  if (conf.grade === "최우수") return "top";
  if (conf.grade === "우수") return "good";
  return "grade-none";
}

/** 등급 칸에 실제로 표시되는 전체 텍스트, 예: "최우수(S)", "우수(-)", "-(A)". */
export function gradeCellText(conf) {
  return `${srGradeLabel(conf)}(${bkGradeLabel(conf)})`;
}

/** BK 등급을 배지 시각 클래스로 매핑한다. S/A는 SR(회사) 등급과 같은
 * gold/silver 언어를 그대로 쓰고(grade-s/grade-a), 목록에 없으면 채움 없는
 * grade-none이 된다 - "없음"이 세 번째 등급처럼 보이면 안 되기 때문. app.js가
 * 이 매핑을 직접 하면 두 곳(어떤 값이 gold/silver인지)이 따로 어긋날 수
 * 있으므로 여기 한 곳에만 둔다. */
export function bkGradeBadgeClass(conf) {
  const label = bkGradeLabel(conf);
  if (label === "S") return "grade-s";
  if (label === "A") return "grade-a";
  return "grade-none";
}

function sortKey(conf, key, now) {
  const edition = pickEdition(conf.editions, now);
  switch (key) {
    case "abbr":
      return conf.abbr.toLowerCase();
    case "field":
      return conf.field.toLowerCase();
    case "grade": {
      // 회사 등급이 1차 기준, BK 등급은 그 안에서만 순위를 가르는 2차
      // 기준이다(예: 최우수(S) < 최우수(A) < 최우수(-) < 우수(S) < ...).
      // BK_RANK 항목 수(2)보다 큰 배수를 쓰면 항상 회사 등급이 우선한다.
      const companyRank = GRADE_RANK[conf.grade] ?? 99;
      const bkRank = BK_RANK[conf.bk_grade] ?? 2;
      return companyRank * 3 + bkRank;
    }
    case "place":
      return (edition?.place || "").toLowerCase();
    case "deadline": {
      const chosen = nextDeadline(edition, now);
      return chosen ? startOfDay(chosen.date) : Number.POSITIVE_INFINITY;
    }
    case "date":
    default: {
      const when = edition?.start || edition?.end;
      if (when) return startOfDay(when);
      // 추정 회차는 그 달 1일 기준으로 줄 세운다. 맨 뒤로 밀면 "7월"이라고
      // 써 놓고 12월 학회보다 아래에 놓이는 모순이 생긴다.
      return estimatedStart(edition) ?? Number.POSITIVE_INFINITY;
    }
  }
}

/**
 * 표시 중인 회차가 이미 끝났는가. pickEdition은 다가오는 회차를 우선하므로,
 * 이것이 참이면 예정된 회차가 아예 없다는 뜻이다.
 * 정렬(하단으로 밀기)과 표시(회색 처리)가 같은 판단을 쓰도록 한 곳에 둔다.
 */
export function isEnded(conf, now) {
  const edition = pickEdition(conf.editions, now);
  const end = edition?.end || edition?.start;
  if (!end) return false;
  const today = startOfDay(now);
  return startOfDay(end) < today;
}

/**
 * 정렬 비교자. 이미 지난 회차는 정렬 키와 무관하게 항상 아래로 민다 —
 * 가까운 미래가 맨 위에 오는 것이 이 표의 목적이기 때문이다.
 */
export function compareBy(key, direction, now) {
  const sign = direction === "desc" ? -1 : 1;

  return (a, b) => {
    const pastA = isEnded(a, now);
    const pastB = isEnded(b, now);
    if (pastA !== pastB) return pastA ? 1 : -1;

    const ka = sortKey(a, key, now);
    const kb = sortKey(b, key, now);
    if (ka < kb) return -1 * sign;
    if (ka > kb) return 1 * sign;
    return a.abbr.localeCompare(b.abbr);
  };
}

/**
 * 필터 통과 여부. fields/grades/bkGrades는 Set이며 빈 Set은 '전체'를 뜻한다.
 *
 * grades(SR)와 bkGrades(BK)는 서로 다른 기준이라 따로 건다. 둘을 함께 켜면
 * 교집합이 된다 - 예를 들어 SR 우수 + BK S를 고르면 회사 기준으로는 우수인데
 * BK는 최우수로 보는 학회만 남아, 두 기준이 갈리는 쪽을 골라낼 수 있다.
 */
export function matchesFilters(conf, filters, now) {
  if (filters.fields.size > 0 && !filters.fields.has(conf.field)) return false;
  // BK 쪽과 같은 규칙: SR 목록에 없으면 '-'로 걸러 "SR 미등재만 보기"가 된다.
  if (filters.grades.size > 0 && !filters.grades.has(conf.grade || "-")) return false;
  if (filters.bkGrades && filters.bkGrades.size > 0) {
    // BK 목록에 없는 학회는 '-'로 거른다 - null과 '-'를 같은 값으로 다뤄야
    // "BK 미등재만 보기"가 가능하다.
    if (!filters.bkGrades.has(conf.bk_grade || "-")) return false;
  }
  if (filters.aiOnly && !conf.ai_specialist) return false;

  if (filters.hidePast) {
    // 셀에 실제로 뜨는 값(nextDeadline)으로 판단해야 한다. primary_deadline은
    // deadlines 배열에 있는 모든 타입 중 가장 늦은 것의 최댓값이라 - CVPR,
    // ACL, SIGGRAPH 2027처럼 deadlines에 paper/submission 타입이 하나도
    // 없이 poster/workshop/demo 등만 있는 회차에서는 nextDeadline이 null(셀:
    // 미정)을 돌려주는데도 primary_deadline은 그 workshop 마감으로 값을
    // 가진다. 그러면 셀은 미정인데 hidePast는 그 마감을 기준으로 판단해
    // 필터와 화면이 서로 다른 근거로 어긋난다.
    const edition = pickEdition(conf.editions, now);
    const chosen = nextDeadline(edition, now);
    const delta = dayDelta(chosen?.date, now);
    if (delta === null || delta < 0) return false;
  }

  const query = (filters.query || "").trim().toLowerCase();
  if (query) {
    const haystack = `${conf.abbr} ${conf.full_name}`.toLowerCase();
    if (!haystack.includes(query)) return false;
  }
  return true;
}
