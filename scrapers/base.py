"""수집기 공통 기능: HTTP 요청, 원본 보관, 검증, 안전한 저장, 상태 기록."""
from __future__ import annotations

import gzip
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from common import load_config, load_json, save_json  # noqa: E402

KST = timezone(timedelta(hours=9))
GAMES_DIR = ROOT / "data" / "games"
OFFICIAL_DIR = ROOT / "data" / "official"
STATUS_PATH = ROOT / "data" / "status.json"
RAW_DIR = ROOT / "raw"
RAW_KEEP_DAYS = 7
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
MIN_INTERVAL = 1.2  # 요청 간 최소 간격(초)

VALID_STAGES = {"regular", "postseason", "allstar", "k1", "k2", "k_po"}


class CollectError(Exception):
    """수집 실패 (이 리그는 저장하지 않음)."""


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def to_int(text) -> int:
    """'2,569명' → 2569. 숫자가 없으면 CollectError."""
    digits = re.sub(r"[^\d]", "", str(text))
    if not digits:
        raise CollectError(f"관중 수가 숫자가 아님: {text!r}")
    return int(digits)


# ---------------------------------------------------------------- HTTP
class Http:
    """요청 간격 1.2초 이상, 실패 시 2회 재시도, 응답 원본을 raw/ 에 보관."""

    def __init__(self, league: str):
        self.league = league
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self._last = 0.0
        self.raw_dir = RAW_DIR / datetime.now(KST).strftime("%Y-%m-%d") / league
        self._n = 0

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        self._last = time.monotonic()

    def request(self, method: str, url: str, raw_name: str | None = None, **kw) -> requests.Response:
        kw.setdefault("timeout", 30)
        err = None
        for attempt in range(3):
            self._wait()
            try:
                r = self.s.request(method, url, **kw)
                r.raise_for_status()
                if raw_name:
                    self.save_raw(raw_name, r.content)
                return r
            except requests.RequestException as e:
                err = e
                time.sleep(3 * (attempt + 1))
        raise CollectError(f"요청 실패 {url}: {err}")

    def get(self, url, raw_name=None, **kw):
        return self.request("GET", url, raw_name, **kw)

    def post(self, url, raw_name=None, **kw):
        return self.request("POST", url, raw_name, **kw)

    def save_raw(self, name: str, content: bytes | str):
        """원본 응답을 gzip 으로 보관 (raw/ 는 저장소에 올리지 않고 Actions 첨부파일로 7일 보관)."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._n += 1
        safe = re.sub(r"[^\w.-]", "_", name)
        p = self.raw_dir / f"{datetime.now(KST).strftime('%H%M%S')}_{self._n:03d}_{safe}.gz"
        p.write_bytes(gzip.compress(content.encode("utf-8") if isinstance(content, str) else content))


def cleanup_raw(keep_days: int = RAW_KEEP_DAYS) -> None:
    """raw/ 에서 keep_days 보다 오래된 날짜 폴더 삭제."""
    if not RAW_DIR.exists():
        return
    cutoff = (datetime.now(KST) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for d in RAW_DIR.iterdir():
        if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name) and d.name < cutoff:
            for p in sorted(d.rglob("*"), reverse=True):
                p.unlink() if p.is_file() else p.rmdir()
            d.rmdir()


# ---------------------------------------------------------------- 결과/검증
@dataclass
class Result:
    games: list[dict]
    source_url: str
    official: dict | None = None          # 연맹 공식 누적치 {item_key: {"attendance":, "games":}}
    notes: list[str] = field(default_factory=list)
    allow_fewer: bool = False             # 스냅샷 방식 등 경기 수 감소를 허용해야 할 때만
    extra: dict = field(default_factory=dict)  # 파일에 함께 저장할 값 (WKBL stage_totals 등)


def total_attendance(games: list[dict]) -> int:
    return sum(g["attendance"] or 0 for g in games)


def validate(league: str, season: str, games: list[dict]) -> list[str]:
    """심각한 문제는 CollectError, 의심 값은 경고 목록으로 반환."""
    cfg = load_config()
    cap = cfg["max_capacity"][league]
    no_crowd = season in cfg["no_crowd_seasons"]
    warnings, seen = [], set()
    for g in games:
        for k in ("game_id", "date", "stage", "attendance"):
            if k == "attendance" and g.get("attendance_known") is False:
                continue
            if g.get(k) in (None, ""):
                raise CollectError(f"{k} 값이 없음: {g}")
        if g["game_id"] in seen:
            raise CollectError(f"중복 경기: {g['game_id']}")
        seen.add(g["game_id"])
        if g["stage"] not in VALID_STAGES:
            raise CollectError(f"알 수 없는 stage {g['stage']}: {g['game_id']}")
        if league == "KOVO" and g.get("division") not in ("men", "women", "common"):
            raise CollectError(f"KOVO division 누락: {g['game_id']}")
        a = g["attendance"]
        if a is None and g.get("attendance_known") is False:
            continue                      # WKBL: 경기별 관중을 알 수 없는 경기 (합계는 stage_totals)
        if not isinstance(a, int) or isinstance(a, bool):
            raise CollectError(f"관중 수가 정수가 아님: {g['game_id']} {a!r}")
        if a < 0:
            raise CollectError(f"관중 수 음수: {g['game_id']} {a}")
        if a == 0 and not no_crowd:
            warnings.append(f"관중 0명: {g['game_id']} ({g['date']})")
        if a > cap * 1.2:
            warnings.append(f"수용 인원 1.2배 초과: {g['game_id']} {a:,}명 (기준 {cap:,})")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", g["date"]):
            raise CollectError(f"날짜 형식 오류: {g['game_id']} {g['date']}")
    return warnings


def games_path(league: str, season: str) -> Path:
    return GAMES_DIR / f"{league}_{season}.json"


def load_previous(league: str, season: str) -> dict | None:
    p = games_path(league, season)
    return load_json(p) if p.exists() else None


def save_result(league: str, season: str, res: Result) -> dict:
    """검증 후 저장. 경기 수가 줄면 저장하지 않고 실패 처리."""
    warnings = validate(league, season, res.games)
    prev = load_previous(league, season)
    if prev is not None and not res.allow_fewer:
        prev_ids = {g["game_id"] for g in prev["games"]}
        new_ids = {g["game_id"] for g in res.games}
        missing = prev_ids - new_ids
        if missing:
            raise CollectError(f"이전에 있던 경기 {len(missing)}건이 이번 수집에서 빠짐 → 저장 안 함 (예: {sorted(missing)[:3]})")
    games = sorted(res.games, key=lambda g: (g["date"], g["game_id"]))
    out = {"league": league, "season": season, "collected_at": now_kst(),
           "source_url": res.source_url, "games": games}
    out.update(res.extra)
    if res.notes:
        out["notes"] = res.notes
    save_json(games_path(league, season), out)
    if res.official is not None:
        save_json(OFFICIAL_DIR / f"{league}_{season}.json",
                  {"league": league, "season": season, "collected_at": out["collected_at"],
                   "source_url": res.source_url, "items": res.official})
    return summarize(res, warnings)


def summarize(res: Result, warnings: list[str]) -> dict:
    """상태 기록용 요약. WKBL처럼 합계를 따로 가진 리그는 그 합계를 사용."""
    st = res.extra.get("stage_totals")
    if st:
        return {"games": sum(v["games"] for v in st.values()),
                "attendance": res.extra.get("season_total"), "warnings": warnings}
    return {"games": len(res.games), "attendance": total_attendance(res.games), "warnings": warnings}


# ---------------------------------------------------------------- 상태
def update_status(league: str, ok: bool, detail: dict | str) -> None:
    status = load_json(STATUS_PATH) if STATUS_PATH.exists() else {"leagues": {}}
    s = status["leagues"].setdefault(league, {})
    s["last_attempt"] = now_kst()
    if ok:
        s["last_success"] = s["last_attempt"]
        s["last_error"] = None
        s["seasons"] = detail
    else:
        s["last_error"] = {"at": s["last_attempt"], "message": str(detail)}
    status["updated_at"] = now_kst()
    save_json(STATUS_PATH, status)


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
