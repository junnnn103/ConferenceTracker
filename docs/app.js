import {
  allDeadlines,
  bkGradeBadgeClass,
  bkGradeLabel,
  compareBy,
  formatDateRange,
  formatDeadline,
  formatStage,
  gradeCellText,
  isEnded,
  isFeaturedDeadline,
  matchesFilters,
  pickEdition,
  srGradeBadgeClass,
  srGradeLabel,
} from "./lib.js?v=2957af0b";
import { safeHref } from "./url-safety.js?v=5de46b35";

const STORAGE_KEY = "conference-manager-filters";

const state = {
  data: { conferences: [], fields: [], unresolved: [] },
  sortKey: "date",
  sortDir: "asc",
  filters: {
    fields: new Set(),
    grades: new Set(),
    bkGrades: new Set(),
    aiOnly: false,
    hidePast: false,
    query: "",
  },
  // AI Specialist 배지를 학회명 옆에 띄울지. 행을 거르는 값이 아니라
  // 보여주기만 하는 값이라 filters가 아닌 최상위에 둔다 - matchesFilters에
  // 흘러들면 "필터가 아닌데 필터처럼" 취급되기 때문. 정렬 상태와 같은 급이다.
  showAiBadge: false,
  // 펼침은 일회성이라 URL이나 localStorage에 저장하지 않는다.
  expanded: new Set(),
};

const el = {
  tbody: document.querySelector("#conference-table tbody"),
  fieldFilters: document.querySelector("#field-filters"),
  search: document.querySelector("#search"),
  count: document.querySelector("#count"),
  generatedAt: document.querySelector("#generated-at"),
  unresolved: document.querySelector("#unresolved"),
  unresolvedList: document.querySelector("#unresolved-list"),
  unresolvedCount: document.querySelector("#unresolved-count"),
};

// ---------- 필터 상태의 저장과 복원 ----------
// URL을 우선한다. 링크로 공유된 필터가 내 localStorage에 덮이면 안 되기 때문이다.

function readStateFromUrl() {
  const params = new URLSearchParams(location.search);
  if (!params.toString()) return false;
  state.filters.fields = new Set(params.getAll("field"));
  state.filters.grades = new Set(params.getAll("grade"));
  state.filters.bkGrades = new Set(params.getAll("bk"));
  state.filters.aiOnly = params.get("ai") === "1";
  state.filters.hidePast = params.get("upcoming") === "1";
  state.filters.query = params.get("q") || "";
  state.showAiBadge = params.get("aibadge") === "1";
  state.sortKey = params.get("sort") || "date";
  state.sortDir = params.get("dir") === "desc" ? "desc" : "asc";
  return true;
}

function readStateFromStorage() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (!saved) return;
    state.filters.fields = new Set(saved.fields || []);
    state.filters.grades = new Set(saved.grades || []);
    state.filters.bkGrades = new Set(saved.bkGrades || []);
    state.filters.aiOnly = Boolean(saved.aiOnly);
    state.filters.hidePast = Boolean(saved.hidePast);
    state.filters.query = saved.query || "";
    state.showAiBadge = Boolean(saved.showAiBadge);
    state.sortKey = saved.sortKey || "date";
    state.sortDir = saved.sortDir || "asc";
  } catch {
    // 저장된 값이 깨졌으면 기본값으로 시작한다.
  }
}

function persistState() {
  const params = new URLSearchParams();
  state.filters.fields.forEach((f) => params.append("field", f));
  state.filters.grades.forEach((g) => params.append("grade", g));
  state.filters.bkGrades.forEach((g) => params.append("bk", g));
  if (state.filters.aiOnly) params.set("ai", "1");
  if (state.filters.hidePast) params.set("upcoming", "1");
  if (state.filters.query) params.set("q", state.filters.query);
  if (state.showAiBadge) params.set("aibadge", "1");
  if (state.sortKey !== "date") params.set("sort", state.sortKey);
  if (state.sortDir !== "asc") params.set("dir", state.sortDir);

  const qs = params.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      fields: [...state.filters.fields],
      grades: [...state.filters.grades],
      bkGrades: [...state.filters.bkGrades],
      aiOnly: state.filters.aiOnly,
      hidePast: state.filters.hidePast,
      query: state.filters.query,
      showAiBadge: state.showAiBadge,
      sortKey: state.sortKey,
      sortDir: state.sortDir,
    }));
  } catch {
    // 사파리 프라이빗 모드 등에서 실패할 수 있다. 기능에는 영향이 없다.
  }
}

// ---------- 렌더링 ----------

function fieldColor(id) {
  return state.data.fields.find((f) => f.id === id)?.color || "#64748b";
}

function fieldLabel(id) {
  return state.data.fields.find((f) => f.id === id)?.label || id;
}

function linkCell(conf, edition) {
  const cell = document.createElement("td");
  cell.className = "links-col";

  const home = document.createElement("a");
  home.textContent = "홈";
  home.className = "link-btn";
  home.title = "학회 공식 홈페이지";
  const homeHref = safeHref(conf.homepage, location.href);
  if (homeHref) {
    home.href = homeHref;
    home.target = "_blank";
    home.rel = "noopener noreferrer";
  } else {
    home.classList.add("disabled");
  }
  cell.append(home);

  const cfp = document.createElement("a");
  cfp.textContent = "CFP";
  cfp.className = "link-btn";
  cfp.title = "이 회차의 논문 모집 공고";
  const cfpHref = safeHref(edition?.link, location.href);
  if (cfpHref) {
    cfp.href = cfpHref;
    cfp.target = "_blank";
    cfp.rel = "noopener noreferrer";
  } else {
    cfp.classList.add("disabled");
  }
  cell.append(cfp);
  return cell;
}

// 마감 라벨에서 정보가 없는 단어만 남는지 판단한다. 실제 데이터의 라벨 대부분
// (35개 중 29개)은 "Paper Submission Deadline" 류의 표현일 뿐이고, 그건 마감
// 칸이 이미 말하고 있는 내용이라 그대로 보여주면 캡션이 열 제목을 반복하게
// 된다. "fourth round"나 "Paper submission (short papers)"처럼 라운드/트랙을
// 구분해 주는 라벨만 남기기 위해, 정보가 없는 단어를 지우고 남는 게 있는지로
// 판단한다 — 문자열 전체를 통째로 비교하면 문구가 조금만 달라도(마침표, 어순,
// deadline 유무) 걸러지지 않기 때문이다.
/**
 * 마감 셀에 붙일 라벨.
 *
 * 학회가 자기 사이트에서 쓰는 표현을 그대로 보여준다 - "Paper",
 * "Full Papers", "Posters", "fourth round" 처럼. 한때 본 논문 계열을
 * "본 논문"으로 번역해 통일했지만, 사용자가 이 값을 학회 사이트와 대조하며
 * 확인하므로 원문이 그대로 보이는 편이 낫다.
 *
 * 라벨이 아예 없을 때만 타입에서 만들어 준다 - 어느 마감인지 모르는 채로
 * 날짜만 뜨면 읽는 사람이 매번 추론해야 한다.
 */
function deadlineLabelText(info) {
  const raw = (info.label || "").trim();
  if (raw) return raw;
  const FROM_TYPE = {
    paper: "Paper",
    submission: "Submission",
    poster: "Poster",
    lbw: "Late-Breaking Work",
    workshop: "Workshop",
    demo: "Demo",
    tutorial: "Tutorial",
    doctoral_consortium: "Doctoral Consortium",
  };
  return FROM_TYPE[info.type] || "";
}

function renderRow(conf, now) {
  const edition = pickEdition(conf.editions, now);
  const row = document.createElement("tr");
  row.dataset.abbr = conf.abbr;
  if (isEnded(conf, now)) row.classList.add("ended");

  const nameCell = document.createElement("td");
  nameCell.className = "name-col";
  const homeHref = safeHref(conf.homepage, location.href);
  const name = document.createElement(homeHref ? "a" : "span");
  name.className = "abbr";
  name.textContent = conf.abbr;
  if (homeHref) {
    name.href = homeHref;
    name.target = "_blank";
    name.rel = "noopener noreferrer";
  }
  nameCell.append(name);
  if (conf.ai_specialist && state.showAiBadge) {
    const badge = document.createElement("span");
    badge.className = "badge ai";
    badge.textContent = "AI Specialist";
    nameCell.append(badge);
  }
  const full = document.createElement("div");
  full.className = "full-name";
  full.textContent = conf.full_name;
  nameCell.append(full);
  row.append(nameCell);

  const fieldCell = document.createElement("td");
  const fieldBadge = document.createElement("span");
  fieldBadge.className = "badge field";
  fieldBadge.textContent = fieldLabel(conf.field);
  fieldBadge.style.setProperty("--badge-color", fieldColor(conf.field));
  fieldCell.append(fieldBadge);
  row.append(fieldCell);

  // 등급 칸은 회사 등급(SR)과 BK 등급을 나란한 배지 두 개로 보여준다.
  const gradeCell = document.createElement("td");
  gradeCell.className = "grade-col";
  gradeCell.title = gradeCellText(conf);
  // SR(회사) 배지와 BK(한국정보과학회) 배지를 순서대로 나란히 둔다. 헤더가
  // "등급 (SR/BK)"라 순서로 어느 쪽인지 알 수 있으므로 배지에 라벨을 넣지
  // 않는다 - 넣으면 열이 넓어지고 분야 배지와 무게가 달라진다.
  const srLabel = srGradeLabel(conf);
  const srBadge = document.createElement("span");
  srBadge.className = `badge grade ${srGradeBadgeClass(conf)}`;
  srBadge.textContent = srLabel;
  srBadge.setAttribute(
    "aria-label",
    srLabel === "-" ? "SR 목록에 없음" : `SR 등급 ${srLabel}`,
  );
  gradeCell.append(srBadge);

  const bkLabel = bkGradeLabel(conf);
  const bkBadge = document.createElement("span");
  bkBadge.className = `badge grade-bk ${bkGradeBadgeClass(conf)}`;
  bkBadge.textContent = bkLabel;
  bkBadge.setAttribute(
    "aria-label",
    bkLabel === "-" ? "BK 목록에 없음" : `BK 등급 ${bkLabel}`,
  );
  gradeCell.append(bkBadge);
  row.append(gradeCell);

  const dateCell = document.createElement("td");
  dateCell.textContent = formatDateRange(edition);
  row.append(dateCell);

  const placeCell = document.createElement("td");
  placeCell.textContent = edition?.place || "미정";
  row.append(placeCell);

  const deadlineCell = document.createElement("td");
  deadlineCell.className = "deadline-col";
  const info = formatDeadline(edition, now);
  const when = document.createElement("div");
  when.className = `deadline-date ${info.state}`;
  when.textContent = info.text;
  deadlineCell.append(when);
  if (info.dday) {
    const dday = document.createElement("div");
    dday.className = `dday ${info.state}`;
    dday.textContent = info.dday;
    deadlineCell.append(dday);
  }
  // 어느 마감인지는 항상 밝힌다 - 본 논문이든 포스터든. 본 논문에만 라벨이
  // 없으면 "라벨 없음 = 본 논문"이라는 암묵적 규칙이 생겨 읽는 사람이
  // 매번 추론해야 한다.
  const labelText = deadlineLabelText(info);
  if (labelText) {
    const lbl = document.createElement("div");
    lbl.className = "deadline-label";
    lbl.textContent = labelText;
    deadlineCell.append(lbl);
  }
  // 펼치면 이제 아무것도 빼지 않은 전체 일정을 보여주므로(allDeadlines),
  // 숫자의 의미도 "숨겨진 개수"에서 "전체 단계 수"로 바뀐다. 마감이 하나뿐인
  // 학회는 펼쳐봐야 셀에 이미 쓰인 것과 같은 한 줄만 나오므로 여전히 토글을
  // 달지 않는다 - 추가 정보가 없는 토글은 없느니만 못하다.
  const stages = allDeadlines(edition);
  if (stages.length > 1) {
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "stage-toggle";
    toggle.dataset.toggle = conf.abbr;
    const open = state.expanded.has(conf.abbr);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = `${open ? "▾" : "▸"} 총 ${stages.length}개`;
    toggle.title = "전체 일정 보기";
    deadlineCell.append(toggle);
  }
  row.append(deadlineCell);

  row.append(linkCell(conf, edition));
  return row;
}

// 표에 표시할 컬럼 수. 결과가 없을 때 안내 행을 표 너비 전체로 펼치는 데 쓴다.
const COLUMN_COUNT = 7;

function emptyRow() {
  const row = document.createElement("tr");
  row.className = "empty-row";
  const cell = document.createElement("td");
  cell.colSpan = COLUMN_COUNT;
  cell.textContent = "조건에 맞는 학회가 없습니다. 필터 초기화를 눌러보세요.";
  row.append(cell);
  return row;
}

// data/conferences.json을 못 가져왔을 때(네트워크 오류, 404 등) 표를 그냥
// 비워 두면 사용자는 아무 설명 없이 빈 화면만 본다.
function errorRow(message) {
  const row = document.createElement("tr");
  row.className = "empty-row error-row";
  const cell = document.createElement("td");
  cell.colSpan = COLUMN_COUNT;
  cell.textContent = message;
  row.append(cell);
  return row;
}

// 토글이 펼쳐졌을 때 주 마감 아래로 나머지 단계를 보여주는 행.
function renderStageRow(conf, edition, now) {
  const row = document.createElement("tr");
  row.className = "stage-row";

  const cell = document.createElement("td");
  cell.colSpan = COLUMN_COUNT;

  const list = document.createElement("ol");
  list.className = "stage-list";

  for (const stage of allDeadlines(edition)) {
    const item = document.createElement("li");
    const scraped = stage.source === "cfp-scrape";
    // 셀에 뜨는 대표 마감도 이 목록에 그대로 포함된다(더 이상 빼지 않는다) -
    // 어느 것인지는 클래스와 뱃지로만 표시한다.
    const current = isFeaturedDeadline(stage, edition, now);
    item.className = ["stage", current && "current", scraped && "scraped"]
      .filter(Boolean).join(" ");

    const label = document.createElement("span");
    label.className = "stage-label";
    label.textContent = stage.label;
    item.append(label);

    // 날짜와 D-day는 제출마감 칸과 같은 함수로 만든다. 여기서 따로 계산하면
    // AoE->KST 환산이 빠지거나 시간대에 따라 날짜가 밀리는 식으로 두 곳이
    // 어긋난다 - 실제로 그랬다(docs/lib.js의 formatStage 주석 참고).
    const info = formatStage(stage, now);

    const when = document.createElement("span");
    when.className = "stage-date";
    when.textContent = info.text;
    item.append(when);

    const dday = document.createElement("span");
    dday.className = `stage-dday ${info.state}`;
    dday.textContent = info.dday;
    item.append(dday);

    if (current) {
      // 색만으로 구분하면 색맹/저시력 사용자나 흑백 인쇄에서 안 보이므로
      // 짧은 한글 라벨도 함께 둔다.
      const badge = document.createElement("span");
      badge.className = "badge stage-current-badge";
      badge.textContent = "현재 표시";
      badge.title = "제출마감 칸에 뜨는 바로 그 마감입니다";
      item.append(badge);
    }

    if (scraped) {
      // 자동 추출은 사람이 한 번의 클릭으로 검증할 수 있어야 한다. 다른
      // 모든 앵커처럼 이 링크도 safeHref를 거친다 - evidence.url도 CFP
      // 페이지에서 그대로 가져온 값이라 신뢰할 수 없다.
      const safeUrl = safeHref(stage.evidence?.url, location.href);
      const badge = document.createElement(safeUrl ? "a" : "span");
      badge.className = "badge scraped-badge";
      badge.textContent = "자동 추출";
      badge.title = stage.evidence?.raw_text
        ? `CFP 원문: "${stage.evidence.raw_text}"`
        : "CFP 페이지에서 자동 추출한 일정";
      if (safeUrl) {
        badge.href = safeUrl;
        badge.target = "_blank";
        badge.rel = "noopener noreferrer";
      }
      item.append(badge);
    }
    list.append(item);
  }

  cell.append(list);
  row.append(cell);
  return row;
}

// 체크/토글 상태를 시각(.on)과 스크린 리더(aria-pressed) 양쪽에 같이 반영한다.
function setPressed(button, on) {
  button.classList.toggle("on", on);
  button.setAttribute("aria-pressed", String(on));
}

function render() {
  const now = new Date();
  const visible = state.data.conferences
    .filter((c) => matchesFilters(c, state.filters, now))
    .sort(compareBy(state.sortKey, state.sortDir, now));

  const rows = [];
  if (visible.length > 0) {
    for (const conf of visible) {
      rows.push(renderRow(conf, now));
      if (state.expanded.has(conf.abbr)) {
        const edition = pickEdition(conf.editions, now);
        if (allDeadlines(edition).length > 1) {
          rows.push(renderStageRow(conf, edition, now));
        }
      }
    }
  } else {
    rows.push(emptyRow());
  }
  el.tbody.replaceChildren(...rows);
  el.count.textContent = `${visible.length} / ${state.data.conferences.length}개 표시`;

  document.querySelectorAll("#conference-table th[data-sort]").forEach((th) => {
    const active = th.dataset.sort === state.sortKey;
    th.querySelector(".arrow").textContent = active
      ? (state.sortDir === "asc" ? "▲" : "▼")
      : "⇅";
    th.classList.toggle("active", active);
    th.setAttribute("aria-sort", active
      ? (state.sortDir === "asc" ? "ascending" : "descending")
      : "none");
  });

  document.querySelectorAll("[data-field]").forEach((chip) => {
    setPressed(chip, state.filters.fields.has(chip.dataset.field));
  });
  document.querySelectorAll("[data-grade]").forEach((chip) => {
    setPressed(chip, state.filters.grades.has(chip.dataset.grade));
  });
  document.querySelectorAll("[data-bk-grade]").forEach((chip) => {
    setPressed(chip, state.filters.bkGrades.has(chip.dataset.bkGrade));
  });
  setPressed(document.querySelector("#ai-only"), state.filters.aiOnly);
  setPressed(document.querySelector("#ai-badge"), state.showAiBadge);
  setPressed(document.querySelector("#hide-past"), state.filters.hidePast);

  // 개별 토글로도 state.expanded가 바뀌므로, 전체 펼치기 버튼의 문구는
  // 그 버튼의 클릭 핸들러가 아니라 여기서 매번 실제 상태로부터 다시
  // 계산한다 - 그래야 "무엇을 하면 어떻게 될지"를 버튼이 항상 정확히
  // 말한다. 핸들러는 무엇을 할지만 결정하고, 문구는 render()가 결정한다.
  document.querySelector("#expand-all").textContent =
    state.expanded.size > 0 ? "전체 접기" : "전체 펼치기";

  persistState();
}

function renderStatic() {
  el.generatedAt.textContent = state.data.generated_at
    ? `· ${state.data.generated_at.slice(0, 10)} 갱신`
    : "";

  el.fieldFilters.replaceChildren(...state.data.fields.map((f) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.dataset.field = f.id;
    chip.textContent = f.label;
    chip.style.setProperty("--badge-color", f.color);
    chip.setAttribute("aria-pressed", "false");
    return chip;
  }));

  const unresolved = state.data.unresolved || [];
  if (unresolved.length > 0) {
    el.unresolved.hidden = false;
    el.unresolvedCount.textContent = `${unresolved.length}개`;
    el.unresolvedList.replaceChildren(...unresolved.map((u) => {
      const li = document.createElement("li");
      li.textContent = `${u.abbr} — ${u.reason}`;
      return li;
    }));
  }
}

// ---------- 이벤트 ----------

function toggleInSet(set, value) {
  if (set.has(value)) set.delete(value);
  else set.add(value);
}

function wireEvents() {
  document.querySelectorAll("#conference-table th[data-sort]").forEach((th) => {
    th.querySelector("button").addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = "asc";
      }
      render();
    });
  });

  el.fieldFilters.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-field]");
    if (!chip) return;
    toggleInSet(state.filters.fields, chip.dataset.field);
    render();
  });

  document.querySelectorAll("[data-grade]").forEach((chip) => {
    chip.addEventListener("click", () => {
      toggleInSet(state.filters.grades, chip.dataset.grade);
      render();
    });
  });

  document.querySelectorAll("[data-bk-grade]").forEach((chip) => {
    chip.addEventListener("click", () => {
      toggleInSet(state.filters.bkGrades, chip.dataset.bkGrade);
      render();
    });
  });

  document.querySelector("#ai-only").addEventListener("click", () => {
    state.filters.aiOnly = !state.filters.aiOnly;
    render();
  });

  document.querySelector("#hide-past").addEventListener("click", () => {
    state.filters.hidePast = !state.filters.hidePast;
    render();
  });

  document.querySelector("#ai-badge").addEventListener("click", () => {
    state.showAiBadge = !state.showAiBadge;
    render();
  });

  document.querySelector("#reset").addEventListener("click", () => {
    state.filters = {
      fields: new Set(), grades: new Set(), bkGrades: new Set(),
      aiOnly: false, hidePast: false, query: "",
    };
    el.search.value = "";
    render();
  });

  el.search.addEventListener("input", (event) => {
    state.filters.query = event.target.value;
    render();
  });

  el.tbody.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-toggle]");
    if (!toggle) return;
    const abbr = toggle.dataset.toggle;
    if (state.expanded.has(abbr)) state.expanded.delete(abbr);
    else state.expanded.add(abbr);
    render();
  });

  document.querySelector("#expand-all").addEventListener("click", () => {
    const now = new Date();
    const anyOpen = state.expanded.size > 0;
    state.expanded.clear();
    if (!anyOpen) {
      for (const conf of state.data.conferences) {
        if (allDeadlines(pickEdition(conf.editions, now)).length > 1) {
          state.expanded.add(conf.abbr);
        }
      }
    }
    render();
  });
}

async function main() {
  try {
    const response = await fetch("data/conferences.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
  } catch (err) {
    // 데이터를 못 가져오면 표가 그냥 비어 있어서(0 / 0개 표시) 사용자는
    // 원인을 알 수 없다. 사유를 콘솔에 남기고, 표 본문에 안내 행을 보여준다.
    console.error("학회 데이터를 불러오지 못했습니다:", err);
    el.tbody.replaceChildren(errorRow(
      "학회 데이터를 불러오지 못했습니다. 잠시 후 새로고침 해주세요."
    ));
    return;
  }

  if (!readStateFromUrl()) readStateFromStorage();
  el.search.value = state.filters.query;

  renderStatic();
  wireEvents();
  render();
}

main();
