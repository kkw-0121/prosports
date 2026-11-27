"""K리그 수집기.

K리그 데이터 포털(data.kleague.com → 손님 세션으로 portal.kleague.com)
데이터센터 > 공식기록 > 관중정보 > '경기별' 표를 리그별(1=K리그1, 2=K리그2, 3=플레이오프)로 조회.
리그컵(4)은 집계 제외라 조회하지 않음.
"""
from __future__ import annotations

import re

from scrapers.base import CollectError, Http, Result, to_int
from scrapers.browser import open_page, pause

ENTRY = "https://data.kleague.com/"
PORTAL = "https://portal.kleague.com"
MENU_ATTENDANCE = "0443"
LEAGUES = {"1": "k1", "2": "k2", "3": "k_po"}
EMPTY_TEXT = "조회된 데이터가 존재하지 않습니다"


def _guest_login_url(http: Http) -> str:
    html = http.get(ENTRY, raw_name="entry.html").text
    m = re.search(r'src="(https://portal\.kleague\.com/user/loginById\.do\?portalGuest=[^"]+)"', html)
    if not m:
        raise CollectError("data.kleague.com 에서 손님 접속 주소를 찾지 못함")
    return m.group(1)


def _read_table(page) -> list[list[str]]:
    return page.evaluate("""() => {
        const t = [...document.querySelectorAll('table')].find(t => t.innerText.includes('관중수') && t.innerText.includes('경기번호'));
        if (!t) return null;
        return [...t.querySelectorAll('tbody tr')].map(r => [...r.cells].map(c => c.innerText.trim()));
    }""")


def _wait_table(page, season: str):
    """표가 다 그려질 때까지 대기: 내용이 연속 2번 같고 모든 행이 요청한 시즌이어야 함."""
    rows, stable = None, 0
    for _ in range(30):
        pause(1.0)
        cur = _read_table(page)
        # 빈 표(그리는 중)는 완료로 보지 않음. 진짜 결과 없음은 '조회된 데이터가 존재하지 않습니다' 한 줄로 나옴
        settled = bool(cur) and all((len(r) == 1 and EMPTY_TEXT in r[0]) or (len(r) > 1 and r[1] == season)
                                    for r in cur)
        stable = stable + 1 if settled and rows is not None and cur == rows else 0
        rows = cur
        if stable >= 2:
            return rows
    raise CollectError(f"K리그 표가 안정되지 않음 ({season})")


def _search(page, http: Http, league_id: str, season: str) -> list[list[str]]:
    want = {"#leagueId": league_id, "#meetYear": season, "#audienceType": "1", "#pageViewCount": "500"}
    dates = {"#searchDateF": f"{season}/01/01", "#searchDateT": f"{season}/12/31"}
    for attempt in range(3):
        for sel, val in want.items():           # 선택을 바꾸면 화면이 자동 조회되기도 해서 매번 확인
            if page.locator(sel).input_value() != val:
                page.select_option(sel, val)
                page.wait_for_load_state("networkidle")
                pause()
        # 연도를 바꾸면 포털이 기간을 'YYYY/12/31~YYYY/12/31'로 잡는 경우가 있어 직접 1/1~12/31로 지정
        page.evaluate("""([f, t]) => {
            for (const [id, v] of [['searchDateF', f], ['searchDateT', t]]) {
                const el = document.getElementById(id); el.value = v;
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }}""", [dates["#searchDateF"], dates["#searchDateT"]])
        pause(0.5)
        page.get_by_role("button", name="조회").click()
        page.wait_for_load_state("networkidle")
        rows = _wait_table(page, season)
        if all(page.locator(s).input_value() == v for s, v in {**want, **dates}.items()):
            break
    else:
        raise CollectError(f"K리그 조회 조건(리그 {league_id}, {season}, 경기별, 500건)이 적용되지 않음")
    http.save_raw(f"attendance_{league_id}_{season}.html", page.content())
    if rows is None:
        raise CollectError("K리그 관중정보 표를 찾지 못함")
    if len(rows) >= 500:
        raise CollectError("K리그 결과가 500건 이상이라 다음 페이지가 있을 수 있음")
    if len(rows) == 1 and EMPTY_TEXT in " ".join(rows[0]):
        return []
    total = page.evaluate("() => (document.querySelector('[name=pageTotalDataCount]')||{}).value || ''")
    if total and total.isdigit() and int(total) > len(rows):
        raise CollectError(f"K리그 결과가 한 페이지에 다 나오지 않음 ({len(rows)}/{total}건)")
    return rows


def _official_k1(page) -> int | None:
    m = re.search(r"총 누적관중수\s*:\s*([\d,]+)", page.inner_text("body"))
    return to_int(m.group(1)) if m else None


def collect(season: str) -> Result:
    http = Http("KLEAGUE")
    login_url = _guest_login_url(http)
    games, notes, official = [], [], None
    with open_page() as page:
        page.goto(login_url)
        page.wait_for_load_state("networkidle")
        pause()
        k1_total = _official_k1(page)   # 메인 화면: 현재 시즌 K리그1 누적 관중
        page.evaluate(f"moveMainFrame('{MENU_ATTENDANCE}')")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("#leagueId")
        years = [v for v in page.eval_on_selector_all("#meetYear option", "os => os.map(o => o.value)") if v.isdigit()]
        if season not in years:
            if season > max(years):
                return Result(games=[], source_url=f"{PORTAL}/mainFrame.do (관중정보)",
                              notes=[f"{season} 시즌이 아직 포털 연도 목록에 없음 (시즌 시작 전)"])
            raise CollectError(f"K리그 포털 연도 목록에 {season} 없음")
        latest = max(years)
        if season != latest:
            k1_total = None            # 메인 화면 누적치는 최신 시즌 것이라 다른 시즌엔 쓰지 않음
        pause()
        for league_id, stage in LEAGUES.items():
            for r in _search(page, http, league_id, season):
                # 순위 시즌 대회 대회명 경기번호 일자 홈팀 상대 경기결과 경기장 관중수 원정팀 비고
                if len(r) < 11 or r[1] != season:
                    raise CollectError(f"K리그 표 형식이 예상과 다름: {r}")
                date = r[5].replace("/", "-")
                games.append({
                    "game_id": f"{r[3]}-{r[4]}", "date": date, "stage": stage,
                    "competition": r[3], "home": r[6], "away": r[7], "venue": r[9],
                    "attendance": to_int(r[10]),
                })
    if k1_total is not None:
        official = {"k1": {"attendance": k1_total, "games": None,
                           "note": "포털 메인 화면 'K리그1 총 누적관중수'"}}
    return Result(games=games, source_url=f"{PORTAL}/mainFrame.do (관중정보)", official=official, notes=notes)
