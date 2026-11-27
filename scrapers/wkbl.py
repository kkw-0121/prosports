"""WKBL 수집기.

WKBL 사이트에는 경기별 관중 수가 없다. 그래서:
- 경기 수: 일정/결과 달력(schedule1.asp)에서 결과가 나온 경기를 셈
    · 월별 화면의 game_type 01 → 정규리그 / '플레이오프/챔피언결정전' 화면 → PO / 그 밖(올스타 등)은 제외
- 관중 수: 역대관중현황(crowd.asp)의 시즌 합계를 매 수집마다 저장(season_total)
    · 진행 중 시즌은 구단별 값이 없고 시즌 합계만 공개됨
    · 새로 끝난 경기는 '반영 대기(pending)'로 두고, 합계가 늘었을 때 대기 경기가 1경기면 증가분 = 그 경기 관중
    · 알 수 없으면 경기별 관중은 비워 둠(attendance_known=false). 추정하지 않음
- 정규/PO 관중 합계(stage_totals): PO 시작 전 = 시즌 합계 전체가 정규리그.
  PO가 시작되면 마지막 정규리그 시점의 합계를 정규리그 값으로 고정하고, 이후 증가분을 PO로 계산.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from scrapers.base import CollectError, Http, Result, load_config, load_previous, now_kst, to_int

BASE = "https://www.wkbl.or.kr"
SCHEDULE = f"{BASE}/game/sch/schedule1.asp"
CROWD = f"{BASE}/history/crowd.asp"
REGULAR_TYPE = "01"



def _season_code(http: Http, season: str) -> tuple[str, list[str]]:
    soup = BeautifulSoup(http.get(SCHEDULE, raw_name="schedule.html").text, "html.parser")
    sel = soup.find("select", attrs={"name": "season_gu"})
    if not sel:
        raise CollectError("WKBL 일정 화면에서 시즌 선택 칸을 찾지 못함")
    code = next((o.get("value") for o in sel.find_all("option") if o.get_text(strip=True) == season), None)
    if code is None:
        raise CollectError(f"WKBL 시즌 목록에 {season} 없음")
    soup = BeautifulSoup(http.get(SCHEDULE, raw_name=f"schedule_{code}.html", params={"season_gu": code}).text,
                         "html.parser")
    yms = [o.get("value") for o in soup.find("select", attrs={"name": "ym"}).find_all("option") if o.get("value")]
    return code, yms


def _parse_month(html: str, code: str, ym: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    games = []
    for block in soup.select("div.info_game"):
        a = block.find("a", href=re.compile(r"result\.asp"))
        if not a:
            continue                                   # 결과 없음 = 아직 안 열렸거나 취소
        q = {k: v[0] for k, v in parse_qs(urlparse(a["href"]).query).items()}
        if q.get("season_gu") != code:
            raise CollectError(f"WKBL 다른 시즌 경기가 섞임: {a['href']}")
        gtype, gno, link_ym = q["game_type"], q["game_no"], q.get("ym", ym)
        if ym != "p" and gtype != REGULAR_TYPE:
            continue                                   # 올스타전 등 (엑셀 항목 아님)
        p = block.find("p", class_="txt_team")
        names = [s.get_text(strip=True) for s in p.find_all("span", class_="language")]
        if len(names) != 2:
            text = re.sub(r"\[.*", "", p.get_text(" ", strip=True))
            names = [x.strip() for x in text.split("vs")]
        if len(names) != 2:
            raise CollectError(f"WKBL 팀 이름을 읽지 못함: {p.get_text(' ', strip=True)}")
        day = block.find_parent("td").find("span", class_="date_day").get_text(strip=True)
        games.append({
            "game_id": f"{code}-{gtype}-{gno}", "game_type": gtype,
            "date": f"{link_ym[:4]}-{link_ym[4:6]}-{int(day):02d}",
            "stage": "regular" if ym != "p" else "postseason",
            "home": names[0], "away": names[1], "venue": None,
        })
    return games


def _season_total(http: Http, season: str) -> int:
    """역대관중현황 막대그래프의 시즌 합계 (진행 중 시즌은 구단별 표에 아직 없음)."""
    soup = BeautifulSoup(http.get(CROWD, raw_name="crowd.html").text, "html.parser")
    for li in soup.select(".crowd_list li"):
        year = li.find(class_="txt_year")
        num = li.find(class_="txt_num")
        if year and num and year.get_text("-", strip=True).replace("--", "-") == season:
            return to_int(num.get_text())
    raise CollectError(f"WKBL 역대관중현황에 {season} 합계가 없음")


def collect(season: str) -> Result:
    http = Http("WKBL")
    code, yms = _season_code(http, season)
    games = []
    for ym in yms:
        html = http.get(SCHEDULE, raw_name=f"schedule_{code}_{ym}.html", params={"season_gu": code, "ym": ym}).text
        games += _parse_month(html, code, ym)
    if len({g["game_id"] for g in games}) != len(games):
        raise CollectError("WKBL 일정에서 같은 경기가 두 번 나옴")

    total = _season_total(http, season)
    prev = load_previous("WKBL", season) or {}
    prev_games = {g["game_id"]: g for g in prev.get("games", [])}
    prev_total = prev.get("season_total")
    notes = []

    # ---- 경기별 관중
    # 이전에 정한 값은 유지. 새로 끝난 경기는 pending(관중 반영 대기)으로 두고,
    # 시즌 합계가 늘었을 때 대기 경기가 정확히 1경기면 증가분 = 그 경기 관중.
    for g in games:
        old = prev_games.get(g["game_id"])
        if old is not None:
            for k in ("attendance", "attendance_known", "pending"):
                g[k] = old.get(k)
        else:
            g["attendance"], g["attendance_known"] = None, False
            g["pending"] = prev_total is not None        # 첫 수집 때는 아래 기준점으로 정함
    if prev_total is None:
        anchor = (load_config().get("wkbl_anchor") or {}).get(season)
        ordered = sorted(games, key=lambda g: (g["date"], g["stage"] != "regular", int(g["game_id"].split("-")[-1])))
        if anchor and anchor["total"] == total:
            for g in ordered[anchor["games_reflected"]:]:
                g["pending"] = True                          # 아직 시즌 합계에 반영 안 된 경기
            notes.append(f"첫 수집 기준점({anchor['source']}): 합계 {total:,}명에 {anchor['games_reflected']}경기 반영, "
                         f"{max(0, len(games) - anchor['games_reflected'])}경기는 반영 대기")
        elif anchor:
            notes.append(f"사이트 합계({total:,})가 기준점({anchor['total']:,})과 달라 기준점을 쓰지 않음 → "
                         "끝난 경기 전부가 합계에 반영됐다고 보고 시작")
        n = sum(1 for g in games if not g.get("pending"))
        notes.append(f"첫 수집: 이미 반영된 {n}경기는 경기별 관중을 알 수 없어 시즌 합계로만 집계")
    else:
        delta = total - prev_total
        pending = [g for g in games if g.get("pending")]
        if delta < 0:
            notes.append(f"시즌 합계가 {delta:,}명 줄었음 (연맹 정정으로 보임)")
        elif delta > 0:
            if len(pending) == 1:
                pending[0]["attendance"], pending[0]["attendance_known"] = delta, True
                pending[0]["pending"] = False
            elif not pending:
                notes.append(f"새 경기 없이 시즌 합계가 {delta:+,}명 바뀜 (연맹 정정으로 보임)")
            else:
                notes.append(f"관중 반영 대기 경기 {len(pending)}개가 한꺼번에 반영됨 → 경기별 구분 불가 (합계는 정확)")
                for g in pending:
                    g["pending"] = False

    # ---- 정규/PO 합계
    # 경기 수는 관중이 합계에 반영된 경기만 (반영 대기 경기는 다음 수집에서 포함)
    reg_n = sum(g["stage"] == "regular" and not g.get("pending") for g in games)
    po_n = sum(g["stage"] == "postseason" and not g.get("pending") for g in games)
    prev_st = prev.get("stage_totals")
    pending_regular = any(g.get("pending") and g["stage"] == "regular" for g in games)
    if po_n == 0:
        reg_att, po_att = total, 0
    elif (prev_st and prev_st["regular"]["games"] == reg_n and prev_st["regular"]["attendance"] is not None
          and not pending_regular):
        reg_att = prev_st["regular"]["attendance"]               # 정규리그 종료 시점 값으로 고정
        po_att = total - reg_att
    else:
        reg_att = po_att = None
        notes.append("정규리그 종료 시점 합계를 확보하지 못해 정규/PO 관중을 나눌 수 없음 (합계만 정확)")
    stage_totals = {"regular": {"attendance": reg_att, "games": reg_n},
                    "postseason": {"attendance": po_att, "games": po_n}}

    known = sum(g["attendance"] for g in games if g["attendance_known"])
    if known > total:
        raise CollectError(f"WKBL 경기별 관중 합({known:,})이 시즌 합계({total:,})보다 큼")

    # 시즌 합계 기록 (날짜별 누적 관중 그래프용). 합계나 반영 경기 수가 바뀔 때만 한 줄 추가
    history = list(prev.get("total_history") or [])
    reflected = [g for g in games if not g.get("pending")]
    entry = {"last_game": max((g["date"] for g in reflected), default=None),
             "games": len(reflected), "total": total, "recorded_at": now_kst()}
    if not history or (history[-1]["total"], history[-1]["games"]) != (entry["total"], entry["games"]):
        history.append(entry)

    return Result(
        games=games, source_url=f"{SCHEDULE} + {CROWD}",
        official={"total": {"attendance": total, "games": None,
                            "note": "WKBL 역대관중현황 시즌 합계 (정규+PO+챔프전)"}},
        notes=notes,
        extra={"attendance_method": "season_total_snapshot", "season_total": total,
               "stage_totals": stage_totals, "total_history": history},
    )
