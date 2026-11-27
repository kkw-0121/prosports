"""'전 시즌 같은 시점 대비' 비교용으로 지난 시즌 경기별 관중을 한 번 수집해 data/reference/ 에 저장.

- 자동 수집 중인 시즌(collect)마다 바로 전 시즌을 찾고, 그 시즌의 수집 파일(data/games)이 없을 때만 수집
- 합계·엑셀 값에는 쓰지 않음 (지난 시즌 합계는 계속 엑셀 확정값)
- WKBL은 경기별 관중을 공개하지 않아 제외
실행: python scripts/collect_reference.py [리그코드 ...]
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from common import load_config, save_json, season_id  # noqa: E402
from scrapers.base import now_kst, validate  # noqa: E402
from scrapers.run_all import MODULES  # noqa: E402

REF_DIR = ROOT / "data" / "reference"
SKIP = {"WKBL"}


def previous_seasons(cfg: dict, code: str) -> list[str]:
    lg = cfg["leagues"][code]
    ids = [season_id(s, lg) for s in cfg["seasons"]]
    out = []
    for sid in lg["collect"]:
        i = ids.index(sid)
        if i > 0 and ids[i - 1] not in out:
            out.append(ids[i - 1])
    return out


def main() -> int:
    cfg = load_config()
    codes = sys.argv[1:] or [c for c in MODULES if c not in SKIP]
    failed = []
    for code in codes:
        for prev in previous_seasons(cfg, code):
            if (ROOT / "data" / "games" / f"{code}_{prev}.json").exists():
                print(f"[{code} {prev}] 수집 파일이 이미 있어 건너뜀")
                continue
            print(f"[{code} {prev}] 비교용 수집…", flush=True)
            try:
                res = importlib.import_module(f"scrapers.{MODULES[code]}").collect(prev)
                warnings = validate(code, prev, res.games)
            except Exception as e:  # noqa: BLE001
                print(f"  실패: {e}")
                failed.append(f"{code} {prev}")
                continue
            save_json(REF_DIR / f"{code}_{prev}.json",
                      {"league": code, "season": prev, "collected_at": now_kst(),
                       "purpose": "전 시즌 같은 시점 비교용 (합계에는 쓰지 않음)",
                       "source_url": res.source_url, "games": sorted(res.games, key=lambda g: (g["date"], g["game_id"]))})
            print(f"  저장: {len(res.games)}경기 {sum(g['attendance'] for g in res.games):,}명"
                  + (f", 경고 {len(warnings)}건" if warnings else ""))
    if failed:
        print("실패:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
