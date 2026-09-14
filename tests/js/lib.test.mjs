import assert from "node:assert/strict";
import { test } from "node:test";

import {
  allDeadlines,
  bkGradeBadgeClass,
  bkGradeLabel,
  compareBy,
  dayDelta,
  formatDateRange,
  formatDeadline,
  formatStage,
  gradeCellText,
  isAoeDeadline,
  isEnded,
  isFeaturedDeadline,
  matchesFilters,
  nextDeadline,
  pickEdition,
  srGradeBadgeClass,
  srGradeLabel,
  toKst,
} from "../../docs/lib.js";

// 로컬 달력 날짜 생성자를 쓴다 - "2026-09-08T00:00:00Z" 같은 UTC 인스턴트
// 문자열은 서부 미국 등에서 로컬로 환산하면 전날(9/7)이 되어, startOfDay가
// now를 로컬 날짜로 읽도록 고친 뒤에는 테스트 자체가 시간대에 따라
// 달라진다. new Date(2026, 8, 8)은 어느 시간대에서 실행해도 "9월 8일"을
// 뜻한다.
const NOW = new Date(2026, 8, 8);

const edition = (year, start, end, primary) => ({
  year,
  date_text: `${start} ~ ${end}`,
  start,
  end,
  place: "Somewhere",
  link: null,
  deadlines: primary ? [{ type: "paper", label: "Paper", date: primary, source: "ccfddl" }] : [],
  primary_deadline: primary ?? null,
  source: "ccfddl",
});

const conf = (over = {}) => ({
  abbr: "EMNLP",
  abbr_group: "emnlp",
  full_name: "Empirical Methods in NLP",
  grade: "최우수",
  ai_specialist: true,
  field: "NLP",
  homepage: "https://example.org/",
  editions: [edition(2026, "2026-10-24", "2026-10-29", "2026-05-25T23:59:59")],
  ...over,
});

test("dayDelta counts whole days to a future date", () => {
  assert.equal(dayDelta("2026-09-18T23:59:59", NOW), 10);
});

test("dayDelta is negative for a passed date", () => {
  assert.equal(dayDelta("2026-05-25T23:59:59", NOW), -106);
});

test("dayDelta returns null for missing input", () => {
  assert.equal(dayDelta(null, NOW), null);
});

test("pickEdition prefers the next upcoming one", () => {
  const editions = [
    edition(2025, "2025-11-05", "2025-11-09", "2025-05-19T23:59:59"),
    edition(2026, "2026-10-24", "2026-10-29", "2026-05-25T23:59:59"),
  ];
  assert.equal(pickEdition(editions, NOW).year, 2026);
});

test("pickEdition falls back to the most recent past one", () => {
  const editions = [edition(2025, "2025-11-05", "2025-11-09", null)];
  assert.equal(pickEdition(editions, NOW).year, 2025);
});

test("pickEdition returns null for an empty list", () => {
  assert.equal(pickEdition([], NOW), null);
});

// MLSys 2027: date는 TBD지만 마감(primary_deadline)은 확정되어 있다.
// scripts/merge.py의 select_editions와 같은 규칙으로, 날짜가 없어도 아직
// 지나지 않은 마감이 있으면 '차기'로 뽑아야 한다.
test("pickEdition picks an undated edition with a future primary_deadline over an already-ended dated one", () => {
  const editions = [
    edition(2026, "2026-03-01", "2026-03-05", null), // 이미 끝난 회차
    edition(2027, null, null, "2026-10-30T23:59:59"), // 날짜 미상, 마감만 확정
  ];
  assert.equal(pickEdition(editions, NOW).year, 2027);
});

test("pickEdition ignores an undated edition whose primary_deadline already passed", () => {
  const editions = [
    edition(2026, "2026-03-01", "2026-03-05", null),
    edition(2027, null, null, "2025-01-01T23:59:59"),
  ];
  assert.equal(pickEdition(editions, NOW).year, 2026);
});

test("isEnded is false for an undated edition with a future primary_deadline", () => {
  // pickEdition이 이 회차를 고른 뒤, isEnded는 end/start가 없으므로 '종료'로
  // 판단하지 않아야 한다 - 회색 처리되면 안 된다.
  const conf1 = conf({
    abbr: "MLSYS",
    editions: [
      edition(2026, "2026-03-01", "2026-03-05", null),
      edition(2027, null, null, "2026-10-30T23:59:59"),
    ],
  });
  assert.equal(isEnded(conf1, NOW), false);
});

test("formatDeadline marks a future deadline as upcoming", () => {
  const result = formatDeadline(edition(2027, "2027-01-01", "2027-01-05", "2026-12-01T23:59:59"), NOW);
  assert.equal(result.state, "upcoming");
  assert.equal(result.dday, "D-84");
});

test("formatDeadline drops the D-day once every submission deadline has passed", () => {
  // 지난 마감에 D+ 숫자를 붙이면 아직 셀 것이 남은 것처럼 읽힌다. 이 상태의
  // 뜻은 "이 회차에 더 낼 곳이 없다"이고, 그건 취소선과 날짜로 이미 드러난다.
  const result = formatDeadline(edition(2026, "2026-10-24", "2026-10-29", "2026-05-25T23:59:59"), NOW);
  assert.equal(result.state, "past");
  assert.equal(result.dday, "");
  assert.equal(result.text, "May 25, 2026");
});


test("formatDeadline reports unknown when there is no deadline", () => {
  const result = formatDeadline(edition(2026, "2026-10-24", "2026-10-29", null), NOW);
  assert.equal(result.state, "unknown");
  assert.equal(result.text, "미정");
});

test("formatDeadline's text is the deadline's calendar date regardless of the viewer's timezone", () => {
  // "2026-05-25T23:59:59" has no offset. Parsed as local time in, say,
  // America/Los_Angeles, that instant falls on May 26 in UTC — so naively
  // formatting `new Date(iso)` with timeZone: "UTC" would print "May 26"
  // there while printing "May 25" in UTC/Asia-Seoul. The deadline is a
  // published calendar date, not an instant, so the text must not depend on
  // where the browser happens to be.
  const result = formatDeadline(edition(2026, "2026-10-24", "2026-10-29", "2026-05-25T23:59:59"), NOW);
  assert.equal(result.text, "May 25, 2026");
});

test("compareBy date sorts nearest first and pushes past editions down", () => {
  const upcoming = conf({ abbr: "A", editions: [edition(2026, "2026-10-24", "2026-10-29", null)] });
  const past = conf({ abbr: "B", editions: [edition(2026, "2026-01-05", "2026-01-09", null)] });
  const sorted = [past, upcoming].sort(compareBy("date", "asc", NOW));
  assert.deepEqual(sorted.map((c) => c.abbr), ["A", "B"]);
});

test("isEnded is true when the displayed edition already ended", () => {
  const past = conf({ abbr: "A", editions: [edition(2026, "2026-01-05", "2026-01-09", null)] });
  assert.equal(isEnded(past, NOW), true);
});

test("isEnded is false when there is an upcoming edition", () => {
  const upcoming = conf({ abbr: "A", editions: [edition(2026, "2026-10-24", "2026-10-29", null)] });
  assert.equal(isEnded(upcoming, NOW), false);
});

test("isEnded is false when no edition has dates", () => {
  const undated = conf({
    abbr: "A",
    editions: [{ year: 2026, date_text: null, start: null, end: null, place: null, link: null, deadlines: [], primary_deadline: null, source: "ccfddl" }],
  });
  assert.equal(isEnded(undated, NOW), false);
});

test("isEnded is false when the edition ends exactly today", () => {
  const endsToday = conf({ abbr: "A", editions: [edition(2026, "2026-09-04", "2026-09-08", null)] });
  assert.equal(isEnded(endsToday, NOW), false);
});

test("compareBy grade ranks 최우수 above 우수", () => {
  const top = conf({ abbr: "A", grade: "최우수" });
  const good = conf({ abbr: "B", grade: "우수" });
  const sorted = [good, top].sort(compareBy("grade", "asc", NOW));
  assert.deepEqual(sorted.map((c) => c.abbr), ["A", "B"]);
});

test("compareBy grade breaks ties within a company grade using BK: S before A before -", () => {
  const a = conf({ abbr: "A", grade: "최우수", bk_grade: "A" });
  const s = conf({ abbr: "S", grade: "최우수", bk_grade: "S" });
  const dash = conf({ abbr: "D", grade: "최우수", bk_grade: null });
  const sorted = [dash, a, s].sort(compareBy("grade", "asc", NOW));
  assert.deepEqual(sorted.map((c) => c.abbr), ["S", "A", "D"]);
});

test("compareBy grade keeps company grade as the primary key even with BK ties", () => {
  // 우수(S)는 BK 등급이 최우수(A)보다 높아도 회사 등급이 낮으므로 뒤에 와야 한다.
  const goodS = conf({ abbr: "GS", grade: "우수", bk_grade: "S" });
  const topA = conf({ abbr: "TA", grade: "최우수", bk_grade: "A" });
  const sorted = [goodS, topA].sort(compareBy("grade", "asc", NOW));
  assert.deepEqual(sorted.map((c) => c.abbr), ["TA", "GS"]);
});

test("bkGradeLabel shows the BK grade, or - when the conference is not in the BK list", () => {
  assert.equal(bkGradeLabel(conf({ bk_grade: "S" })), "S");
  assert.equal(bkGradeLabel(conf({ bk_grade: "A" })), "A");
  assert.equal(bkGradeLabel(conf({ bk_grade: null })), "-");
});

test("gradeCellText renders company grade with BK grade in parentheses", () => {
  assert.equal(gradeCellText(conf({ grade: "최우수", bk_grade: "S" })), "최우수(S)");
  assert.equal(gradeCellText(conf({ grade: "최우수", bk_grade: "A" })), "최우수(A)");
  assert.equal(gradeCellText(conf({ grade: "우수", bk_grade: "S" })), "우수(S)");
  assert.equal(gradeCellText(conf({ grade: "우수", bk_grade: "A" })), "우수(A)");
  assert.equal(gradeCellText(conf({ grade: "우수", bk_grade: null })), "우수(-)");
});

// BK 배지의 색 클래스는 app.js가 직접 고르지 않고 여기서 가져다 쓴다 - 지난
// 버전은 배지 안 글자색이 배경과 같은 값이 되는 실수가 테스트 없이 그대로
// 배포됐었다. 세 상태(S/A/미등재)가 각각 다른 클래스로, 그리고 미등재가
// 등재된 값과 반드시 다른 클래스로 떨어지는지를 여기서 고정해 둔다.
test("bkGradeBadgeClass maps S/A to the shared gold/silver classes", () => {
  assert.equal(bkGradeBadgeClass(conf({ bk_grade: "S" })), "grade-s");
  assert.equal(bkGradeBadgeClass(conf({ bk_grade: "A" })), "grade-a");
});

test("bkGradeBadgeClass renders the not-listed case distinctly from a graded one", () => {
  const notListed = bkGradeBadgeClass(conf({ bk_grade: null }));
  assert.equal(notListed, "grade-none");
  assert.notEqual(notListed, bkGradeBadgeClass(conf({ bk_grade: "S" })));
  assert.notEqual(notListed, bkGradeBadgeClass(conf({ bk_grade: "A" })));
});

test("matchesFilters passes everything when no filter is set", () => {
  const filters = { fields: new Set(), grades: new Set(), aiOnly: false, hidePast: false, query: "" };
  assert.equal(matchesFilters(conf(), filters, NOW), true);
});

test("matchesFilters restricts by field", () => {
  const filters = { fields: new Set(["CV"]), grades: new Set(), aiOnly: false, hidePast: false, query: "" };
  assert.equal(matchesFilters(conf(), filters, NOW), false);
});

test("matchesFilters searches abbreviation and full name case-insensitively", () => {
  const base = { fields: new Set(), grades: new Set(), aiOnly: false, hidePast: false };
  assert.equal(matchesFilters(conf(), { ...base, query: "emnlp" }, NOW), true);
  assert.equal(matchesFilters(conf(), { ...base, query: "empirical" }, NOW), true);
  assert.equal(matchesFilters(conf(), { ...base, query: "siggraph" }, NOW), false);
});

test("matchesFilters hidePast drops conferences whose deadline has passed", () => {
  const filters = { fields: new Set(), grades: new Set(), aiOnly: false, hidePast: true, query: "" };
  assert.equal(matchesFilters(conf(), filters, NOW), false);
});

test("matchesFilters hidePast follows nextDeadline, not primary_deadline, when they diverge", () => {
  // hidePast는 셀에 뜨는 값과 같은 근거(nextDeadline)로 판단해야 한다.
  // 여기서는 제출 계열이 하나도 없고 통보/카메라레디만 있는 회차를 쓴다 -
  // 셀은 미정으로 뜨는데(nextDeadline이 null), primary_deadline은 그 통보
  // 날짜를 갖고 있어 아직 미래처럼 보인다. primary_deadline을 기준으로
  // 판단하면 화면엔 미정이라 써 있는 학회가 "곧 마감"인 척 필터를 통과한다.
  const adminOnly = conf({
    editions: [{
      year: 2027,
      date_text: "2027",
      start: "2027-07-01",
      end: "2027-07-05",
      place: "Somewhere",
      link: null,
      deadlines: [
        { type: "notification", label: "Notification", date: "2026-12-01T23:59:59", source: "ccfddl" },
      ],
      primary_deadline: "2026-12-01T23:59:59",
      source: "ccfddl",
    }],
  });
  const filters = { fields: new Set(), grades: new Set(), aiOnly: false, hidePast: true, query: "" };
  assert.equal(matchesFilters(adminOnly, filters, NOW), false);
});

test("본 논문 마감이 지나도 남은 포스터가 있으면 그것을 보여준다", () => {
  // CHI 2027이 실제로 이 모양이다 - 본 논문 9/10, 포스터 이듬해 1/21.
  // 본 논문만 후보로 보면 9/11부터 "마감됨"으로 뜨지만 아직 낼 곳이 남아 있다.
  const chiLike = {
    year: 2027,
    date_text: "2027",
    start: "2027-05-10",
    end: "2027-05-14",
    place: "Somewhere",
    link: null,
    deadlines: [
      { type: "paper", label: "Full Paper Due", date: "2026-09-10T23:59:59", source: "ccfddl" },
      { type: "workshop", label: "Workshops", date: "2026-10-01T23:59:59", source: "cfp-scrape" },
      { type: "poster", label: "Posters", date: "2027-01-21T23:59:59", source: "cfp-scrape" },
    ],
    primary_deadline: "2026-09-10T23:59:59",
    source: "ccfddl",
  };
  assert.equal(nextDeadline(chiLike, new Date(2026, 8, 9)).type, "paper");
  // 본 논문 다음은 포스터다. 그 사이의 workshop 제안 마감은 워크숍을 열려는
  // 조직위의 마감이지 논문을 내는 사람의 마감이 아니라 건너뛴다.
  const afterPaper = nextDeadline(chiLike, new Date(2026, 8, 11));
  assert.equal(afterPaper.type, "poster");
  assert.equal(afterPaper.label, "Posters");
  // 전부 지나면 본 논문 마감으로 되돌아가 "마감됨"으로 보인다
  assert.equal(nextDeadline(chiLike, new Date(2027, 5, 1)).type, "paper");
  assert.equal(formatDeadline(chiLike, new Date(2027, 5, 1)).state, "past");
});

test("abstract가 본 논문보다 앞서면 abstract를 먼저 보여준다", () => {
  // 대부분의 학회가 초록을 먼저 등록해야 본문을 낼 수 있게 한다. 초록을
  // 놓치면 본문을 아예 못 내므로 실질적인 다음 마감은 초록 쪽이다.
  const withAbstract = {
    year: 2027,
    date_text: "2027",
    start: "2027-04-01",
    end: "2027-04-05",
    place: "Somewhere",
    link: null,
    deadlines: [
      { type: "abstract", label: "Abstract Submission", date: "2026-09-18T23:59:59", source: "ai-deadlines" },
      { type: "paper", label: "Paper Submission", date: "2026-09-25T23:59:59", source: "ai-deadlines" },
    ],
    primary_deadline: "2026-09-25T23:59:59",
    source: "ai-deadlines",
  };
  const before = nextDeadline(withAbstract, new Date(2026, 8, 10));
  assert.equal(before.type, "abstract");
  assert.equal(before.label, "Abstract Submission");
  // 초록이 지나면 본 논문으로 넘어간다
  assert.equal(nextDeadline(withAbstract, new Date(2026, 8, 19)).type, "paper");
});

test("워크숍 제안 마감은 건너뛰고 채택 발표일을 보여준다", () => {
  // workshop 제안은 워크숍을 열려는 조직위가 내는 것이라 참가자의 마감이
  // 아니다. 대신 어떤 워크숍이 채택됐는지 알려주는 notification이 의미 있다.
  const eccvLike = {
    year: 2027,
    date_text: "2027",
    start: "2027-09-08",
    end: "2027-09-13",
    place: "Somewhere",
    link: null,
    deadlines: [
      { type: "paper", label: "Paper Submission", date: "2026-03-05T23:59:59", source: "ai-deadlines" },
      { type: "submission", label: "Workshop Proposal Submission", date: "2026-02-27T23:59:59", source: "ai-deadlines" },
      { type: "notification", label: "Tutorial/Workshop Decisions", date: "2026-12-12T23:59:59", source: "ai-deadlines" },
    ],
    primary_deadline: "2026-03-05T23:59:59",
    source: "ai-deadlines",
  };
  const chosen = nextDeadline(eccvLike, new Date(2026, 8, 10));
  assert.equal(chosen.type, "notification");
  assert.equal(chosen.label, "Tutorial/Workshop Decisions");
});


test("matchesFilters aiOnly keeps only AI Specialist conferences", () => {
  const filters = { fields: new Set(), grades: new Set(), aiOnly: true, hidePast: false, query: "" };
  assert.equal(matchesFilters(conf({ ai_specialist: false }), filters, NOW), false);
});

// --- nextDeadline: rolling-deadline (다회차) 학회의 대표 마감 선택 ---
//
// UbiComp처럼 연 4회 라운드가 있는 학회는 build가 계산한 primary_deadline이
// "가장 늦은 라운드"라 학회가 끝난 뒤 날짜가 뜬다. 브라우저는 아직 지나지
// 않은 것 중 가장 이른 라운드를 대표로 보여줘야 한다.

const rollingEdition = (rounds, primary) => ({
  year: 2026,
  date_text: "2026-10-11 ~ 2026-10-15",
  start: "2026-10-11",
  end: "2026-10-15",
  place: "Somewhere",
  link: null,
  deadlines: rounds,
  primary_deadline: primary,
  source: "ccfddl",
});

const UBICOMP_ROUNDS = [
  { type: "paper", label: "first round", date: "2026-02-01T23:59:59", source: "ccfddl" },
  { type: "paper", label: "second round", date: "2026-05-01T23:59:59", source: "ccfddl" },
  { type: "paper", label: "third round", date: "2026-08-01T23:59:59", source: "ccfddl" },
  { type: "paper", label: "fourth round", date: "2026-11-01T23:59:59", source: "ccfddl" },
];

test("nextDeadline picks the earliest future round, not the latest", () => {
  // Between the second and third rounds: first/second have passed, third and
  // fourth have not. The earliest future one (third) must win, not the last
  // (fourth) — a naive "just take the last entry" implementation would also
  // return the fourth round here by coincidence unless two rounds are still
  // ahead, which is why this NOW is chosen deliberately.
  const midYear = new Date(2026, 5, 1);
  const result = nextDeadline(rollingEdition(UBICOMP_ROUNDS, "2026-11-01T23:59:59"), midYear);
  assert.equal(result.label, "third round");
  assert.equal(result.date, "2026-08-01T23:59:59");
});

test("nextDeadline falls back to the last round when every round has passed", () => {
  const laterNow = new Date(2026, 11, 1);
  const result = nextDeadline(rollingEdition(UBICOMP_ROUNDS, "2026-11-01T23:59:59"), laterNow);
  assert.equal(result.label, "fourth round");
  assert.equal(result.date, "2026-11-01T23:59:59");
});

test("nextDeadline with an empty deadlines array falls back to primary_deadline", () => {
  const ed = { ...rollingEdition([], null), primary_deadline: "2026-12-01T23:59:59" };
  const result = nextDeadline(ed, NOW);
  assert.equal(result.date, "2026-12-01T23:59:59");
});

test("nextDeadline returns null when there is neither deadlines nor primary_deadline", () => {
  assert.equal(nextDeadline(rollingEdition([], null), NOW), null);
});

test("formatDeadline label matches the chosen rolling-deadline round", () => {
  const result = formatDeadline(rollingEdition(UBICOMP_ROUNDS, "2026-11-01T23:59:59"), NOW);
  assert.equal(result.state, "upcoming");
  assert.equal(result.label, "fourth round");
});

test("compareBy deadline sorts by the next unresolved round, not primary_deadline", () => {
  // At NOW itself only the last UbiComp round is still future, so its next
  // round and its primary_deadline (the latest round) are the same date —
  // a fixture built around NOW couldn't tell a correct implementation from
  // one that reads primary_deadline directly (this is exactly how the first
  // version of this test failed to discriminate). Use midYear instead: two
  // rounds (third, fourth) are still ahead, so "next round" (Aug 1) and
  // "primary_deadline" (Nov 1, the latest round) genuinely disagree.
  //
  // UBICOMP's next round is Aug 1 (before SOON's Sep 20 deadline) — correct
  // sorting by next round puts UBICOMP first. Sorting by primary_deadline
  // instead would compare Nov 1 against Sep 20 and put SOON first — the
  // opposite order — so this fixture fails under the old behavior.
  const midYear = new Date(2026, 5, 1);
  const rolling = conf({
    abbr: "UBICOMP",
    editions: [rollingEdition(UBICOMP_ROUNDS, "2026-11-01T23:59:59")],
  });
  const soon = conf({
    abbr: "SOON",
    editions: [edition(2026, "2026-12-01", "2026-12-05", "2026-09-20T23:59:59")],
  });
  const sorted = [soon, rolling].sort(compareBy("deadline", "asc", midYear));
  assert.deepEqual(sorted.map((c) => c.abbr), ["UBICOMP", "SOON"]);
});

// --- nextDeadline must ignore non-paper deadline types ---
//
// 실제 데이터에는 WACV/SIGGRAPH/ECCV처럼 논문 마감 외에도 등록(registration),
// 리뷰공개(review_release), 통보(notification), camera-ready 같은 타입이
// 같은 deadlines 배열에 섞여 있다. 날짜순으로 "아직 지나지 않은 것"만 고르면
// 이런 행정 일정이 논문 마감보다 먼저 뽑혀 나올 수 있다. build가 primary_deadline을
// 계산할 때 쓰는 것과 같은 타입 집합(paper, submission)만 후보로 삼아야 한다.

const wacvLikeEdition = () => ({
  year: 2026,
  date_text: "2026-01-01 ~ 2026-01-05",
  start: "2026-01-01",
  end: "2026-01-05",
  place: "Somewhere",
  link: null,
  deadlines: [
    { type: "registration", label: "Round 1 Registration", date: "2025-07-11T23:59:59", source: "ccfddl" },
    { type: "submission", label: "Round 1 Submission", date: "2025-07-18T23:59:59", source: "ccfddl" },
    { type: "review_release", label: "Round 1 Reviews Released", date: "2025-09-05T23:59:59", source: "ccfddl" },
    { type: "submission", label: "Round 2 Submission", date: "2025-09-19T23:59:59", source: "ccfddl" },
    { type: "notification", label: "Round 2 Decisions", date: "2026-10-09T23:59:59", source: "ccfddl" },
    { type: "camera_ready", label: "Camera Ready", date: "2026-11-02T23:59:59", source: "ccfddl" },
  ],
  primary_deadline: "2025-09-19T23:59:59",
  source: "ccfddl",
});

test("nextDeadline ignores non-paper types like notification and camera_ready", () => {
  // NOW = 2026-09-08: both submission rounds have passed. The next chronological
  // entry in the raw array is "Round 2 Decisions" (notification), which must NOT
  // be picked — it isn't a paper deadline. Correct behavior falls back to the
  // last paper/submission-type entry, Round 2 Submission.
  const result = nextDeadline(wacvLikeEdition(), NOW);
  assert.equal(result.type, "submission");
  assert.equal(result.label, "Round 2 Submission");
});

// --- nextDeadline must prefer "paper" over an unrelated "submission" ---
//
// ECCV's real deadlines array uses "submission" for tracks that have nothing
// to do with the main paper deadline: Tutorial Proposal Submission, Workshop
// Proposal Submission, and — dated well after the actual paper deadline — AI
// Art Submission. A flat PAPER_TYPES set of {paper, submission} lets that
// later, unrelated AI Art date outrank the real "Paper Submission" (type
// "paper"). When any "paper"-typed deadline exists, "submission"-typed ones
// must not be considered at all.

const eccvLikeEdition = () => ({
  year: 2026,
  date_text: "2026-06-01 ~ 2026-06-05",
  start: "2026-06-01",
  end: "2026-06-05",
  place: "Somewhere",
  link: null,
  deadlines: [
    { type: "submission", label: "Tutorial Proposal Submission", date: "2026-02-15T23:59:59", source: "ccfddl" },
    { type: "submission", label: "Workshop Proposal Submission", date: "2026-02-27T23:59:59", source: "ccfddl" },
    { type: "paper", label: "Paper Submission", date: "2026-03-05T22:00:00", source: "ccfddl" },
    { type: "submission", label: "AI Art Submission", date: "2026-06-14T23:59:59", source: "ccfddl" },
  ],
  primary_deadline: "2026-03-05T22:00:00",
  source: "ccfddl",
});

test("nextDeadline prefers paper over a later, unrelated submission-typed entry", () => {
  // NOW = 2026-09-08: everything above has passed, including the Jun 14 AI
  // Art Submission. A flat type set would fall back to the latest entry
  // overall (AI Art Submission); tiering by paper-first must fall back to
  // the latest *paper*-typed entry instead (there's only one: Paper Submission).
  const result = nextDeadline(eccvLikeEdition(), NOW);
  assert.equal(result.type, "paper");
  assert.equal(result.label, "Paper Submission");
});

test("formatDeadline shows ECCV's Paper Submission, not the later AI Art Submission", () => {
  const result = formatDeadline(eccvLikeEdition(), NOW);
  assert.equal(result.label, "Paper Submission");
});

// --- allDeadlines: 토글에 보여줄 전체 일정 ---
//
// 예전 이름 extraDeadlines는 셀에 뜨는 항목(nextDeadline의 선택)을 뺐다.
// 하지만 그게 펼친 목록에서 가장 중요한 항목(본 마감)이 통째로 사라지는
// 결과였다(ECCV 12개 중 11개, UbiComp 4개 중 3개, WACV 11개 중 10개만
// 보이던 문제). allDeadlines는 아무것도 빼지 않고 시간순으로 전부 돌려주고,
// 어느 것이 대표인지는 isFeaturedDeadline이 참조 동일성으로 따로 표시한다.

const multiStage = {
  year: 2026,
  date_text: "June 3-7, 2026",
  start: "2026-06-03",
  end: "2026-06-07",
  place: "Denver USA",
  link: null,
  primary_deadline: "2025-11-13T23:59:59",
  source: "ai-deadlines",
  deadlines: [
    { type: "abstract", label: "Abstract", date: "2025-11-07T23:59:59", source: "ai-deadlines" },
    { type: "paper", label: "Paper", date: "2025-11-13T23:59:59", source: "ai-deadlines" },
    { type: "notification", label: "Decisions", date: "2026-02-20T23:59:59", source: "ai-deadlines" },
    {
      type: "poster", label: "Posters", date: "2026-04-21T22:00:00", source: "cfp-scrape",
      evidence: { raw_text: "Posters deadline: April 21, 2026", url: "https://x/" },
    },
  ],
};

test("allDeadlines includes the stage the cell shows too — nothing is dropped", () => {
  const types = allDeadlines(multiStage).map((d) => d.type);
  assert.deepEqual(types, ["abstract", "paper", "notification", "poster"]);
});

test("allDeadlines sorts chronologically", () => {
  const dates = allDeadlines(multiStage).map((d) => d.date);
  assert.deepEqual(dates, [...dates].sort());
});

test("allDeadlines returns the single stage as-is when only one deadline exists", () => {
  // 마감이 하나뿐이면 목록도 그 하나뿐이다(빈 배열이 아니다) - 토글을 달지
  // 말지는 호출하는 쪽(app.js)이 길이로 판단한다.
  const single = { ...multiStage, deadlines: [multiStage.deadlines[1]] };
  assert.deepEqual(allDeadlines(single).map((d) => d.type), ["paper"]);
});

test("allDeadlines handles an edition with no deadlines", () => {
  assert.deepEqual(allDeadlines({ deadlines: [], primary_deadline: null }), []);
  assert.deepEqual(allDeadlines(null), []);
});

// --- isFeaturedDeadline: 어느 단계가 셀과 같은 대표 마감인지 ---

test("isFeaturedDeadline marks by identity, not by date — a shared date does not mark two stages", () => {
  // 날짜값으로 비교하면 같은 시각에 걸린 두 단계가 둘 다 '대표'로 잘못
  // 표시될 수 있다. nextDeadline은 특정 객체 하나(여기선 "paper" 항목)를
  // 고르므로, 그 객체만 current여야 한다.
  const sharedDate = "2025-11-13T23:59:59";
  const sharedDateEdition = {
    year: 2026,
    date_text: "June 3-7, 2026",
    start: "2026-06-03",
    end: "2026-06-07",
    place: "Denver USA",
    link: null,
    primary_deadline: sharedDate,
    source: "ai-deadlines",
    deadlines: [
      { type: "paper", label: "Paper", date: sharedDate, source: "ai-deadlines" },
      { type: "abstract", label: "Also due", date: sharedDate, source: "ai-deadlines" },
    ],
  };
  const flags = allDeadlines(sharedDateEdition).map(
    (d) => [d.type, isFeaturedDeadline(d, sharedDateEdition, NOW)]
  );
  assert.deepEqual(flags, [["paper", true], ["abstract", false]]);
});

// --- nextDeadline must not synthesize a featured deadline out of thin air
// when deadlines exist but none is paper/submission typed ---
//
// The empty-deadlines fallback (primary_deadline only, no deadlines array)
// synthesizes a { type: "paper", ... } object that isn't a member of
// edition.deadlines — harmless there, since allDeadlines has nothing to list
// in that case (edition.deadlines is empty). But if deadlines is non-empty
// and simply has no paper/submission entry (e.g. only notification/
// camera_ready survived, which is what an LLM-extracted CFP could plausibly
// produce), isFeaturedDeadline must not somehow match one of them to that
// synthesized object — none of them is "featured".

const noPaperTypeEdition = () => ({
  year: 2026,
  date_text: "2026-05-01 ~ 2026-06-05",
  start: "2026-05-01",
  end: "2026-06-05",
  place: "Somewhere",
  link: null,
  deadlines: [
    { type: "notification", label: "Decisions", date: "2026-05-01T23:59:59", source: "cfp-scrape" },
    { type: "camera_ready", label: "Camera Ready", date: "2026-06-01T23:59:59", source: "cfp-scrape" },
  ],
  primary_deadline: "2026-05-01T23:59:59",
  source: "cfp-scrape",
});

test("nextDeadline returns null when deadlines exist but none is paper/submission typed", () => {
  assert.equal(nextDeadline(noPaperTypeEdition(), NOW), null);
});

test("allDeadlines shows every stage without duplication when nextDeadline finds no featured deadline", () => {
  const types = allDeadlines(noPaperTypeEdition()).map((d) => d.type);
  assert.deepEqual(types, ["notification", "camera_ready"]);
});

test("isFeaturedDeadline marks nothing as current when nextDeadline finds no featured deadline", () => {
  const edition = noPaperTypeEdition();
  const flags = allDeadlines(edition).map((d) => isFeaturedDeadline(d, edition, NOW));
  assert.deepEqual(flags, [false, false]);
});

test("AoE 마감은 KST로 옮겨 하루 뒤로 보인다", () => {
  // AoE(UTC-12) 9월 18일 23:59는 KST로 9월 19일 20:59다. 한국에서 실제로
  // 낼 수 있는 시각이 하루 뒤이므로, AoE 날짜를 그대로 띄우면 없는 마감
  // 압박을 만든다.
  const aoeEdition = {
    year: 2027,
    date_text: "2027",
    start: "2027-04-01",
    end: "2027-04-05",
    place: "Somewhere",
    link: null,
    deadlines: [
      { type: "paper", label: "Paper", date: "2026-09-18T23:59:59", timezone: "AoE", source: "ai-deadlines" },
    ],
    primary_deadline: "2026-09-18T23:59:59",
    source: "ai-deadlines",
  };
  const result = formatDeadline(aoeEdition, new Date(2026, 8, 10));
  assert.equal(result.text, "Sep 19, 2026");
  assert.equal(result.dday, "D-9");
  assert.equal(result.aoe, true);
});

test("AoE가 아닌 마감은 원래 날짜 그대로 보인다", () => {
  // PST나 UTC 표기는 AoE와 달라서 하루를 더해선 안 된다.
  const pstEdition = {
    year: 2027,
    date_text: "2027",
    start: "2027-04-01",
    end: "2027-04-05",
    place: "Somewhere",
    link: null,
    deadlines: [
      { type: "paper", label: "Paper", date: "2026-09-15T23:59:59", timezone: "PST", source: "ai-deadlines" },
    ],
    primary_deadline: "2026-09-15T23:59:59",
    source: "ai-deadlines",
  };
  const result = formatDeadline(pstEdition, new Date(2026, 8, 10));
  assert.equal(result.text, "Sep 15, 2026");
  assert.equal(result.aoe, false);
});

test("UTC-12 표기도 AoE와 같은 시각이므로 함께 환산한다", () => {
  assert.equal(isAoeDeadline({ timezone: "UTC-12" }), true);
  assert.equal(isAoeDeadline({ timezone: "AoE" }), true);
  assert.equal(isAoeDeadline({ timezone: "UTC" }), false);
  assert.equal(isAoeDeadline({}), false);
  // AoE 자정 마감은 KST로 같은 날 21:00이라 날짜가 안 밀린다
  assert.equal(toKst("2026-09-18T00:00:00").toISOString().slice(0, 10), "2026-09-18");
  assert.equal(toKst("2026-09-18T23:59:59").toISOString().slice(0, 10), "2026-09-19");
});

test("matchesFilters BK 등급으로 거른다", () => {
  const base = { fields: new Set(), grades: new Set(), aiOnly: false, hidePast: false, query: "" };
  const sConf = conf({ grade: "우수", bk_grade: "S" });
  const aConf = conf({ grade: "최우수", bk_grade: "A" });
  const noneConf = conf({ grade: "우수", bk_grade: null });

  assert.equal(matchesFilters(sConf, { ...base, bkGrades: new Set(["S"]) }, NOW), true);
  assert.equal(matchesFilters(aConf, { ...base, bkGrades: new Set(["S"]) }, NOW), false);
  // BK 목록에 없는 학회는 '-'로 거른다 - null과 '-'를 같은 값으로 다뤄야
  // "BK 미등재만 보기"가 성립한다.
  assert.equal(matchesFilters(noneConf, { ...base, bkGrades: new Set(["-"]) }, NOW), true);
  assert.equal(matchesFilters(sConf, { ...base, bkGrades: new Set(["-"]) }, NOW), false);
  // 빈 Set은 '전체'
  assert.equal(matchesFilters(aConf, { ...base, bkGrades: new Set() }, NOW), true);
});

test("matchesFilters SR과 BK 필터를 함께 걸면 교집합이다", () => {
  // 두 기준이 갈리는 학회를 골라내는 용도다 - SR 우수 + BK S를 고르면
  // 회사 기준으로는 우수인데 BK는 최우수로 보는 학회만 남는다.
  const base = { fields: new Set(), aiOnly: false, hidePast: false, query: "" };
  const split = conf({ grade: "우수", bk_grade: "S" });
  const agree = conf({ grade: "최우수", bk_grade: "S" });
  const filters = { ...base, grades: new Set(["우수"]), bkGrades: new Set(["S"]) };

  assert.equal(matchesFilters(split, filters, NOW), true);
  assert.equal(matchesFilters(agree, filters, NOW), false);
});

test("matchesFilters bkGrades가 없어도 동작한다", () => {
  // 저장된 옛 필터 상태에는 bkGrades 키가 없을 수 있다.
  const filters = { fields: new Set(), grades: new Set(), aiOnly: false, hidePast: false, query: "" };
  assert.equal(matchesFilters(conf({ bk_grade: "S" }), filters, NOW), true);
});

test("SR 목록에 없는 학회는 '-' 배지가 된다", () => {
  // EACL/CSCW는 BK 목록에만 있어 grade가 빈 문자열이다. 그대로 배지에 넣으면
  // 글자 없는 은색 배지가 떠서 "우수"처럼 보인다 - BK 쪽과 똑같이 "-"로 세운다.
  const bkOnly = conf({ grade: "", bk_grade: "A" });
  assert.equal(srGradeLabel(bkOnly), "-");
  assert.equal(srGradeBadgeClass(bkOnly), "grade-none");
  assert.equal(gradeCellText(bkOnly), "-(A)");

  assert.equal(srGradeBadgeClass(conf({ grade: "최우수" })), "top");
  assert.equal(srGradeBadgeClass(conf({ grade: "우수" })), "good");
  assert.equal(gradeCellText(conf({ grade: "최우수", bk_grade: "S" })), "최우수(S)");
});

test("SR 미등재를 필터로 고를 수 있다", () => {
  const base = { fields: new Set(), bkGrades: new Set(), aiOnly: false, hidePast: false, query: "" };
  const bkOnly = conf({ grade: "", bk_grade: "A" });
  const graded = conf({ grade: "우수", bk_grade: "A" });

  assert.equal(matchesFilters(bkOnly, { ...base, grades: new Set(["-"]) }, NOW), true);
  assert.equal(matchesFilters(graded, { ...base, grades: new Set(["-"]) }, NOW), false);
  // 등급 있는 학회를 고르면 미등재는 빠진다
  assert.equal(matchesFilters(bkOnly, { ...base, grades: new Set(["우수"]) }, NOW), false);
});

test("formatStage: 시간 없는 날짜가 뷰어 시간대에 밀리지 않는다", () => {
  // 예전 펼침 목록은 new Date(stage.date)로 곧바로 파싱했다. 오프셋 없는
  // "2027-02-16T00:00:00"은 로컬로 읽힌 뒤 UTC로 표시되어, KST(UTC+9)
  // 뷰어에게는 Feb 15로 하루 당겨져 보였다.
  const stage = { type: "notification", label: "Workshop Acceptance Notification",
    date: "2027-02-16T00:00:00", source: "manual" };
  assert.equal(formatStage(stage, new Date(2026, 8, 11)).text, "Feb 16, 2027");
});

test("formatStage: AoE 환산이 대표 마감과 펼침에서 같다", () => {
  // 같은 마감이 칸에서는 Jan 12, 펼침에서는 Jan 11로 보이던 어긋남을 막는다.
  const aoeStage = { type: "abstract", label: "Title and Abstract",
    date: "2027-01-11T23:59:59", timezone: "AoE", source: "manual" };
  const now = new Date(2026, 8, 11);
  const stageInfo = formatStage(aoeStage, now);

  // abstract만 있는 회차는 대표 마감이 '미정'이다 - abstract는 아직 열려 있는
  // 본 논문 마감이 있을 때만 그보다 먼저 보여주는 값이기 때문. 실제 DIS처럼
  // paper를 함께 둬야 abstract가 대표로 올라온다.
  const paperStage = { type: "paper", label: "Paper and Pictorial Submission",
    date: "2027-01-18T23:59:59", timezone: "AoE", source: "manual" };
  const edition = { year: 2027, date_text: "2027", start: "2027-06-28", end: "2027-07-02",
    place: "Stockholm, Sweden", link: null, deadlines: [aoeStage, paperStage],
    primary_deadline: paperStage.date, source: "manual" };
  const cellInfo = formatDeadline(edition, now);

  assert.equal(stageInfo.text, "Jan 12, 2027");
  assert.equal(stageInfo.text, cellInfo.text);
  assert.equal(stageInfo.dday, cellInfo.dday);
  assert.equal(stageInfo.aoe, true);
});

test("formatStage: AoE가 아니면 날짜를 그대로 둔다", () => {
  const stage = { type: "paper", label: "Paper", date: "2027-01-18T23:59:59",
    timezone: "PST", source: "manual" };
  assert.equal(formatStage(stage, new Date(2026, 8, 11)).text, "Jan 18, 2027");
});

const estimatedEdition = (year, month) => ({
  year, date_text: "", start: null, end: null, place: "", link: null,
  deadlines: [], primary_deadline: null, source: "estimated", estimated_month: month,
});

test("formatDateRange: 추정 회차는 월과 (미정)으로 보여준다", () => {
  assert.equal(formatDateRange(estimatedEdition(2027, 7)), "July, 2027 (미정)");
  assert.equal(formatDateRange(estimatedEdition(2027, 5)), "May, 2027 (미정)");
  // 확정 일정이 있으면 추정은 끼어들지 않는다.
  assert.equal(
    formatDateRange({ ...estimatedEdition(2027, 7), date_text: "July 6-11, 2027" }),
    "July 6-11, 2027",
  );
});

test("pickEdition: 지난 회차보다 추정 회차를 고른다", () => {
  // 이게 없으면 끝난 회차가 계속 대표로 뽑혀 행이 회색으로 남는다.
  const past = { year: 2026, date_text: "July 6-11, 2026", start: "2026-07-06",
    end: "2026-07-11", place: "Seoul", link: null, deadlines: [],
    primary_deadline: null, source: "ai-deadlines" };
  const picked = pickEdition([past, estimatedEdition(2027, 7)], new Date(2026, 8, 14));
  assert.equal(picked.year, 2027);
  assert.equal(picked.source, "estimated");
});

test("pickEdition: 확정된 차기 회차가 추정보다 우선한다", () => {
  const confirmed = { year: 2027, date_text: "March 1-5, 2027", start: "2027-03-01",
    end: "2027-03-05", place: "Seoul", link: null, deadlines: [],
    primary_deadline: null, source: "ccfddl" };
  // 추정(7월)이 확정(3월)보다 늦으므로 날짜순으로도 확정이 앞선다.
  const picked = pickEdition([confirmed, estimatedEdition(2028, 7)], new Date(2026, 8, 14));
  assert.equal(picked.source, "ccfddl");
});

test("추정 회차만 있어도 마감은 '미정'이고 D-day가 없다", () => {
  // 추정에 마감이 붙으면 있지도 않은 D-day가 뜬다.
  const info = formatDeadline(estimatedEdition(2027, 7), new Date(2026, 8, 14));
  assert.equal(info.text, "미정");
  assert.equal(info.dday, "");
});

test("isEnded: 추정 회차가 있으면 회색 처리하지 않는다", () => {
  const conf = {
    abbr: "ICML", field: "ML", grade: "최우수", bk_grade: "S", ai_specialist: true,
    editions: [
      { year: 2026, date_text: "July 6-11, 2026", start: "2026-07-06", end: "2026-07-11",
        place: "Seoul", link: null, deadlines: [], primary_deadline: null, source: "ai-deadlines" },
      estimatedEdition(2027, 7),
    ],
  };
  assert.equal(isEnded(conf, new Date(2026, 8, 14)), false);
});

test("정렬: 추정 회차는 그 달 기준으로 줄 선다", () => {
  // 맨 뒤로 밀면 "July, 2027"이라고 써 놓고 그보다 늦은 12월 학회 아래에
  // 놓이는 모순이 생긴다. 추정(2027-07)이 확정(2027-12)보다 앞서고,
  // 확정(2026-12)보다는 뒤여야 한다 - 셋을 함께 둬야 두 갈래가 갈린다.
  const dated = (abbr, start, end) => ({ abbr, editions: [
    { year: Number(start.slice(0, 4)), date_text: start, start, end, place: "어딘가",
      link: null, deadlines: [], primary_deadline: null, source: "ccfddl" },
  ] });
  const withEstimate = { abbr: "ICML", editions: [estimatedEdition(2027, 7)] };
  const now = new Date(2026, 8, 14);
  const sorted = [
    dated("LATER", "2027-12-01", "2027-12-05"),
    withEstimate,
    dated("EARLIER", "2026-12-13", "2026-12-16"),
  ].sort(compareBy("date", "asc", now));
  assert.deepEqual(sorted.map((c) => c.abbr), ["EARLIER", "ICML", "LATER"]);
});
