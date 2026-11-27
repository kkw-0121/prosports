/* 프로스포츠 관중 수 대시보드 — data/summary.json 을 읽어 그린다 (계산 규칙은 서버 쪽 build_summary.py) */
(() => {
  "use strict";

  const COLOR_VAR = { KBO: "--kbo", KLEAGUE: "--kleague", KBL: "--kbl", WKBL: "--wkbl", KOVO: "--kovo" };
  const css = getComputedStyle(document.documentElement);
  const color = (code) => css.getPropertyValue(COLOR_VAR[code]).trim();
  const ACCENT = css.getPropertyValue("--accent").trim();

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const num = (n) => (n == null || Number.isNaN(n) ? "-" : Math.round(n).toLocaleString("ko-KR"));
  const avgOf = (a, g) => (g ? a / g : null);

  /** 1277만 명 / 37.5만 명 / 1.8억 명 처럼 읽기 쉬운 단위 */
  function koUnit(n) {
    if (n == null) return "";
    if (n >= 1e8) return `${(n / 1e8).toFixed(2).replace(/\.?0+$/, "")}억 명`;
    if (n >= 1e6) return `${Math.round(n / 1e4).toLocaleString("ko-KR")}만 명`;
    if (n >= 1e4) return `${(n / 1e4).toFixed(1).replace(/\.0$/, "")}만 명`;
    return `${num(n)}명`;
  }
  function delta(cur, prev) {
    if (cur == null || prev == null || !prev) return null;
    return ((cur - prev) / prev) * 100;
  }
  function deltaTag(d, label) {
    if (d == null) return `<span class="tag">${label} 비교 없음</span>`;
    const cls = d > 0.05 ? "up" : d < -0.05 ? "down" : "";
    const arrow = d > 0.05 ? "▲" : d < -0.05 ? "▼" : "–";
    return `<span class="tag ${cls}" title="${label}">${arrow} ${Math.abs(d).toFixed(1)}%</span>`;
  }
  const shortSeason = (sid) => (sid.includes("-") ? `${sid.slice(0, 4)}-${sid.slice(-2)}` : sid);

  let D, leagues, codes, rowIdx, mainSport, detailSport, progSport;
  const charts = {};

  // ---------------------------------------------------------------- 공통 계산
  const label = (code) => `${leagues[code].name} (${leagues[code].abbr})`;
  /** 종목 카드의 시즌 상태 배지: 진행 중(주황) · 확정(파랑) · 시즌 전(회색 글자) */
  const BADGE = {
    live: '<span class="badge live">진행 중</span>',
    final: '<span class="badge final">확정</span>',
    pre: '<span class="badge pre">· 시즌 전</span>',
  };
  const seasonKey = (code, i) => Object.keys(leagues[code].seasons)[i];
  const seasonOf = (code, i) => leagues[code].seasons[seasonKey(code, i)];
  const isLive = (code, i) => seasonOf(code, i).source === "collected";
  const rowLive = (i) => codes.some((c) => isLive(c, i) && seasonOf(c, i).has_data);

  // ---------------------------------------------------------------- 헤더
  function renderHeader() {
    $("#asOf").textContent = D.as_of.replaceAll("-", ".");
    $("#statusList").innerHTML = codes.map((c) => {
      const s = leagues[c].status;
      return `<li class="status ${s.state}" title="${esc(s.message)}"><span class="dot"></span>${esc(label(c))} <b>${s.label}</b></li>`;
    }).join("");
  }

  function renderChips() {
    $("#seasonChips").innerHTML = D.rows.map((r, i) =>
      `<button class="chip" role="tab" aria-selected="${i === rowIdx}" data-i="${i}">${r.year}<small>${rowLive(i) ? " · 진행 중" : ""}</small></button>`
    ).join("");
    $("#seasonChips").querySelectorAll(".chip").forEach((b) =>
      b.addEventListener("click", () => { rowIdx = +b.dataset.i; renderAll(); }));
  }

  // ---------------------------------------------------------------- KPI
  /** 전 시즌 비교값: 이번 시즌에 경기가 있는 종목만 모아 같은 기준으로 비교 (시즌 전 종목 때문에 왜곡되지 않게) */
  function comparablePrev(i) {
    if (i <= 0) return null;
    const active = codes.filter((c) => seasonOf(c, i).has_data);
    let a = 0, g = 0;
    active.forEach((c) => { const t = seasonOf(c, i - 1).total; a += t.attendance || 0; g += t.games || 0; });
    return { attendance: a, games: g, average: avgOf(a, g), partial: active.length < codes.length,
             names: active.map((c) => leagues[c].abbr) };
  }

  function renderKpis() {
    const r = D.rows[rowIdx], p = comparablePrev(rowIdx);
    const live = rowLive(rowIdx);
    const basis = p?.partial ? `전 시즌 같은 종목(${p.names.join("·")})` : "전 시즌";
    $("#kpis").innerHTML = `
      <div class="card kpi">
        <div class="label">전체 총 관중 ${live ? '<span class="tag live">진행 중</span>' : ""}</div>
        <div class="value">${num(r.attendance)}<span class="unit">명</span></div>
        <div class="meta"><span>약 ${koUnit(r.attendance)}</span><span>${esc(r.row)}</span></div>
      </div>
      <div class="card kpi">
        <div class="label">전체 평균 관중 ${deltaTag(delta(r.average, p?.average), basis + " 평균 대비")}</div>
        <div class="value">${num(r.average)}<span class="unit">명</span></div>
        <div class="meta"><span>${esc(basis)} 평균 ${p ? num(p.average) + "명" : "-"}</span><span>총 관중 ÷ 총 경기</span></div>
      </div>
      <div class="card kpi">
        <div class="label">총 경기 수</div>
        <div class="value">${num(r.games)}<span class="unit">경기</span></div>
        <div class="meta"><span>5개 종목 합계</span><span>${esc(D.rows[rowIdx - 1] ? "전 시즌 " + num(D.rows[rowIdx - 1].games) + "경기" : "")}</span></div>
      </div>`;
  }

  // ---------------------------------------------------------------- 종목 카드
  function renderSportCards() {
    $("#sportCards").innerHTML = codes.map((c) => {
      const lg = leagues[c], sid = seasonKey(c, rowIdx), s = lg.seasons[sid];
      const prev = rowIdx > 0 ? seasonOf(c, rowIdx - 1) : null;
      const badge = isLive(c, rowIdx) ? (s.has_data ? BADGE.live : BADGE.pre) : BADGE.final;
      let body;
      if (!s.has_data) {
        const last = prev && prev.has_data ? `직전 시즌 ${shortSeason(seasonKey(c, rowIdx - 1))}: ${koUnit(prev.total.attendance)}` : "";
        body = `<div class="empty">아직 경기 없음<br><small>${esc(last)}</small></div>`;
      } else {
        body = `
          <div class="big">${num(s.total.attendance)}<small>${koUnit(s.total.attendance)}</small></div>
          <dl><dt>경기 수</dt><dd>${num(s.total.games)}</dd><dt>평균</dt><dd>${num(s.total.average)}명</dd></dl>
          <div class="foot-row"><span class="card-sub">평균 · 전 시즌 대비</span>${deltaTag(delta(s.total.average, prev?.total.average), "평균 관중 전 시즌 대비")}</div>`;
      }
      return `<article class="card sport ${c === mainSport ? "active" : ""}" style="--c:${color(c)}" data-code="${c}" tabindex="0">
          <div class="name"><i></i>${esc(label(c))}</div>
          <div class="season">${shortSeason(sid)} 시즌 ${badge}</div>${body}</article>`;
    }).join("");
    $("#sportCards").querySelectorAll(".sport").forEach((el) => {
      const go = () => { selectMain(el.dataset.code); $(".progress-card").scrollIntoView({ behavior: "smooth", block: "start" }); };
      el.addEventListener("click", go);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    });
  }

  // ---------------------------------------------------------------- 연도별 추이
  const fade = (hex, a) => {
    const h = hex.replace("#", "");
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    return `rgba(${r},${g},${b},${a})`;
  };
  function baseOptions() {
    return {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { backgroundColor: "#15171c", padding: 10, cornerRadius: 8, boxPadding: 4 } },
      scales: {
        x: { grid: { display: false }, border: { display: false } },
        y: { grid: { color: "#eef0f3" }, border: { display: false }, ticks: { callback: (v) => (v >= 1e4 ? `${v / 1e4}만` : v) } },
      },
    };
  }
  function renderTrend() {
    const labels = D.rows.map((r, i) => (rowLive(i) ? [r.year, "(진행 중)"] : r.year));
    const datasets = codes.map((c) => ({
      type: "bar", label: label(c), stack: "s", order: 2,
      data: D.rows.map((_, i) => seasonOf(c, i).total.attendance ?? 0),
      backgroundColor: D.rows.map((_, i) => (i === rowIdx ? color(c) : fade(color(c), 0.32))),
      borderRadius: 4, borderSkipped: false, maxBarThickness: 56,
    }));
    datasets.push({
      type: "line", label: "전체 평균 관중", yAxisID: "y1", order: 1,
      data: D.rows.map((r) => r.average), borderColor: "#2b2f36", borderWidth: 2, tension: 0.3,
      // 진행 중 시즌으로 이어지는 구간은 점선 (시즌이 덜 끝나 종목 구성이 달라 단순 비교 주의)
      segment: { borderDash: (ctx) => (rowLive(ctx.p1DataIndex) ? [5, 4] : undefined) },
      pointRadius: D.rows.map((_, i) => (i === rowIdx ? 5 : 3)),
      pointBackgroundColor: D.rows.map((_, i) => (i === rowIdx ? ACCENT : "#2b2f36")),
      pointBorderColor: "#fff", pointBorderWidth: 1.5,
    });
    const opt = baseOptions();
    opt.scales.x.stacked = true;
    opt.scales.y.stacked = true;
    opt.scales.y1 = { position: "right", beginAtZero: true, grid: { display: false }, border: { display: false },
                      ticks: { callback: (v) => num(v) } };
    opt.plugins.tooltip.callbacks = {
      label: (ctx) => ` ${ctx.dataset.label}: ${num(ctx.raw)}명`,
      footer: (items) => {
        const i = items[0].dataIndex;
        return `전체 ${num(D.rows[i].attendance)}명 · ${num(D.rows[i].games)}경기`;
      },
    };
    opt.onClick = (_, els) => { if (els.length) { rowIdx = els[0].index; renderAll(); } };
    draw("trend", "#trendChart", { data: { labels, datasets }, options: opt });
    $("#trendLegend").innerHTML = codes.map((c) => `<span><i style="--c:${color(c)}"></i>${esc(label(c))}</span>`).join("")
      + `<span><i class="line" style="--c:#2b2f36"></i>평균</span>`;
  }

  function draw(key, sel, cfg) {
    if (charts[key]) charts[key].destroy();
    charts[key] = new Chart($(sel), cfg);
  }

  // ---------------------------------------------------------------- 종목 상세
  function renderTabs() {
    $("#sportTabs").innerHTML = codes.map((c) =>
      `<button class="tab" role="tab" aria-selected="${c === detailSport}" data-code="${c}" style="--c:${color(c)}"><i></i>${esc(label(c))}</button>`).join("");
    $("#sportTabs").querySelectorAll(".tab").forEach((b) =>
      b.addEventListener("click", () => { detailSport = b.dataset.code; renderDetail(); }));   // 상세만 바뀜
  }

  function renderDetail() {
    renderTabs();
    const lg = leagues[detailSport], c = color(detailSport), keys = Object.keys(lg.seasons);
    $(".detail-grid").classList.toggle("wide", lg.items.length > 3);   // 항목이 많으면 표를 아래 전체 폭으로
    // 그래프
    const opt = baseOptions();
    opt.plugins.tooltip.callbacks = {
      label: (ctx) => {
        const s = lg.seasons[keys[ctx.dataIndex]].total;
        return ` ${num(s.attendance)}명 · ${num(s.games)}경기 · 평균 ${num(s.average)}명`;
      },
    };
    opt.onClick = (_, els) => { if (els.length) { rowIdx = els[0].index; renderAll(); } };
    draw("detail", "#detailChart", {
      type: "bar",
      data: {
        labels: keys.map(shortSeason),
        datasets: [{
          data: keys.map((k) => lg.seasons[k].total.attendance ?? 0),
          backgroundColor: keys.map((_, i) => (i === rowIdx ? c : fade(c, 0.25))),
          borderRadius: 6, maxBarThickness: 44,
        }],
      },
      options: opt,
    });

    // 공식 집계 대조 + 메모
    const sid = keys[rowIdx], s = lg.seasons[sid];
    let box = "";
    if (s.official.length) {
      box = s.official.map((o) => {
        if (o.diff === 0) {
          return `<div class="off-row ok"><div class="t">${esc(o.label)} <span>공식 집계와 일치</span></div>
            <div class="d">경기별 합계 ${num(o.ours)}명 · 연맹 공식 ${num(o.official)}명</div></div>`;
        }
        if (o.diff == null) {
          return `<div class="off-row none"><div class="t">${esc(o.label)}</div><div class="d">연맹 공식 ${num(o.official)}명 · 경기별 합계를 나눌 수 없어 비교 불가</div></div>`;
        }
        return `<div class="off-row diff"><div class="t">${esc(o.label)} <span>공식 집계와 ${num(Math.abs(o.diff))}명 차이</span></div>
          <div class="d">경기별 합계 ${num(o.ours)}명 · 연맹 공식 ${num(o.official)}명 (${o.diff > 0 ? "공식이 많음" : "공식이 적음"})</div></div>`;
      }).join("");
    } else if (s.official_status === "not_provided") {
      box = `<div class="off-row none"><div class="t">공식 누적치 미제공</div><div class="d">연맹이 이 시즌 누적 관중을 따로 발표하지 않아 경기별 합계만 표시</div></div>`;
    } else {
      box = `<div class="off-row none"><div class="t">확정값</div><div class="d">지난 시즌은 엑셀에 입력된 확정값(엑셀 기준일 ${esc(D.excel_as_of)})을 사용</div></div>`;
    }
    box += s.notes.map((n) => `<div class="note">${esc(n)}</div>`).join("");
    if (s.source !== "baseline" && s.last_game) box += `<div class="note">마지막 반영 경기 ${s.last_game.replaceAll("-", ".")} · 수집 ${s.collected_at.slice(0, 16).replace("T", " ")}</div>`;
    $("#officialBox").innerHTML = `<h3 class="card-sub" style="margin:0">${shortSeason(sid)} 시즌 · 연맹 공식 집계 대조</h3>` + box;

    // 표: 칸마다 관중(크게) + 경기·평균(작게) → 열 수를 줄여 가로 스크롤 없이
    const items = lg.items;
    const head = `<tr><th>시즌</th>${items.map((it) => `<th>${esc(it.label)}</th>`).join("")}<th>합계</th></tr>`;
    const body = newestFirst(keys).map(([k, i]) => {
      const se = lg.seasons[k];
      const live = se.source === "collected" && se.has_data ? '<span class="tag live">진행 중</span>' : "";
      return `<tr class="${i === rowIdx ? "sel" : ""}"><td class="row-head">${shortSeason(k)}${live}</td>
        ${items.map((it) => statCell(se.items[it.key], it.label)).join("")}${statCell(se.total, "합계", "total")}</tr>`;
    }).join("");
    $("#detailTable").innerHTML = `<table class="stat stack"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  }

  /** 표는 최근 시즌이 위로: [값, 원래 순번] 목록을 거꾸로 (그래프는 왼쪽→오른쪽 시간순 그대로) */
  const newestFirst = (arr) => arr.map((v, i) => [v, i]).reverse();

  /** 표 한 칸: 관중 수 + (경기 · 평균). 경기가 없으면 '-' */
  function statCell(v, lbl, cls = "") {
    if (!v || (!v.games && !v.attendance)) {
      return `<td class="${cls} empty" data-label="${esc(lbl)}"><b>-</b></td>`;
    }
    return `<td class="${cls}" data-label="${esc(lbl)}"><b>${num(v.attendance)}</b>`
      + `<small>${num(v.games)}경기 · 평균 ${num(v.average)}</small></td>`;
  }

  // ---------------------------------------------------------------- 종합 표
  function renderSummary() {
    const head = `<tr><th>구분</th>${codes.map((c) => `<th style="--c:${color(c)}"><span class="sw"></span>${esc(label(c))}</th>`).join("")}<th>전체</th></tr>`;
    const body = newestFirst(D.rows).map(([r, i]) => `<tr class="${i === rowIdx ? "sel" : ""}">
      <td class="row-head">${esc(r.year)}<small>${esc(r.split)}</small></td>${codes.map((c) =>
        statCell(seasonOf(c, i).total, label(c))).join("")}
      ${statCell({ attendance: r.attendance, games: r.games, average: r.average }, "전체", "total")}</tr>`).join("");
    $("#summaryTable").innerHTML = `<table class="stat stack"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  }

  function renderFoot() {
    $("#foot").innerHTML = `자료: KBO · K리그 데이터포털 · KBL · WKBL · KOVO 공식 홈페이지 (경기별 관중 수 합산)<br>
      지난 시즌은 엑셀 확정값(엑셀 기준일 ${esc(D.excel_as_of)}) · 화면 데이터 생성 ${esc(D.generated_at.slice(0, 16).replace("T", " "))}`;
  }

  /** 기본 종목: 카드 순서(야구→축구→남자농구→여자농구→배구)에서 경기가 있는 첫 종목 (시즌 전 종목은 건너뜀) */
  const defaultSport = (i) => codes.find((c) => seasonOf(c, i).has_data) || codes[0];

  /** 메인 선택(종목 카드): 진행 현황·종목별 상세를 모두 그 종목으로 */
  function selectMain(code) {
    mainSport = detailSport = progSport = code;
    renderSportCards(); renderDetail();
    if (D.progress) renderProgress();
  }

  function renderAll() {
    // 시즌을 바꿨는데 메인 카드 종목이 그 시즌에 경기가 없으면 기본 종목으로 바뀜 (메인을 누른 것처럼 셋 다)
    if (!seasonOf(mainSport, rowIdx).has_data) mainSport = detailSport = progSport = defaultSport(rowIdx);
    if (!seasonOf(detailSport, rowIdx).has_data) detailSport = mainSport;
    renderChips(); renderKpis(); renderSportCards(); renderTrend(); renderDetail(); renderSummary();
    if (D.progress) renderProgress();
  }

  // ---------------------------------------------------------------- 2차: 이번 시즌 진행 현황
  let recentLeague = "ALL";
  const WEEK = ["일", "월", "화", "수", "목", "금", "토"];
  const dateLabel = (d) => { const t = new Date(`${d}T00:00:00`); return `${d.slice(5).replace("-", ".")} (${WEEK[t.getDay()]})`; };

  function renderProgress() {
    const P = D.progress[rowIdx];          // 위에서 고른 연도(엑셀 행)의 시즌
    $("#progressTabs").innerHTML = codes.map((c) =>
      `<button class="tab" role="tab" aria-selected="${c === progSport}" data-code="${c}" style="--c:${color(c)}"><i></i>${esc(label(c))}</button>`).join("");
    $("#progressTabs").querySelectorAll(".tab").forEach((b) =>
      b.addEventListener("click", () => { progSport = b.dataset.code; renderProgress(); }));   // 진행 현황만 바뀜

    const p = P[progSport], c = color(progSport);
    const opt = baseOptions();
    opt.interaction = { mode: "nearest", intersect: false, axis: "x" };
    opt.scales.x = { type: "linear", min: 1, grid: { display: false }, border: { display: false },
                     title: { display: true, text: "개막 후 일수", color: css.getPropertyValue("--text-3").trim() },
                     ticks: { callback: (v) => `${v}일` } };
    opt.plugins.tooltip.callbacks = {
      title: (items) => `개막 후 ${items[0].raw.x}일째`,
      label: (ctx) => ` ${ctx.dataset.label}: ${num(ctx.raw.y)}명 (${ctx.raw.games}경기, ${ctx.raw.date})`,
    };
    opt.plugins.legend = { display: true, position: "top", align: "end", labels: { boxWidth: 12, boxHeight: 2 } };
    const toXY = (pts) => pts.map((q) => ({ x: q.day, y: q.attendance, games: q.games, date: q.date }));
    const datasets = [];
    if (p.prev.length) {
      datasets.push({ label: `지난 시즌 ${shortSeason(p.prev_season)}`, data: toXY(p.prev), borderColor: "#b9bec7",
                      borderDash: [5, 4], borderWidth: 2, pointRadius: 0, tension: 0.15 });
    }
    if (p.cur.length) {
      datasets.push({ label: `이번 시즌 ${shortSeason(p.season)}`, data: toXY(p.cur), borderColor: c, backgroundColor: c,
                      borderWidth: 2.5, pointRadius: p.cur.length < 3 ? 4 : 0, tension: 0.15 });
    }
    if (p.compare) opt.scales.x.max = Math.max(p.compare.day + 7, 14);   // 이번 시즌 진행 구간 위주로 보기
    draw("progress", "#progressChart", { type: "line", data: { datasets }, options: opt });

    // 오른쪽 숫자
    let html;
    const stateBadge = { live: BADGE.live, final: BADGE.final, pre: BADGE.pre, none: "" }[p.state] || "";
    if (p.state === "pre" || p.state === "none") {
      html = `<div class="ps-head">${esc(label(progSport))} ${shortSeason(p.season)} 시즌 ${stateBadge}</div>`;
    } else {
      const k = p.compare, last = p.cur[p.cur.length - 1];
      html = `<div class="ps-head">${esc(label(progSport))} ${shortSeason(p.season)} 시즌 ${stateBadge}</div>`;
      if (k) {
        html += `<div class="ps-when">개막 후 <b>${k.day}일째</b> · ${k.date.replaceAll("-", ".")} 경기까지
                 <span>지난 시즌 같은 시점: ${k.prev_date.replaceAll("-", ".")}</span></div>
          <div class="ps-row"><span class="ps-k">누적 관중</span><span class="ps-v">${num(k.cur.attendance)}명</span>
            <span class="ps-p">지난 시즌 ${num(k.prev.attendance)}명</span>${deltaTag(k.rate_attendance, "누적 관중 지난 시즌 같은 시점 대비")}</div>
          <div class="ps-row"><span class="ps-k">경기 수</span><span class="ps-v">${num(k.cur.games)}경기</span>
            <span class="ps-p">지난 시즌 ${num(k.prev.games)}경기</span><span></span></div>
          <div class="ps-row"><span class="ps-k">평균 관중</span><span class="ps-v">${num(k.cur.average)}명</span>
            <span class="ps-p">지난 시즌 ${num(k.prev.average)}명</span>${deltaTag(k.rate_average, "평균 관중 지난 시즌 같은 시점 대비")}</div>`;
      } else if (last) {
        html += `<div class="ps-when">${last.date.replaceAll("-", ".")} 경기까지</div>
          <div class="ps-row"><span class="ps-k">누적 관중</span><span class="ps-v">${num(last.attendance)}명</span><span class="ps-p"></span><span></span></div>
          <div class="ps-row"><span class="ps-k">경기 수</span><span class="ps-v">${num(last.games)}경기</span><span class="ps-p"></span><span></span></div>`;
      }
    }
    html += p.notes.map((n) => `<div class="note">${esc(n)}</div>`).join("");
    $("#progressStats").innerHTML = html;
  }

  // ---------------------------------------------------------------- 2차: 최근 경기
  function renderRecent() {
    const rows = D.recent;
    const count = (c) => rows.filter((r) => c === "ALL" || r.league === c).length;
    $("#recentSub").textContent = `최근 ${D.recent_days}일 경기별 관중 수 (${D.as_of.replaceAll("-", ".")} 기준, 최신 순)`;
    $("#recentTabs").innerHTML = [["ALL", "전체", ""], ...codes.map((c) => [c, leagues[c].name, color(c)])].map(([c, n, col]) =>
      `<button class="tab" role="tab" aria-selected="${c === recentLeague}" data-code="${c}" style="--c:${col || "transparent"}">${col ? "<i></i>" : ""}${esc(n)} <small>${count(c)}</small></button>`).join("");
    $("#recentTabs").querySelectorAll(".tab").forEach((b) =>
      b.addEventListener("click", () => { recentLeague = b.dataset.code; renderRecent(); }));
    const list = rows.filter((r) => recentLeague === "ALL" || r.league === recentLeague);
    if (!list.length) {
      $("#recentTable").innerHTML = `<div class="note">최근 ${D.recent_days}일 동안 열린 경기가 없습니다.</div>`;
      return;
    }
    const body = list.map((r) => {
      const att = r.pending ? '<span class="muted-txt">반영 대기</span>'
        : r.attendance == null ? '<span class="muted-txt">미공개</span>' : `<b>${num(r.attendance)}</b>명`;
      const match = r.away ? `${esc(r.home)} <span class="vs">vs</span> ${esc(r.away)}` : `${esc(r.home)} <span class="muted-txt">홈 경기</span>`;
      return `<tr><td data-label="날짜">${dateLabel(r.date)}</td>
        <td data-label="리그"><span class="lg" style="--c:${color(r.league)}"><i></i>${esc(leagues[r.league].name)}</span></td>
        <td data-label="구분">${esc(r.label)}</td><td data-label="경기">${match}</td>
        <td data-label="경기장">${esc(r.venue || "-")}</td><td data-label="관중" class="num">${att}</td></tr>`;
    }).join("");
    $("#recentTable").innerHTML = `<table class="recent stack"><thead><tr><th>날짜</th><th>리그</th><th>구분</th><th>경기</th><th>경기장</th><th class="num">관중</th></tr></thead><tbody>${body}</tbody></table>`;
  }

  // ---------------------------------------------------------------- 엑셀 다운로드 (assets/excel.js)
  $("#btnExcel").addEventListener("click", async () => {
    const btn = $("#btnExcel");
    if (!D) return;
    btn.disabled = true;
    try {
      const { skipped } = await window.ExcelExport.download(D);
      if (skipped.length) alert(`관중을 알 수 없어 엑셀에서 비워 둔 항목: ${skipped.join(", ")}\n('공식 집계 대조' 시트에 사유가 있습니다)`);
    } catch (e) {
      alert(`엑셀 파일을 만들지 못했습니다: ${e.message}`);
    } finally {
      btn.disabled = false;
    }
  });

  // ---------------------------------------------------------------- 시작
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = css.getPropertyValue("--text-3").trim();

  fetch("data/summary.json", { cache: "no-store" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((data) => {
      D = data; leagues = D.leagues; codes = Object.keys(leagues);
      rowIdx = D.rows.reduce((last, r, i) => (r.games > 0 ? i : last), 0);
      mainSport = detailSport = progSport = defaultSport(rowIdx);
      renderHeader(); renderFoot(); renderAll();
      if (D.recent) renderRecent();
    })
    .catch((e) => {
      document.querySelector(".page").insertAdjacentHTML("afterbegin",
        `<div class="card" style="border-color:#f3c4c4;color:#d64545">데이터를 불러오지 못했습니다 (${esc(e.message)}). 잠시 후 새로고침해 주세요.</div>`);
    });
})();
