"""공통 도우미: 설정 파일 읽기, 경로, 집계 계산."""
from __future__ import annotations

import ast
import json
import operator
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "leagues.yaml"
DATA_DIR = ROOT / "data"
BASELINE_PATH = DATA_DIR / "baseline.json"
SOURCE_XLSX = ROOT / "프로스포츠 관중 수 양식.xlsx"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def season_id(season_row: dict, league_cfg: dict) -> str:
    """종합 시트 행 → 리그별 시즌 표기 (KBO '2026' / KBL '2025-2026')."""
    return season_row[league_cfg["season_format"]]


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}


def eval_simple_formula(formula: str) -> int | float:
    """'=1+2+4+6' 같은 숫자 사칙연산 수식만 계산 (셀 참조가 있으면 오류)."""
    def _ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_ev(node.left), _ev(node.right))
        raise ValueError(f"계산할 수 없는 수식: {formula}")
    return _ev(ast.parse(formula.lstrip("="), mode="eval").body)


def league_season_totals(baseline_league: dict, season: str, total_items: list[str]) -> tuple[int, int]:
    """종목 합계 (엑셀처럼 빈칸은 0으로 더함)."""
    items = baseline_league.get(season, {})
    att = sum((items.get(k, {}).get("attendance") or 0) for k in total_items)
    games = sum((items.get(k, {}).get("games") or 0) for k in total_items)
    return att, games


def average(att: int, games: int) -> float | None:
    """평균 = 총 관중 ÷ 총 경기. 경기 수 0이면 None(화면에는 '-')."""
    return att / games if games else None
