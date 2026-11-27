"""화면용 데이터 묶음 생성: baseline(엑셀 확정값) + data/games(수집) + data/official + status → site/data/summary.json

규칙은 config/leagues.yaml 에서 읽는다 (하드코딩 없음).
- collect 목록에 있는 시즌: 수집한 경기로 항목별 합계 계산 (WKBL은 stage_totals)
- 그 밖의 시즌: 엑셀 확정값
실행: python scripts/build_summary.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BASELINE_PATH, DATA_DIR, ROOT, average, load_config,  # noqa: E402
                    load_json, save_json, season_id)

KST = timezone(timedelta(hours=9))
OUT = ROOT / "site" / "data" / "summary.json"
STALE_HOURS = 26          # 마지막 성공이 이보다 오래되면 '지연'


def item_from_games(item: dict, games: list[dict]) -> dict:
    sel = [g for g in games if g["stage"] in item["stages"] and not g.get("pending")
           and ("division" not in item or g.get("division") == item["division"])]
    return {"attendance": sum(g["attendance"] or 0 for g in sel), "games": len(sel)}


def collected_items(lg: dict, data: dict) -> tuple[dict, list[str]]:
    games, notes = data["games"], []
    st = data.get("stage_totals")
    items = {}
    for it in lg["items"]:
        if st:   # WKBL: 관중은 시즌 합계 스냅샷 기준 (경기별 관중 미공개)
            v = st.get(it["key"], {"attendance": None, "games": 0})
            items[it["key"]] = {"attendance": v["attendance"], "games": v["games"]}
            if v["attendance"] is None:
                notes.append(f"{it['label']}: 정규/PO 관중을 나눌 수 없음 (연맹이 경기별 관중을 공개하지 않음)")
        else:
            items[it["key"]] = item_from_games(it, games)
    pending = [g for g in games if g.get("pending")]
    if pending:
        notes.append(f"관중 반영 대기 {len(pending)}경기 (연맹 집계 반영 후 포함): "
                     + ", ".join(f"{g['date']} {g['home']}-{g['away']}" for g in pending[:3]))
    return items, notes


def official_compare(lg: dict, items: dict, total: dict, official: dict | None) -> list[dict]:
    """연맹 공식 누적치 ↔ 경기별 합계 비교 목록."""
    if not official:
        return []
    labels = {it["key"]: it["label"] for it in lg["items"]}
    out = []
    for key, v in official["items"].items():
        if key == "total":
            label, mine = "시즌 전체", total["attendance"]
        elif key in items:
            label, mine = labels[key], items[key]["attendance"]
        elif key.endswith("_total"):
            stage = key[: -len("_total")]
            keys = [it["key"] for it in lg["items"] if stage in it["stages"]]
            label = {"regular": "정규리그 (남녀 합)", "postseason": "포스트시즌 (남녀 합)"}.get(stage, key)
            vals = [items[k]["attendance"] for k in keys]
            mine = None if any(x is None for x in vals) else sum(vals)
        else:
            continue
        diff = None if mine is None else v["attendance"] - mine
        out.append({"key": key, "label": label, "official": v["attendance"], "ours": mine,
                    "diff": diff, "note": v.get("note")})
    return out


def league_status(s: dict | None, now: datetime) -> dict:
    if not s:
        return {"state": "fail", "label": "실패", "message": "아직 수집 기록 없음"}
    err, ok = s.get("last_error"), s.get("last_success")
    if err and (not ok or err["at"] >= ok):
        return {"state": "fail", "label": "실패", "message": err["message"], "last_success": ok}
    if ok and now - datetime.fromisoformat(ok) > timedelta(hours=STALE_HOURS):
        return {"state": "delay", "label": "지연", "message": f"마지막 성공 {ok[:16].replace('T', ' ')}",
                "last_success": ok}
    return {"state": "ok", "label": "정상", "message": f"마지막 성공 {ok[:16].replace('T', ' ')}",
            "last_success": ok}


def main() -> None:
    cfg = load_config()
    base = load_json(BASELINE_PATH)
    status_path = DATA_DIR / "status.json"
    status = load_json(status_path) if status_path.exists() else {"leagues": {}}
    now = datetime.now(KST)

    leagues_out, latest_collect = {}, None
    for code, lg in cfg["leagues"].items():
        seasons_out = {}
        for srow in cfg["seasons"]:
            sid = season_id(srow, lg)
            src = "baseline"
            notes, official, collected_at = [], None, None
            gpath = DATA_DIR / "games" / f"{code}_{sid}.json"
            if gpath.exists():
                # 수집 파일이 있으면 그 값을 씀. collect 목록에 있으면 '진행 중'(collected),
                # 시즌이 끝나 목록에서 뺐으면 마지막 수집값으로 고정된 확정값(final)
                data = load_json(gpath)
                items, notes = collected_items(lg, data)
                src, collected_at = ("collected" if sid in lg["collect"] else "final"), data["collected_at"]
                if src == "collected":
                    latest_collect = max(latest_collect or collected_at, collected_at)
                opath = DATA_DIR / "official" / f"{code}_{sid}.json"
                official = load_json(opath) if opath.exists() else None
                last_game = max((g["date"] for g in data["games"]), default=None)
            else:
                items = {k: {"attendance": v["attendance"], "games": v["games"]}
                         for k, v in base["leagues"][code][sid].items()}
                last_game = None
                if sid in lg["collect"]:
                    notes.append("아직 수집 기록 없음 → 엑셀 값 표시")
            vals = [items[k] for k in lg["total"]]
            att = None if any(v["attendance"] is None and (v["games"] or 0) > 0 for v in vals) \
                else sum(v["attendance"] or 0 for v in vals)
            games = sum(v["games"] or 0 for v in vals)
            total = {"attendance": att, "games": games,
                     "average": None if att is None else average(att, games)}
            for v in items.values():
                v["average"] = None if v["attendance"] is None else average(v["attendance"] or 0, v["games"] or 0)
            seasons_out[sid] = {
                "row": srow["row_label"], "source": src, "items": items, "total": total,
                "has_data": games > 0, "collected_at": collected_at, "last_game": last_game,
                "official": official_compare(lg, items, total, official) if official else [],
                "official_status": ("provided" if official else
                                    ("not_provided" if src in ("collected", "final") else "baseline")),
                "notes": notes,
            }
        leagues_out[code] = {
            "code": code, "name": lg["name"], "abbr": lg.get("abbr", code), "sheet": lg["sheet"],
            "items": [{"key": it["key"], "label": it["label"]} for it in lg["items"]],
            "total_items": lg["total"], "seasons": seasons_out,
            "status": league_status(status["leagues"].get(code), now),
        }

    # 종합 행 (연도별 전체)
    rows = []
    for srow in cfg["seasons"]:
        per = {code: leagues_out[code]["seasons"][season_id(srow, lg)]["total"]
               for code, lg in cfg["leagues"].items()}
        att = sum(v["attendance"] or 0 for v in per.values())
        games = sum(v["games"] for v in per.values())
        rows.append({"row": srow["row_label"], "year": srow["year"], "split": srow["split"],
                     "attendance": att, "games": games, "average": average(att, games),
                     "complete": all(v["attendance"] is not None for v in per.values())})

    as_of = (datetime.fromisoformat(latest_collect) if latest_collect else now)
    save_json(OUT, {
        "generated_at": now.isoformat(timespec="seconds"),
        "as_of": as_of.strftime("%Y-%m-%d"),
        "excel_as_of": base["excel_as_of"],
        "rows": rows,
        "leagues": leagues_out,
        "excel": {   # 엑셀 다운로드 시 채울 칸 (config 그대로 전달)
            "template": "template/양식.xlsx",
            "summary_sheet": cfg["workbook"]["summary_sheet"],
            "as_of_cell": cfg["workbook"]["as_of_cell"],
            "summary_first_row": cfg["workbook"]["summary_first_row"],
            "overall_total_col": cfg["workbook"]["overall_total_col"],
            "overall_avg_col": cfg["workbook"]["overall_avg_col"],
            "official_sheet": "공식 집계 대조",
            "seasons": [s["row_label"] for s in cfg["seasons"]],
            "leagues": {code: {"sheet": lg["sheet"], "season_format": lg["season_format"],
                               "summary_cols": lg["summary_cols"], "total": lg["total"],
                               "items": [{k: it[k] for k in ("key", "label", "first_row", "attendance_col", "games_col")}
                                         for it in lg["items"]]}
                        for code, lg in cfg["leagues"].items()},
        },
    })
    print(f"저장: {OUT}")


if __name__ == "__main__":
    main()
