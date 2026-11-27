"""data/baseline.json 으로 종합 시트를 다시 계산해 엑셀 '종합' 시트와 대조.

1) 숫자 대조: 종목별 총 관중·총 경기·평균, 전체 총 관중·전체 평균 (8개 연도 × 17칸)
2) 수식 대조: 종합 시트 수식이 참조하는 셀이 config/leagues.yaml 의 항목 설정과 같은지
결과는 docs/phase1_대조표.md 로 저장. 하나라도 다르면 종료 코드 1.
실행: python scripts/verify_baseline.py [엑셀경로]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BASELINE_PATH, ROOT, SOURCE_XLSX, average,  # noqa: E402
                    league_season_totals, load_config, load_json, season_id)

REPORT = ROOT / "docs" / "phase1_대조표.md"
REF_RE = re.compile(r"'([^']+)'!([A-Z]+)(\d+)")


def same(excel, ours) -> bool:
    if excel in (None, "#DIV/0!"):
        return ours is None
    if ours is None:
        return False
    return abs(float(excel) - float(ours)) < 1e-6


def fmt(v, avg=False) -> str:
    if v in (None, "#DIV/0!"):
        return "-" if v is None else "#DIV/0!"
    return f"{v:,.2f}" if avg else f"{int(v):,}"


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE_XLSX
    cfg = load_config()
    base = load_json(BASELINE_PATH)
    wb_val = openpyxl.load_workbook(src, data_only=True)
    wb_f = openpyxl.load_workbook(src, data_only=False)
    wcfg = cfg["workbook"]
    sv, sf = wb_val[wcfg["summary_sheet"]], wb_f[wcfg["summary_sheet"]]

    checks = mismatches = 0
    lines = ["# Phase 1 — baseline.json ↔ 엑셀 `종합` 시트 대조표", "",
             f"- 원본: `{src.name}` (엑셀 기준일 {base['excel_as_of']})",
             f"- baseline 생성: {base['generated_at']}",
             "- 방법: baseline.json 숫자와 `config/leagues.yaml` 규칙만으로 종합 시트를 다시 계산해 엑셀에 저장된 값과 비교", ""]

    # ---------- 1) 숫자 대조 ----------
    for code, lg in cfg["leagues"].items():
        cols = lg["summary_cols"]
        lines += [f"## {lg['name']} ({code})", "",
                  "| 연도 | 엑셀 총 관중 | baseline 총 관중 | 엑셀 경기 | baseline 경기 | 엑셀 평균 | baseline 평균 | 결과 |",
                  "|---|---:|---:|---:|---:|---:|---:|:-:|"]
        for i, srow in enumerate(cfg["seasons"]):
            r = wcfg["summary_first_row"] + i
            att, games = league_season_totals(base["leagues"][code], season_id(srow, lg), lg["total"])
            avg = average(att, games)
            ex = (sv[f"{cols['attendance']}{r}"].value, sv[f"{cols['games']}{r}"].value, sv[f"{cols['average']}{r}"].value)
            ok = [same(ex[0], att), same(ex[1], games), same(ex[2], avg)]
            checks += 3
            mismatches += ok.count(False)
            lines.append(f"| {srow['row_label']} | {fmt(ex[0])} | {fmt(att)} | {fmt(ex[1])} | {fmt(games)} | "
                         f"{fmt(ex[2], True)} | {fmt(avg, True)} | {'✅' if all(ok) else '❌'} |")
        lines.append("")

    lines += ["## 전체", "", "| 연도 | 엑셀 전체 총 관중 | baseline | 엑셀 전체 평균 | baseline | 결과 |",
              "|---|---:|---:|---:|---:|:-:|"]
    for i, srow in enumerate(cfg["seasons"]):
        r = wcfg["summary_first_row"] + i
        tot_att = tot_games = 0
        for code, lg in cfg["leagues"].items():
            a, g = league_season_totals(base["leagues"][code], season_id(srow, lg), lg["total"])
            tot_att += a
            tot_games += g
        avg = average(tot_att, tot_games)
        ex_att, ex_avg = sv[f"{wcfg['overall_total_col']}{r}"].value, sv[f"{wcfg['overall_avg_col']}{r}"].value
        ok = [same(ex_att, tot_att), same(ex_avg, avg)]
        checks += 2
        mismatches += ok.count(False)
        lines.append(f"| {srow['row_label']} | {fmt(ex_att)} | {fmt(tot_att)} | {fmt(ex_avg, True)} | {fmt(avg, True)} | "
                     f"{'✅' if all(ok) else '❌'} |")
    lines.append("")

    # ---------- 2) 수식 대조 ----------
    formula_issues = []
    for code, lg in cfg["leagues"].items():
        cols = lg["summary_cols"]
        items = {it["key"]: it for it in lg["items"]}
        for i, _ in enumerate(cfg["seasons"]):
            r = wcfg["summary_first_row"] + i
            for kind, col_key in (("attendance", "attendance_col"), ("games", "games_col")):
                formula = sf[f"{cols[kind]}{r}"].value or ""
                found = sorted((s, c, int(n)) for s, c, n in REF_RE.findall(formula))
                expected = sorted((lg["sheet"], items[k][col_key], items[k]["first_row"] + i) for k in lg["total"])
                checks += 1
                if found != expected:
                    mismatches += 1
                    formula_issues.append(f"- {cols[kind]}{r}: 엑셀 `{formula}` / 설정 기대 {expected}")
    lines += ["## 수식 구조 대조", "",
              "종합 시트의 종목 합계 수식(80칸)이 참조하는 셀 목록을 설정 파일 규칙과 비교했습니다.", ""]
    lines += formula_issues or ["- ✅ 80칸 모두 설정과 같은 셀을 더하고 있음"]
    lines.append("")

    if base["formula_cells"]:
        lines += ["## 수식으로 입력된 셀 (계산값으로 저장)", "", "| 위치 | 셀 | 수식 | 저장값 |", "|---|---|---|---:|"]
        lines += [f"| {c['where']} | {c['cell']} | `{c['formula']}` | {c['value']} |" for c in base["formula_cells"]]
        lines.append("")

    verdict = (f"**결과: {checks}개 항목 중 불일치 {mismatches}개**"
               + (" → 100% 일치" if mismatches == 0 else " → 확인 필요"))
    lines.insert(5, verdict)
    lines.insert(6, "")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(verdict.replace("**", ""))
    print(f"대조표: {REPORT}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
