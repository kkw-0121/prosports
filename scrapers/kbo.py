"""KBO 수집기.

- 정규시즌: 기록 > 관중현황 > 일자별 (GraphDaily.aspx, ASP.NET 폼 POST)
- 포스트시즌(와일드카드·준PO·PO·KS)·올스타전: 일정 목록(/ws GetScheduleList) → 경기별 게임센터(/ws GetScoreBoardScroll)
"""
from __future__ import annotations

import json
import re
from collections import Counter

from bs4 import BeautifulSoup

from scrapers.base import CollectError, Http, Result, load_previous, to_int

BASE = "https://www.koreabaseball.com"
DAILY_URL = f"{BASE}/Record/Crowd/GraphDaily.aspx"
SCHEDULE_URL = f"{BASE}/Schedule/Schedule.aspx"
WS_LIST = f"{BASE}/ws/Schedule.asmx/GetScheduleList"
WS_BOARD = f"{BASE}/ws/Schedule.asmx/GetScoreBoardScroll"
GAMECENTER = f"{BASE}/Schedule/GameCenter/Main.aspx"

PS_SERIES = ["4", "3", "5", "7"]        # 와일드카드, 준PO, PO, 한국시리즈
ALLSTAR_SERIES = "9"
PS_MONTHS = ["09", "10", "11"]
ALLSTAR_MONTHS = ["06", "07", "08"]


def _json(resp) -> dict:
    try:
        return json.loads(resp.content.decode("utf-8-sig"))
    except ValueError as e:
        raise CollectError(f"KBO 응답이 JSON이 아님 ({resp.url}) — 사이트 구조 변경 가능성") from e


# ---------------------------------------------------------------- 정규시즌
def collect_regular(http: Http, season: str) -> tuple[list[dict], dict | None]:
    page = http.get(DAILY_URL, raw_name="daily_get.html")
    soup = BeautifulSoup(page.text, "html.parser")
    form = {i["name"]: i.get("value", "") for i in soup.select("input[type=hidden]") if i.get("name")}
    season_sel = None
    for sel in soup.find_all("select"):
        name = sel.get("name", "")
        opts = [o.get("value") for o in sel.find_all("option")]
        if name.endswith("ddlSeason"):
            season_sel = name
            if season not in opts:
                years = [o for o in opts if o and o.isdigit()]
                if years and season > max(years):
                    return [], None      # 아직 시즌 선택지에 없음 = 시즌 시작 전
                raise CollectError(f"KBO 일자별 관중 시즌 목록에 {season} 없음")
            form[name] = season
        else:
            form[name] = opts[0] if opts else ""
    if not season_sel:
        raise CollectError("KBO 일자별 관중 페이지에서 시즌 선택 칸을 찾지 못함")
    btn = soup.find("input", attrs={"name": re.compile(r"btnSearch$")})
    if btn:
        form[btn["name"]] = btn.get("value", "검색")

    resp = http.post(DAILY_URL, raw_name=f"daily_{season}.html", data=form)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    if not table:
        raise CollectError("KBO 일자별 관중 표가 없음")

    games, official, seq = [], None, Counter()
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
        if len(cells) == 1 and "합계" in cells[0]:
            m = re.search(r"경기수\s*:\s*([\d,]+).*?합계\s*:\s*([\d,]+)", cells[0])
            if m:
                official = {"regular": {"games": to_int(m.group(1)), "attendance": to_int(m.group(2))}}
            continue
        if len(cells) != 6 or not re.fullmatch(r"\d{4}/\d{2}/\d{2}", cells[0]):
            continue
        date = cells[0].replace("/", "-")
        if not date.startswith(season):
            raise CollectError(f"KBO {season} 요청에 다른 시즌 날짜가 섞임: {date}")
        home, away, venue = cells[2], cells[3], cells[4]
        key = (date, home, away)
        seq[key] += 1                                         # 더블헤더 구분
        games.append({
            "game_id": f"{date.replace('-', '')}-{home}-{away}-{seq[key]}",
            "date": date, "stage": "regular",
            "home": home, "away": away, "venue": venue,
            "attendance": to_int(cells[5]),
        })
    if official and official["regular"]["games"] != len(games):
        raise CollectError(f"KBO 표의 경기 수({len(games)})와 상단 합계({official['regular']['games']})가 다름")
    return games, official


# ---------------------------------------------------------------- 포스트시즌·올스타
def _list_game_ids(http: Http, season: str, series: str, months: list[str]) -> list[str]:
    ids = []
    for m in months:
        r = http.post(WS_LIST, raw_name=f"list_{series.replace(',', '')}_{m}.json",
                      headers={"Referer": SCHEDULE_URL, "X-Requested-With": "XMLHttpRequest"},
                      data={"leId": 1, "srIdList": series, "seasonId": season, "gameMonth": m, "teamId": ""})
        d = _json(r)
        for gid in re.findall(r"gameId=(\w+)", json.dumps(d, ensure_ascii=False)):
            if gid not in ids:
                ids.append(gid)
    return ids


def _scoreboard(http: Http, season: str, gid: str, series_order: list[str]) -> dict | None:
    for sr in series_order:
        r = http.post(WS_BOARD, raw_name=f"board_{gid}_{sr}.json",
                      headers={"Referer": f"{GAMECENTER}?gameId={gid}", "X-Requested-With": "XMLHttpRequest"},
                      data={"leId": 1, "srId": sr, "seasonId": season, "gameId": gid})
        d = _json(r)
        if d.get("code") == "100":
            d["_sr"] = sr
            return d
    return None


def collect_games_by_id(http: Http, season: str, stage: str, series_list: str,
                        months: list[str], try_order: list[str], prev_sr: dict) -> tuple[list[dict], list[str]]:
    games, notes = [], []
    for gid in _list_game_ids(http, season, series_list, months):
        order = [prev_sr[gid]] + [s for s in try_order if s != prev_sr[gid]] if gid in prev_sr else try_order
        d = _scoreboard(http, season, gid, order)
        if d is None:
            notes.append(f"{gid}: 게임센터 정보 없음 (미개최/취소로 보고 제외)")
            continue
        crowd = str(d.get("CROWD_CN") or "").strip()
        if not re.search(r"\d", crowd) or to_int(crowd) == 0:
            notes.append(f"{gid}: 관중 수 없음 (경기 전/취소로 보고 제외)")
            continue
        games.append({
            "game_id": gid, "date": d["G_DT"][:10], "stage": stage, "series_id": d["_sr"],
            "home": d.get("HOME_NM"), "away": d.get("AWAY_NM"), "venue": d.get("S_NM"),
            "attendance": to_int(crowd),
        })
    return games, notes


def collect(season: str) -> Result:
    http = Http("KBO")
    prev = load_previous("KBO", season)
    prev_sr = {g["game_id"]: g["series_id"] for g in (prev or {}).get("games", []) if g.get("series_id")}

    regular, official = collect_regular(http, season)
    http.get(SCHEDULE_URL)  # 일정 페이지 세션
    ps, n1 = collect_games_by_id(http, season, "postseason", ",".join(sorted(PS_SERIES, key=int)),
                                 PS_MONTHS, PS_SERIES, prev_sr)
    allstar, n2 = collect_games_by_id(http, season, "allstar", ALLSTAR_SERIES,
                                      ALLSTAR_MONTHS, [ALLSTAR_SERIES], prev_sr)
    return Result(games=regular + ps + allstar, source_url=DAILY_URL, official=official, notes=n1 + n2)
