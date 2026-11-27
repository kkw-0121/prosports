"""KOVO 수집기.

KOVO 홈페이지 '일정 및 결과' 화면을 헤드리스 브라우저로 열고, 화면이 받아온 경기 목록(관중 수 포함)을 읽는다.
(API를 직접 호출하지 않고, 공개 화면이 받은 응답만 사용)

- 리그 코드: 201 정규리그 → regular / 202 플레이오프·203 챔피언결정전·204 준플레이오프 → postseason
- 올스타전: '올스타전 일정' 화면 (gcode 999, 리그 801) → allstar, division common
- 남자부(gender 1) → men / 여자부(gender 2) → women
- 컵대회·기타매치는 다른 메뉴라 조회하지 않음
- 공식 누적치: 기록 > 관중현황 (시즌 종료 후에만 숫자가 나옴)
"""
from __future__ import annotations

import re

from scrapers.base import CollectError, Http, Result, dump, to_int
from scrapers.browser import open_page, pause

SITE = "https://kovo.co.kr"
SCHEDULE = SITE + "/games/v-leagues/schedules?season={code}&gender=all&league={league}"
ALLSTAR = SITE + "/games/all-stars/schedules?season={code}"
AUDIENCES = SITE + "/stats/audiences"
STAGE = {"201": "regular", "202": "postseason", "203": "postseason", "204": "postseason"}
DIVISION = {"1": "men", "2": "women"}


def _capture(page, url: str, match) -> dict:
    """url 을 열고, 화면이 받은 응답 중 match(url) 에 맞는 JSON 을 반환."""
    with page.expect_response(lambda r: match(r.url) and r.status == 200, timeout=45_000) as info:
        page.goto(url)
    body = info.value.json()
    page.wait_for_load_state("networkidle")
    pause()
    return body.get("payload", body)


def _rows(payload: dict, what: str) -> list[dict]:
    content = payload.get("content") or []
    total = (payload.get("page") or {}).get("totalElements")
    if total is not None and total != len(content):
        raise CollectError(f"KOVO {what}: 목록이 잘림 ({len(content)}/{total}건)")
    return content


def _finished(r: dict) -> bool:
    return max(r.get("hspoint") or 0, r.get("aspoint") or 0) >= 3 or bool(r.get("result"))


def _official(page, season: str) -> dict | None:
    page.goto(AUDIENCES)
    page.wait_for_load_state("networkidle")
    pause(2)
    label = season.replace("-", "~")[:5] + season[-2:] + "시즌"          # '2025-2026' → '2025~26시즌'
    for tr in page.locator("table tr").all():
        cells = [c.strip() for c in tr.locator("th, td").all_inner_texts()]
        if cells and cells[0] == label:
            # 구분 | 컵대회 | 정규리그 | 올스타전 | 포스트시즌 | 계 | 기타매치 | 합계
            if len(cells) < 6 or not re.search(r"\d", cells[2]):
                return None                                  # '시즌 종료 후 업데이트 예정'
            num = lambda v: to_int(v) if re.search(r"\d", v) else 0     # noqa: E731
            reg, allstar, ps, site_total = num(cells[2]), num(cells[3]), num(cells[4]), num(cells[5])
            # 전체는 표의 '계' 칸이 아니라 항목 합으로 계산 (2022-23처럼 '계' 칸이 틀린 시즌이 있음)
            total = {"attendance": reg + allstar + ps, "games": None,
                     "note": "KOVO 관중현황 정규리그+올스타전+포스트시즌 합"}
            if site_total != total["attendance"]:
                total["site_total"] = site_total
                total["note"] += (f" (표의 '계' 칸은 {site_total:,}명으로 항목 합과 "
                                  f"{site_total - total['attendance']:+,}명 다름 → 항목 합 사용)")
            return {"regular_total": {"attendance": reg, "games": None, "note": "남녀부 합산"},
                    "allstar": {"attendance": allstar, "games": None},
                    "postseason_total": {"attendance": ps, "games": None, "note": "남녀부 합산"},
                    "total": total}
    return None


def collect(season: str) -> Result:
    http = Http("KOVO")
    target = season.replace("-", "~")
    games, notes, raw = [], [], {}
    with open_page() as page:
        # 시즌별 리그 목록 (정규·PO·챔프전·준PO 등). 이 응답은 시즌마다 리그 구성을 알려줌
        season_list = _capture(page, SCHEDULE.format(code="", league="201"),
                               lambda u: "stat/season-list?gcode=001" in u)
        info = next((s for s in season_list if target in (s.get("seasonName") or "")), None)
        if info is None:
            raise CollectError(f"KOVO 시즌 목록에 {season} 없음")
        code = info["seasonCode"]
        leagues = [{"league": x["leagueCode"], "name": x["leagueName"]} for x in info.get("leagues") or []]
        if not any(lg["league"] == "201" for lg in leagues):
            raise CollectError(f"KOVO {season} 리그 목록에 정규리그가 없음: {leagues}")
        skipped = [(x["league"], x["name"]) for x in leagues if x["league"] not in STAGE and x["league"] not in ("200", "801")]
        if skipped:
            notes.append(f"집계하지 않는 리그: {skipped}")
        for lg in leagues:
            lc = lg["league"]
            if lc not in STAGE:
                continue
            payload = _capture(page, SCHEDULE.format(code=code, league=lc),
                               lambda u, lc=lc: f"game-schedule?gcode=001&seasonCode={code}&leagueCode={lc}" in u)
            raw[lc] = payload
            for r in _rows(payload, lg["name"]):
                if r.get("seasonCode") != code or r.get("leagueCode") != lc:
                    raise CollectError(f"KOVO 다른 시즌/리그 경기가 섞임: {r.get('seasonCode')}/{r.get('leagueCode')}")
                if not _finished(r):
                    continue
                if r.get("gender") not in DIVISION:
                    raise CollectError(f"KOVO 남녀부 구분 없음: {r}")
                games.append({
                    "game_id": f"{code}-{lc}-{r['gender']}-{r['gnum']}", "date": r["gdate"],
                    "stage": STAGE[lc], "division": DIVISION[r["gender"]], "league_name": lg["name"],
                    "home": r.get("hsname"), "away": r.get("asname"), "venue": r.get("place"),
                    "attendance": int(r.get("spectators") or 0),
                })
        payload = _capture(page, ALLSTAR.format(code=code),
                           lambda u: f"game-schedule?gcode=999&seasonCode={code}&leagueCode=801" in u)
        raw["801"] = payload
        # 올스타전은 남자부·여자부 경기가 한 행사(같은 날·같은 체육관, 같은 관중 수)로 두 줄 나옴 → 1경기로 합침
        events: dict[tuple, dict] = {}
        for r in _rows(payload, "올스타전"):
            if not r.get("spectators"):
                continue
            key = (r["gdate"], r.get("place"))
            ev = events.get(key)
            if ev is None:
                events[key] = {
                    "game_id": f"{code}-801-{r['gdate']}", "date": r["gdate"], "stage": "allstar",
                    "division": "common", "league_name": "올스타전", "parts": [r["gnum"]],
                    "home": r.get("hsname"), "away": r.get("asname"), "venue": r.get("place"),
                    "attendance": int(r["spectators"]),
                }
            elif ev["attendance"] != int(r["spectators"]):
                raise CollectError(f"KOVO 올스타전 같은 행사인데 관중 수가 다름: {ev['attendance']} / {r['spectators']}")
            else:
                ev["parts"].append(r["gnum"])
        games += list(events.values())
        official = _official(page, season)
    http.save_raw(f"schedule_{code}.json", dump(raw))
    if official is None:
        notes.append("KOVO 관중현황은 시즌 종료 후에 공개됨 → 공식 누적치 미제공")
    return Result(games=games, source_url=SCHEDULE.format(code=code, league="201"), official=official, notes=notes)
