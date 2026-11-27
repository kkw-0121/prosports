"""KBL 수집기.

KBL 홈페이지 기록 > 관중현황 화면을 헤드리스 브라우저로 열고,
'팀 관중현황'에서 구단을 하나씩 선택해 화면이 받아온 경기별 관중 목록을 읽는다.
(데이터 업체 API를 직접 호출하지 않고, 공개 화면이 받은 응답만 사용)

- 경기구분: 정규경기 → regular / 플레이오프·챔피언결정전 → postseason
- 공식 누적치: '전체 관중현황'의 시즌 합계 (정규+PO 합산)
"""
from __future__ import annotations

from scrapers.base import CollectError, Http, Result, dump
from scrapers.browser import open_page, pause

PAGE_URL = "https://www.kbl.or.kr/record/crowd"
STAGE = {"정규경기": "regular", "플레이오프": "postseason", "챔피언결정전": "postseason"}


def _date(season: str, mmdd: str) -> str:
    """'10.18' + '2026-2027' → '2026-10-18' (9월 이후는 앞 연도, 그 전은 뒤 연도)."""
    first, second = season.split("-")
    mm, dd = mmdd.split(".")
    year = first if int(mm) >= 9 else second
    return f"{year}-{int(mm):02d}-{int(dd):02d}"


def collect(season: str) -> Result:
    http = Http("KBL")
    captured: dict[str, dict] = {}
    crowd_all = {}

    def on_response(resp):
        if "/Attendance/" not in resp.url or resp.status != 200:
            return
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            return
        data = body.get("data", body) if isinstance(body, dict) else {}
        if "/crowd-all" in resp.url:
            crowd_all["rows"] = data.get("crowdAll") or []

    with open_page() as page:
        page.on("response", on_response)
        page.goto(PAGE_URL)
        page.wait_for_load_state("networkidle")
        pause(2)
        page.locator("select").first.select_option("team")
        page.wait_for_load_state("networkidle")
        pause()
        selects = page.locator("select").all()
        if len(selects) < 4:
            raise CollectError("KBL 팀 관중현황 선택 칸을 찾지 못함 (화면 구조 변경 가능성)")
        team_sel, season_sel = selects[1], selects[2]
        seasons = season_sel.evaluate("s => [...s.options].map(o => [o.value, o.text.trim()])")
        code = next((v for v, t in seasons if t == season), None)
        if code is None:
            raise CollectError(f"KBL 시즌 목록에 {season} 없음")
        season_sel.select_option(code)
        pause()
        teams = [(v, t) for v, t in team_sel.evaluate("s => [...s.options].map(o => [o.value, o.text.trim()])")
                 if v and v != "00"]
        if len(teams) < 8:
            raise CollectError(f"KBL 구단 목록이 이상함: {teams}")
        for value, name in teams:
            want = f"teamCode={value}&"
            try:
                with page.expect_response(lambda r: want in r.url and "listCn=10000" in r.url, timeout=30_000) as info:
                    team_sel.select_option(value)
                body = info.value.json()
            except Exception as e:  # noqa: BLE001
                raise CollectError(f"KBL {name} 관중 목록을 받지 못함: {e}") from e
            captured[value] = body.get("data", body)
            page.wait_for_load_state("networkidle")
            pause()

    http.save_raw(f"crowd_team_{season}.json", dump(captured))
    http.save_raw("crowd_all.json", dump(crowd_all))

    games, notes = [], []
    for team, data in captured.items():
        for r in data.get("crowdTeam") or []:
            if r.get("seasonName") != season:
                continue
            stage = STAGE.get(r.get("gameName"))
            if stage is None:
                raise CollectError(f"KBL 알 수 없는 경기구분: {r.get('gameName')} ({r})")
            games.append({
                "game_id": f"{season}-{r['gameName']}-{r['gameNo']}",
                "date": _date(season, r["gameDate"]), "stage": stage, "round": r.get("gameRound"),
                "home": r.get("teamName"), "away": None, "venue": r.get("stadiumCode"),
                "attendance": int(r["enterCrowd"]),
            })
    official = None
    for r in crowd_all.get("rows", []):
        if r.get("seasonName") == season:
            official = {"total": {"attendance": int(r["crowdSum"]), "games": None,
                                  "note": "KBL 관중현황 '전체 관중현황' 시즌 합계 (정규+PO)"}}
    if official is None:
        notes.append("전체 관중현황에서 이 시즌 합계를 찾지 못함")
    notes.append("KBL 관중 목록에는 원정팀 정보가 없어 away는 비어 있음")
    return Result(games=games, source_url=PAGE_URL, official=official, notes=notes)
