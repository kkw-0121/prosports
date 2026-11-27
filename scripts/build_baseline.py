"""엑셀 '프로스포츠 관중 수 양식.xlsx' → data/baseline.json 변환.

원본 엑셀은 읽기만 합니다. 실행: python scripts/build_baseline.py [엑셀경로]
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BASELINE_PATH, SOURCE_XLSX, eval_simple_formula,  # noqa: E402
                    load_config, save_json, season_id)

KST = timezone(timedelta(hours=9))


def read_number(ws_val, ws_f, coord: str, notes: list, where: str):
    """셀 값 읽기. 빈칸 → None, 수식 → 계산값(캐시 없으면 직접 계산)."""
    value = ws_val[coord].value
    raw = ws_f[coord].value
    if isinstance(raw, str) and raw.startswith("="):
        computed = eval_simple_formula(raw)
        if value is None:
            value = computed
        elif value != computed:
            raise ValueError(f"{where} {coord}: 저장된 값 {value} ≠ 수식 {raw} 계산값 {computed}")
        notes.append({"where": where, "cell": coord, "formula": raw, "value": value})
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} {coord}: 숫자가 아님 → {value!r}")
    if value < 0:
        raise ValueError(f"{where} {coord}: 음수 → {value}")
    return int(value) if float(value).is_integer() else value


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE_XLSX
    cfg = load_config()
    wb_val = openpyxl.load_workbook(src, data_only=True, read_only=False)
    wb_f = openpyxl.load_workbook(src, data_only=False, read_only=False)

    summary = wb_val[cfg["workbook"]["summary_sheet"]]
    as_of = summary[cfg["workbook"]["as_of_cell"]].value

    out = {
        "description": "엑셀에서 가져온 시즌별·항목별 합계 (확정값). 빈칸은 null.",
        "source_file": src.name,
        "excel_as_of": str(as_of),
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "leagues": {},
        "formula_cells": [],
    }

    for code, lg in cfg["leagues"].items():
        ws_v, ws_f = wb_val[lg["sheet"]], wb_f[lg["sheet"]]
        league_out = {}
        for i, srow in enumerate(cfg["seasons"]):
            sid = season_id(srow, lg)
            season_out = {}
            for item in lg["items"]:
                row = item["first_row"] + i
                # 행 머리(B열)가 시즌과 맞는지 확인 → 설정이 엑셀과 어긋나면 바로 중단
                label = ws_v[f"B{row}"].value
                if str(label).strip() != sid:
                    raise ValueError(f"{lg['sheet']} B{row} = {label!r}, 기대값 {sid!r} (config 행 번호 확인)")
                where = f"{lg['sheet']}/{sid}/{item['key']}"
                season_out[item["key"]] = {
                    "attendance": read_number(ws_v, ws_f, f"{item['attendance_col']}{row}", out["formula_cells"], where),
                    "games": read_number(ws_v, ws_f, f"{item['games_col']}{row}", out["formula_cells"], where),
                }
            league_out[sid] = season_out
        out["leagues"][code] = league_out

    save_json(BASELINE_PATH, out)
    n = sum(len(s) for lg in out["leagues"].values() for s in lg.values())
    print(f"저장: {BASELINE_PATH}  (리그 {len(out['leagues'])}개, 항목 {n}개, 수식 셀 {len(out['formula_cells'])}개, 엑셀 기준일 {as_of})")


if __name__ == "__main__":
    main()
