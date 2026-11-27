"""모든 리그 수집 실행. 한 리그가 실패해도 나머지는 계속, 하나라도 실패하면 종료 코드 1.

python -m scrapers.run_all                      # config 의 collect 시즌 전부
python -m scrapers.run_all --league KBL         # 한 리그만
python -m scrapers.run_all --league KBO --season 2026 --dry-run   # 저장 없이 시험 수집
"""
from __future__ import annotations

import argparse
import importlib
import sys
import traceback

from scrapers.base import (CollectError, cleanup_raw, load_config, save_json, save_result,
                           summarize, update_status, validate)

MODULES = {"KBO": "kbo", "KLEAGUE": "kleague", "KBL": "kbl", "WKBL": "wkbl", "KOVO": "kovo"}


def run_league(code: str, seasons: list[str], dry_run: bool, dump_dir) -> bool:
    mod = importlib.import_module(f"scrapers.{MODULES[code]}")
    summary = {}
    try:
        for season in seasons:
            print(f"[{code} {season}] 수집 시작")
            res = mod.collect(season)
            if dry_run:
                warnings = validate(code, season, res.games)
                info = summarize(res, warnings)
                if dump_dir:
                    save_json(dump_dir / f"{code}_{season}.json",
                              {"games": res.games, "official": res.official, "notes": res.notes, **res.extra})
            else:
                info = save_result(code, season, res)
            summary[season] = info
            print(f"[{code} {season}] 경기 {info['games']}건 / 관중 {info['attendance']:,}명"
                  + (f" / 경고 {len(info['warnings'])}건" if info["warnings"] else ""))
            for w in info["warnings"][:10]:
                print(f"    경고: {w}")
            for n in res.notes:
                print(f"    참고: {n}")
        if not dry_run:
            update_status(code, True, summary)
        return True
    except Exception as e:  # noqa: BLE001 — 리그 단위로 격리
        msg = str(e) if isinstance(e, CollectError) else f"{type(e).__name__}: {e}"
        print(f"[{code}] 실패: {msg}", file=sys.stderr)
        if not isinstance(e, CollectError):
            traceback.print_exc()
        if not dry_run:
            update_status(code, False, msg)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", choices=list(MODULES))
    ap.add_argument("--season")
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 출력")
    ap.add_argument("--dump", help="--dry-run 결과 JSON을 저장할 폴더")
    a = ap.parse_args()
    cfg = load_config()
    leagues = [a.league] if a.league else list(MODULES)
    dump_dir = None
    if a.dump:
        from pathlib import Path
        dump_dir = Path(a.dump)
    failed = []
    for code in leagues:
        seasons = [a.season] if a.season else cfg["leagues"][code]["collect"]
        if not run_league(code, seasons, a.dry_run, dump_dir):
            failed.append(code)
    if not a.dry_run:
        cleanup_raw()
    if failed:
        print(f"실패한 리그: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("모든 리그 수집 성공")
    return 0


if __name__ == "__main__":
    sys.exit(main())
