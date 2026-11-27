"""다운로드한 엑셀 ↔ 원본 양식 대조.

python scripts/compare_excel.py <원본.xlsx> <다운로드.xlsx> [보고서.md]

확인 항목
 1) 파일 구성: 원본의 모든 부품(그림·텍스트 상자·인쇄설정·테마 등)이 그대로(바이트 동일) 남아 있는지
 2) 기존 6개 시트: 서식(글꼴·채우기·테두리·정렬·표시형식), 병합 셀, 열 너비, 행 높이, 수식이 모두 같은지
 3) 값이 바뀐 칸이 '바뀌어도 되는 칸'(자동 수집 시즌 입력 칸, 기준일, 종합 수식의 저장 결과값)뿐인지
 4) 종합 시트 수식을 다시 계산한 값이 저장된 결과값과 같은지, 새 시트 '공식 집계 대조'가 맨 뒤에 있는지
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_config, season_id  # noqa: E402

EXPECTED_CHANGED_PARTS = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels", "[Content_Types].xml",
                          "docProps/app.xml", "xl/styles.xml"}


def style_sig(c):
    f, fl, b, a = c.font, c.fill, c.border, c.alignment
    side = lambda s: (s.style, s.color.rgb if s and s.color else None) if s else None  # noqa: E731
    return (f.name, f.sz, f.b, f.i, f.u, f.color.rgb if f.color else None, f.color.theme if f.color else None,
            fl.fill_type, fl.fgColor.rgb, fl.fgColor.theme, fl.fgColor.tint,
            side(b.left), side(b.right), side(b.top), side(b.bottom),
            a.horizontal, a.vertical, a.wrap_text, a.indent, c.number_format, c.protection.locked)


def allowed_cells(cfg) -> set[tuple[str, str]]:
    ok = set()
    wb = cfg["workbook"]
    ok.add((wb["summary_sheet"], wb["as_of_cell"]))
    for i, srow in enumerate(cfg["seasons"]):
        r = wb["summary_first_row"] + i
        for lg in cfg["leagues"].values():
            for col in lg["summary_cols"].values():
                ok.add((wb["summary_sheet"], f"{col}{r}"))
            if season_id(srow, lg) in lg["collect"]:
                for it in lg["items"]:
                    ok.add((lg["sheet"], f"{it['attendance_col']}{it['first_row'] + i}"))
                    ok.add((lg["sheet"], f"{it['games_col']}{it['first_row'] + i}"))
        ok.add((wb["summary_sheet"], f"{wb['overall_total_col']}{r}"))
        ok.add((wb["summary_sheet"], f"{wb['overall_avg_col']}{r}"))
    return ok


def main() -> int:
    orig_p, new_p = Path(sys.argv[1]), Path(sys.argv[2])
    report = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    cfg = load_config()
    problems, lines = [], []

    # 1) 파일 구성
    zo, zn = zipfile.ZipFile(orig_p), zipfile.ZipFile(new_p)
    no, nn = set(zo.namelist()), set(zn.namelist())
    missing = sorted(no - nn)
    added = sorted(nn - no)
    if missing:
        problems.append(f"원본에 있던 부품이 빠짐: {missing}")
    sheet_parts = {p for p in no if p.startswith("xl/worksheets/sheet")}
    changed = sorted(p for p in no & nn if zo.read(p) != zn.read(p))
    unexpected = [p for p in changed if p not in EXPECTED_CHANGED_PARTS and p not in sheet_parts]
    if unexpected:
        problems.append(f"바뀌면 안 되는 부품이 바뀜: {unexpected}")
    same_drawings = all(zo.read(p) == zn.read(p) for p in no if p.startswith(("xl/drawings/", "xl/media/")))
    lines += ["## 1. 파일 구성", "",
              f"- 원본 부품 {len(no)}개 중 빠진 것: {len(missing)}개",
              f"- 추가된 부품: {', '.join(added) or '없음'}",
              f"- 내용이 바뀐 부품: {', '.join(changed)}",
              f"- 텍스트 상자·그림(drawings, media) 바이트 동일: {'✅' if same_drawings else '❌'}",
              f"- 그 밖의 부품(테마·인쇄설정·계산체인 등) 바이트 동일: {'✅' if not unexpected else '❌ ' + str(unexpected)}", ""]
    if not same_drawings:
        problems.append("텍스트 상자/그림이 바뀜")

    # 2)~3) 시트 비교
    wo = openpyxl.load_workbook(orig_p)
    wn = openpyxl.load_workbook(new_p)
    wnv = openpyxl.load_workbook(new_p, data_only=True)
    allow = allowed_cells(cfg)
    lines += ["## 2. 기존 시트 서식·구조", "", "| 시트 | 칸 수 | 서식 다른 칸 | 수식 다른 칸 | 병합 | 열 너비 | 행 높이 | 값 바뀐 칸 (허용 / 허용 외) |",
              "|---|---:|---:|---:|:-:|:-:|:-:|---|"]
    value_changes = []
    for name in wo.sheetnames:
        so, sn = wo[name], wn[name]
        style_diff = formula_diff = 0
        changed_ok, changed_bad = [], []
        coords = {c.coordinate for row in so.iter_rows() for c in row} | {c.coordinate for row in sn.iter_rows() for c in row}
        for coord in coords:
            co, cn = so[coord], sn[coord]
            if style_sig(co) != style_sig(cn):
                style_diff += 1
                problems.append(f"{name}!{coord} 서식 다름")
            fo = co.value if isinstance(co.value, str) and co.value.startswith("=") else None
            fn = cn.value if isinstance(cn.value, str) and cn.value.startswith("=") else None
            if fo != fn:
                formula_diff += 1
                problems.append(f"{name}!{coord} 수식 다름: {fo} → {fn}")
            elif fo is None and co.value != cn.value:
                (changed_ok if (name, coord) in allow else changed_bad).append(coord)
                value_changes.append((name, coord, co.value, cn.value))
        merged = sorted(map(str, so.merged_cells.ranges)) == sorted(map(str, sn.merged_cells.ranges))
        widths = {k: v.width for k, v in so.column_dimensions.items()} == {k: v.width for k, v in sn.column_dimensions.items()}
        heights = {k: v.height for k, v in so.row_dimensions.items()} == {k: v.height for k, v in sn.row_dimensions.items()}
        for ok, what in ((merged, "병합 셀"), (widths, "열 너비"), (heights, "행 높이")):
            if not ok:
                problems.append(f"{name} {what} 다름")
        if changed_bad:
            problems.append(f"{name} 바뀌면 안 되는 칸이 바뀜: {changed_bad}")
        lines.append(f"| {name} | {len(coords)} | {style_diff} | {formula_diff} | {'✅' if merged else '❌'} | "
                     f"{'✅' if widths else '❌'} | {'✅' if heights else '❌'} | {len(changed_ok)} / {len(changed_bad)} |")
    lines.append("")

    lines += ["## 3. 값이 바뀐 칸 (모두 자동 수집 시즌 입력 칸 또는 기준일)", "", "| 시트 | 칸 | 원본(양식) | 다운로드 |", "|---|---|---:|---:|"]
    lines += [f"| {n} | {c} | {o if o is not None else '(빈칸)'} | {v} |" for n, c, o, v in sorted(value_changes)]
    lines.append("")

    # 4) 종합 수식 결과값 검증 (openpyxl 로 직접 다시 계산)
    wbc = cfg["workbook"]
    sv = wnv[wbc["summary_sheet"]]
    calc_bad = 0
    for i, srow in enumerate(cfg["seasons"]):
        r = wbc["summary_first_row"] + i
        all_a = all_g = 0
        for lg in cfg["leagues"].values():
            ls = wnv[lg["sheet"]]
            items = {it["key"]: it for it in lg["items"]}
            a = sum((ls[f"{items[k]['attendance_col']}{items[k]['first_row'] + i}"].value or 0) for k in lg["total"])
            g = sum((ls[f"{items[k]['games_col']}{items[k]['first_row'] + i}"].value or 0) for k in lg["total"])
            cols = lg["summary_cols"]
            exp = [a, g, (a / g if g else "#DIV/0!")]
            got = [sv[f"{cols['attendance']}{r}"].value, sv[f"{cols['games']}{r}"].value, sv[f"{cols['average']}{r}"].value]
            for e, x in zip(exp, got):
                if (isinstance(e, str) and e != x) or (not isinstance(e, str) and (x is None or abs(e - x) > 1e-6)):
                    calc_bad += 1
                    problems.append(f"종합 {srow['row_label']} {lg['name']}: 기대 {exp} / 저장 {got}")
                    break
            all_a += a
            all_g += g
        if sv[f"{wbc['overall_total_col']}{r}"].value != all_a:
            calc_bad += 1
            problems.append(f"종합 {srow['row_label']} 전체 총 관중 불일치")
    full_calc = b'fullCalcOnLoad="1"' in zn.read("xl/workbook.xml")
    new_sheets = wn.sheetnames[len(wo.sheetnames):]
    order_ok = wn.sheetnames[:len(wo.sheetnames)] == wo.sheetnames and new_sheets == ["공식 집계 대조"]
    lines += ["## 4. 종합 시트·새 시트", "",
              f"- 종합 시트 수식 결과값을 다시 계산해 대조: 불일치 {calc_bad}건",
              f"- 기준일 칸 {wbc['as_of_cell']}: '{wo[wbc['summary_sheet']][wbc['as_of_cell']].value}' → '{sv[wbc['as_of_cell']].value}'",
              f"- 엑셀이 열 때 수식 전체 재계산 설정(fullCalcOnLoad): {'✅' if full_calc else '❌'}",
              f"- 시트 순서: 기존 6개 그대로 + 맨 뒤 {new_sheets} {'✅' if order_ok else '❌'}", ""]
    if not full_calc:
        problems.append("fullCalcOnLoad 없음")
    if not order_ok:
        problems.append(f"시트 순서 이상: {wn.sheetnames}")

    verdict = "✅ 서식 차이 없음 (바뀐 것은 숫자 칸·기준일·새 시트뿐)" if not problems else f"❌ 문제 {len(problems)}건"
    out = [f"# 엑셀 다운로드 ↔ 원본 양식 대조", "", f"- 원본: `{orig_p.name}`", f"- 다운로드: `{new_p.name}`",
           f"- **결과: {verdict}**", ""] + lines
    if problems:
        out += ["## 문제 목록", ""] + [f"- {p}" for p in problems[:100]]
    text = "\n".join(out)
    if report:
        report.write_text(text, encoding="utf-8")
    print(verdict)
    for p in problems[:30]:
        print(" -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
