/* 엑셀 다운로드: 양식(template/양식.xlsx)의 숫자 칸만 바꿔서 내려준다.
 *
 * ExcelJS 로 파일 전체를 다시 쓰면 양식의 텍스트 상자(안내문)가 사라지므로,
 * xlsx(zip) 안의 XML 에서 필요한 칸의 값만 직접 바꾼다. 서식·병합·그림·텍스트 상자·수식은 원본 그대로.
 * 바꾸는 것:
 *   1) 리그별 시트: 자동 수집 시즌의 관중·경기 수 칸 (수식 칸은 절대 건드리지 않음)
 *   2) 종합 시트: 기준일 칸, 그리고 수식의 '저장된 결과값'(수식 자체는 그대로, 엑셀이 열 때 다시 계산)
 *   3) 맨 뒤에 '공식 집계 대조' 시트 추가
 */
(() => {
  "use strict";
  const NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
  const NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
  const NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships";
  const XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n';

  const parse = (s) => new DOMParser().parseFromString(s, "application/xml");
  const ser = (d) => XML_HEAD + new XMLSerializer().serializeToString(d).replace(/^<\?xml[^>]*\?>\s*/, "");
  const colNum = (col) => [...col].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);
  const splitRef = (ref) => { const m = /^([A-Z]+)(\d+)$/.exec(ref); return [m[1], +m[2]]; };
  const xmlEsc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ------------------------------------------------------------ 시트 XML 다루기
  class Sheet {
    constructor(doc) { this.doc = doc; this.data = doc.getElementsByTagNameNS(NS, "sheetData")[0]; }
    row(r) {
      const rows = [...this.data.getElementsByTagNameNS(NS, "row")];
      let el = rows.find((x) => +x.getAttribute("r") === r);
      if (!el) {
        el = this.doc.createElementNS(NS, "row");
        el.setAttribute("r", r);
        const after = rows.find((x) => +x.getAttribute("r") > r);
        this.data.insertBefore(el, after || null);
      }
      return el;
    }
    cell(ref) {
      const [col, r] = splitRef(ref);
      const row = this.row(r);
      const cells = [...row.getElementsByTagNameNS(NS, "c")];
      let c = cells.find((x) => x.getAttribute("r") === ref);
      if (!c) {
        c = this.doc.createElementNS(NS, "c");
        c.setAttribute("r", ref);
        const after = cells.find((x) => colNum(splitRef(x.getAttribute("r"))[0]) > colNum(col));
        row.insertBefore(c, after || null);
      }
      return c;
    }
    child(c, name) { return c.getElementsByTagNameNS(NS, name)[0]; }
    hasFormula(ref) { return !!this.child(this.cell(ref), "f"); }
    /** 입력 칸에 숫자. 수식 칸이면 바꾸지 않고 false */
    setNumber(ref, value) {
      const c = this.cell(ref);
      if (this.child(c, "f")) return false;
      [...c.childNodes].forEach((n) => c.removeChild(n));
      c.removeAttribute("t");
      const v = this.doc.createElementNS(NS, "v");
      v.textContent = String(value);
      c.appendChild(v);
      return true;
    }
    setText(ref, text) {
      const c = this.cell(ref);
      [...c.childNodes].forEach((n) => c.removeChild(n));
      c.setAttribute("t", "inlineStr");
      const is = this.doc.createElementNS(NS, "is"), t = this.doc.createElementNS(NS, "t");
      t.textContent = text; is.appendChild(t); c.appendChild(is);
    }
    getNumber(ref) {
      const v = this.child(this.cell(ref), "v");
      return v && v.textContent !== "" && !isNaN(+v.textContent) ? +v.textContent : 0;
    }
    /** 수식은 그대로 두고 저장된 결과값만 갱신 (미리보기 프로그램에서도 맞는 숫자가 보이게) */
    setFormulaResult(ref, value) {
      const c = this.cell(ref);
      if (!this.child(c, "f")) return;
      let v = this.child(c, "v");
      if (!v) { v = this.doc.createElementNS(NS, "v"); c.appendChild(v); }
      if (value == null) { c.setAttribute("t", "e"); v.textContent = "#DIV/0!"; }
      else { c.removeAttribute("t"); v.textContent = String(value); }
    }
  }

  // ------------------------------------------------------------ 스타일 추가 (새 시트용, 기존 스타일은 그대로)
  function addStyles(doc) {
    const fonts = doc.getElementsByTagNameNS(NS, "fonts")[0];
    const fills = doc.getElementsByTagNameNS(NS, "fills")[0];
    const xfs = doc.getElementsByTagNameNS(NS, "cellXfs")[0];
    const base = fonts.getElementsByTagNameNS(NS, "font")[0];
    const bold = base.cloneNode(true);
    bold.insertBefore(doc.createElementNS(NS, "b"), bold.firstChild);
    fonts.appendChild(bold);
    const boldId = fonts.getElementsByTagNameNS(NS, "font").length - 1;
    const addFill = (rgb) => {
      const f = doc.createElementNS(NS, "fill"), p = doc.createElementNS(NS, "patternFill"), fg = doc.createElementNS(NS, "fgColor");
      p.setAttribute("patternType", "solid"); fg.setAttribute("rgb", rgb); p.appendChild(fg); f.appendChild(p); fills.appendChild(f);
      return fills.getElementsByTagNameNS(NS, "fill").length - 1;
    };
    const gray = addFill("FFF2F2F2"), yellow = addFill("FFFFF2CC");
    const addXf = (fontId, fillId, numFmtId) => {
      const x = doc.createElementNS(NS, "xf");
      x.setAttribute("numFmtId", numFmtId); x.setAttribute("fontId", fontId); x.setAttribute("fillId", fillId);
      x.setAttribute("borderId", "0"); x.setAttribute("xfId", "0");
      if (+numFmtId) x.setAttribute("applyNumberFormat", "1");
      if (+fontId) x.setAttribute("applyFont", "1");
      if (+fillId) x.setAttribute("applyFill", "1");
      xfs.appendChild(x);
      return xfs.getElementsByTagNameNS(NS, "xf").length - 1;
    };
    const s = { text: addXf(0, 0, 0), title: addXf(boldId, 0, 0), head: addXf(boldId, gray, 0),
                num: addXf(0, 0, 3), numWarn: addXf(0, yellow, 3), textWarn: addXf(0, yellow, 0) };
    for (const el of [fonts, fills, xfs]) el.setAttribute("count", el.children.length);
    return s;
  }

  // ------------------------------------------------------------ '공식 집계 대조' 시트
  function officialSheetXml(D, st) {
    const rows = [];
    const cell = (col, r, v, s) => (v == null || v === "" ? `<c r="${col}${r}" s="${s}"/>`
      : typeof v === "number" ? `<c r="${col}${r}" s="${s}"><v>${v}</v></c>`
        : `<c r="${col}${r}" s="${s}" t="inlineStr"><is><t xml:space="preserve">${xmlEsc(v)}</t></is></c>`);
    let r = 1;
    rows.push(`<row r="${r}">${cell("A", r, "연맹 공식 누적치 대조", st.title)}</row>`); r += 1;
    rows.push(`<row r="${r}">${cell("A", r, `기준일 ${D.as_of.replaceAll("-", ".")} · 종합·리그별 시트는 경기별 합계로 채움 · 차이 = 연맹 공식 − 경기별 합계`, st.text)}</row>`); r += 2;
    const cols = ["종목", "시즌", "항목", "경기별 합계", "연맹 공식", "차이", "비고"];
    rows.push(`<row r="${r}">${cols.map((h, i) => cell("ABCDEFG"[i], r, h, st.head)).join("")}</row>`); r += 1;
    for (const [code, lg] of Object.entries(D.leagues)) {
      for (const [sid, s] of Object.entries(lg.seasons)) {
        if (s.source === "baseline") continue;          // 수집 시즌(진행 중·확정)만
        const name = `${lg.name} (${lg.abbr})`;
        if (s.official.length) {
          for (const o of s.official) {
            const warn = o.diff !== 0;
            const note = o.diff == null ? "경기별 합계를 나눌 수 없어 비교 불가" : o.diff === 0 ? "일치" : `공식 집계와 ${Math.abs(o.diff).toLocaleString("ko-KR")}명 차이`;
            rows.push(`<row r="${r}">${cell("A", r, name, st.text)}${cell("B", r, sid, st.text)}${cell("C", r, o.label, st.text)}`
              + `${cell("D", r, o.ours, st.num)}${cell("E", r, o.official, st.num)}${cell("F", r, o.diff, warn ? st.numWarn : st.num)}`
              + `${cell("G", r, note + (o.note ? ` · ${o.note}` : ""), warn ? st.textWarn : st.text)}</row>`);
            r += 1;
          }
        } else {
          rows.push(`<row r="${r}">${cell("A", r, name, st.text)}${cell("B", r, sid, st.text)}${cell("C", r, "시즌 전체", st.text)}`
            + `${cell("D", r, s.total.attendance, st.num)}${cell("E", r, null, st.text)}${cell("F", r, null, st.text)}`
            + `${cell("G", r, s.has_data ? "공식 누적치 미제공" : "아직 경기 없음", st.text)}</row>`);
          r += 1;
        }
        for (const n of s.notes) {
          rows.push(`<row r="${r}">${cell("A", r, name, st.text)}${cell("B", r, sid, st.text)}${cell("C", r, "참고", st.text)}${cell("G", r, n, st.text)}</row>`);
          r += 1;
        }
      }
    }
    const widths = [18, 12, 22, 14, 14, 12, 70];
    return XML_HEAD + `<worksheet xmlns="${NS}" xmlns:r="${NS_R}"><sheetViews><sheetView workbookViewId="0"/></sheetViews>`
      + `<sheetFormatPr defaultRowHeight="16.5"/><cols>${widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join("")}</cols>`
      + `<sheetData>${rows.join("")}</sheetData><pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>`;
  }

  // ------------------------------------------------------------ 본체
  async function build(D) {
    const X = D.excel;
    const buf = await fetch(encodeURI(X.template), { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error(`양식 파일을 불러오지 못함 (${r.status})`);
      return r.arrayBuffer();
    });
    const zip = await JSZip.loadAsync(buf, { createFolders: false });   // 원본에 없는 폴더 항목을 만들지 않음
    const read = async (p) => parse(await zip.file(p).async("string"));
    const put = (p, data) => zip.file(p, data, { createFolders: false });

    // 시트 이름 → 파일 경로
    const wb = await read("xl/workbook.xml"), rels = await read("xl/_rels/workbook.xml.rels");
    const relTarget = {};
    [...rels.getElementsByTagNameNS(NS_PKG, "Relationship")].forEach((r) => { relTarget[r.getAttribute("Id")] = r.getAttribute("Target"); });
    const sheetEls = [...wb.getElementsByTagNameNS(NS, "sheet")];
    const pathOf = {};
    sheetEls.forEach((s) => { pathOf[s.getAttribute("name")] = "xl/" + relTarget[s.getAttributeNS(NS_R, "id")].replace(/^\/?xl\//, ""); });
    const sheets = {};
    const sheet = async (name) => {
      if (!pathOf[name]) throw new Error(`양식에 '${name}' 시트가 없음`);
      return (sheets[name] ||= new Sheet(await read(pathOf[name])));
    };

    // 1) 리그별 시트: 자동 수집 시즌만
    const skipped = [];
    for (const [code, xl] of Object.entries(X.leagues)) {
      const sh = await sheet(xl.sheet), lg = D.leagues[code], keys = Object.keys(lg.seasons);
      keys.forEach((sid, i) => {
        const s = lg.seasons[sid];
        if (s.source === "baseline") return;            // 엑셀 확정값 시즌은 양식 그대로
        for (const it of xl.items) {
          const v = s.items[it.key], row = it.first_row + i;
          if (!v || (!v.games && !v.attendance)) continue;           // 경기 없음 → 양식 그대로(빈칸)
          if (v.attendance == null) { skipped.push(`${lg.name} ${sid} ${it.label}`); continue; }   // 모르면 비워 둠
          const a = sh.setNumber(`${it.attendance_col}${row}`, v.attendance);
          const g = sh.setNumber(`${it.games_col}${row}`, v.games);
          if (!a || !g) throw new Error(`${xl.sheet} ${row}행은 수식 칸이라 바꾸지 않음 (설정 확인 필요)`);
        }
      });
    }

    // 2) 종합 시트: 기준일 + 수식 결과값 갱신
    const sum = await sheet(X.summary_sheet);
    sum.setText(X.as_of_cell, D.as_of.replaceAll("-", "."));
    for (let i = 0; i < X.seasons.length; i++) {
      const r = X.summary_first_row + i;
      let allA = 0, allG = 0;
      for (const [code, xl] of Object.entries(X.leagues)) {
        const sh = await sheet(xl.sheet);
        let a = 0, g = 0;
        for (const key of xl.total) {
          const it = xl.items.find((x) => x.key === key);
          a += sh.getNumber(`${it.attendance_col}${it.first_row + i}`);
          g += sh.getNumber(`${it.games_col}${it.first_row + i}`);
        }
        sum.setFormulaResult(`${xl.summary_cols.attendance}${r}`, a);
        sum.setFormulaResult(`${xl.summary_cols.games}${r}`, g);
        sum.setFormulaResult(`${xl.summary_cols.average}${r}`, g ? a / g : null);
        allA += a; allG += g;
      }
      sum.setFormulaResult(`${X.overall_total_col}${r}`, allA);
      sum.setFormulaResult(`${X.overall_avg_col}${r}`, allG ? allA / allG : null);
    }
    for (const [name, sh] of Object.entries(sheets)) put(pathOf[name], ser(sh.doc));

    // 엑셀이 열 때 수식을 모두 다시 계산
    const calc = wb.getElementsByTagNameNS(NS, "calcPr")[0];
    if (calc) calc.setAttribute("fullCalcOnLoad", "1");

    // 3) '공식 집계 대조' 시트 추가 (맨 뒤)
    const styles = await read("xl/styles.xml");
    const st = addStyles(styles);
    put("xl/styles.xml", ser(styles));
    let n = 1;
    while (zip.file(`xl/worksheets/sheet${n}.xml`)) n += 1;
    const newPath = `worksheets/sheet${n}.xml`;
    put(`xl/${newPath}`, officialSheetXml(D, st));
    const relIds = Object.keys(relTarget).map((id) => +id.replace(/\D/g, "") || 0);
    const rid = `rId${Math.max(...relIds) + 1}`;
    const rel = rels.createElementNS(NS_PKG, "Relationship");
    rel.setAttribute("Id", rid);
    rel.setAttribute("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet");
    rel.setAttribute("Target", newPath);
    rels.documentElement.appendChild(rel);
    put("xl/_rels/workbook.xml.rels", ser(rels));
    const sheetsEl = wb.getElementsByTagNameNS(NS, "sheets")[0];
    const se = wb.createElementNS(NS, "sheet");
    se.setAttribute("name", X.official_sheet);
    se.setAttribute("sheetId", Math.max(...sheetEls.map((s) => +s.getAttribute("sheetId"))) + 1);
    se.setAttributeNS(NS_R, "r:id", rid);
    sheetsEl.appendChild(se);
    put("xl/workbook.xml", ser(wb));
    const ct = await read("[Content_Types].xml");
    const ov = ct.createElementNS("http://schemas.openxmlformats.org/package/2006/content-types", "Override");
    ov.setAttribute("PartName", `/xl/${newPath}`);
    ov.setAttribute("ContentType", "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml");
    ct.documentElement.appendChild(ov);
    put("[Content_Types].xml", ser(ct));
    // 문서 속성의 시트 목록
    if (zip.file("docProps/app.xml")) {
      let app = await zip.file("docProps/app.xml").async("string");
      const cnt = sheetEls.length;
      app = app.replace(`<vt:i4>${cnt}</vt:i4>`, `<vt:i4>${cnt + 1}</vt:i4>`)
        .replace(/(<TitlesOfParts><vt:vector size=")(\d+)(" baseType="lpstr">)([\s\S]*?)(<\/vt:vector>)/,
          (_, a, size, b, body, end) => `${a}${+size + 1}${b}${body}<vt:lpstr>${xmlEsc(X.official_sheet)}</vt:lpstr>${end}`);
      put("docProps/app.xml", app);
    }

    const blob = await zip.generateAsync({
      type: "blob", compression: "DEFLATE",
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const [y, m, d] = D.as_of.split("-");
    return { blob, filename: `프로스포츠 관중 수(${y.slice(2)}.${m}.${d} 기준).xlsx`, skipped };
  }

  window.ExcelExport = {
    async download(D) {
      const { blob, filename, skipped } = await build(D);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      return { filename, skipped };
    },
  };
})();
