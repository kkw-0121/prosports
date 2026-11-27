"""원본 엑셀 → 사이트 다운로드용 양식(site/template/양식.xlsx) 만들기. 원본은 읽기만 한다.

다운로드용 양식에서 정리하는 것:
  - 리그별 시트의 안내 상자(파란 상자)와 그 안의 캡처 그림 → 통째로 제거
    (접속 경로·담당자 연락처 등 내부 업무용 안내라서)
  - 종합 시트 안내 상자의 '■ 관중 수 취합 방법' 부분 → 제거하고 상자 높이를 남은 내용에 맞게 줄임
    ('■ 종목별 공식 관중 수 집계 기준' 등 나머지 안내는 유지)
  - 엑셀 내부에 저장된 원본 파일 경로 (OneDrive 폴더 경로)
그 밖의 모든 부품(서식·수식·열 너비 등)은 바이트 그대로 복사.
마지막에 전화번호·이메일이 남아 있는지 검사하고, 남아 있으면 저장하지 않는다.

실행: python scripts/make_public_template.py [원본.xlsx]
"""
from __future__ import annotations

import math
import posixpath
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, SOURCE_XLSX, load_config  # noqa: E402

OUT = ROOT / "site" / "template" / "양식.xlsx"
SUMMARY_CUT_HEADING = "관중 수 취합 방법"      # 종합 상자에서 이 제목부터 끝까지 지움
PHONE = re.compile(r"\b0\d{1,2}-\d{3,4}-\d{4}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PARA = re.compile(r"<a:p>.*?</a:p>|<a:p [^>]*>.*?</a:p>", re.S)


def para_text(p: str) -> str:
    return "".join(re.findall(r"<a:t[^>]*>([^<]*)</a:t>", p))


def resolve(base_dir: str, target: str) -> str:
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base_dir, target))


def rels_of(files: dict, part: str) -> list[tuple[str, str, str]]:
    """part 의 관계 목록 [(Id, Type, 절대경로)]"""
    d, name = posixpath.split(part)
    rp = f"{d}/_rels/{name}.rels"
    if rp not in files:
        return []
    out = []
    for m in re.finditer(r"<Relationship ([^>]*)/>", files[rp].decode("utf-8")):
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        out.append((a["Id"], a["Type"], resolve(d, a["Target"])))
    return out


def trim_summary_box(xml: str) -> tuple[str, int]:
    """종합 상자: '관중 수 취합 방법' 제목(과 바로 앞 빈 줄)부터 끝까지 지우고, 상자 높이를 비례해 줄임."""
    paras = list(PARA.finditer(xml))
    cut = next((i for i, m in enumerate(paras) if SUMMARY_CUT_HEADING in para_text(m.group(0))), None)
    if cut is None:
        return xml, 0
    while cut > 0 and not para_text(paras[cut - 1].group(0)).strip():
        cut -= 1
    removed = len(paras) - cut
    xml = xml[: paras[cut].start()] + xml[paras[-1].end():]
    m_from = re.search(r"<xdr:from>.*?<xdr:row>(\d+)</xdr:row>", xml, re.S)
    m_to = re.search(r"(<xdr:to>.*?<xdr:row>)(\d+)(</xdr:row>)", xml, re.S)
    if m_from and m_to:
        top, bottom = int(m_from.group(1)), int(m_to.group(2))
        new_bottom = top + math.ceil((bottom - top) * cut / len(paras)) + 1
        xml = xml[: m_to.start(2)] + str(new_bottom) + xml[m_to.end(2):]
    return xml, removed


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE_XLSX
    summary_name = load_config()["workbook"]["summary_sheet"]
    zin = zipfile.ZipFile(src)
    infos = {i.filename: i for i in zin.infolist()}
    files = {n: zin.read(n) for n in infos}
    log = []

    # 시트 이름 → 시트 파일
    wb = files["xl/workbook.xml"].decode("utf-8")
    wb_rels = {rid: path for rid, _, path in rels_of(files, "xl/workbook.xml")}
    sheets = {m.group(1): wb_rels[m.group(2)]
              for m in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="([^"]+)"', wb)}

    drop_parts = set()
    for name, sheet_path in sheets.items():
        for rid, typ, target in rels_of(files, sheet_path):
            if not typ.endswith("/drawing"):
                continue
            if name == summary_name:
                xml, n = trim_summary_box(files[target].decode("utf-8"))
                files[target] = xml.encode("utf-8")
                log.append(f"{name}: 안내 상자에서 '{SUMMARY_CUT_HEADING}' 부분 {n}줄 삭제, 상자 높이 조정")
                continue
            # 리그 시트: 상자·그림 통째로 제거 (시트의 <drawing> 연결, 관계, 그림 파일까지)
            sx = files[sheet_path].decode("utf-8")
            files[sheet_path] = re.sub(rf'<drawing r:id="{rid}"\s*/>', "", sx).encode("utf-8")
            d, base = posixpath.split(sheet_path)
            rp = f"{d}/_rels/{base}.rels"
            files[rp] = re.sub(rf'<Relationship [^>]*Id="{rid}"[^>]*/>', "", files[rp].decode("utf-8")).encode("utf-8")
            drop_parts.add(target)
            for _, _, media in rels_of(files, target):
                drop_parts.add(media)
            dd, db = posixpath.split(target)
            drop_parts.add(f"{dd}/_rels/{db}.rels")
            log.append(f"{name}: 안내 상자·그림 제거 ({posixpath.basename(target)})")

    # 지운 그림이 다른 곳에서 쓰이면 남김
    still_used = {t for p in files if p not in drop_parts and p.endswith(".xml")
                  for _, _, t in rels_of(files, p)}
    drop_parts -= still_used
    ct = files["[Content_Types].xml"].decode("utf-8")
    for p in drop_parts:
        ct = re.sub(rf'<Override PartName="/{re.escape(p)}"[^>]*/>', "", ct)
    files["[Content_Types].xml"] = ct.encode("utf-8")

    # 원본 파일 저장 경로 제거
    wb2 = re.sub(r"<mc:AlternateContent[^>]*><mc:Choice[^>]*><x15ac:absPath [^>]*/></mc:Choice></mc:AlternateContent>", "", wb)
    if wb2 != wb:
        log.append("workbook.xml: 원본 파일 저장 경로(absPath) 삭제")
    files["xl/workbook.xml"] = wb2.encode("utf-8")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w") as zout:
        for name, info in infos.items():
            if name not in drop_parts:
                zout.writestr(info, files[name], compress_type=info.compress_type)

    # 최종 점검: 전화번호·이메일·파일 경로가 하나라도 남아 있으면 중단
    with zipfile.ZipFile(tmp) as z:
        for name in z.namelist():
            if name.endswith((".xml", ".rels")):
                t = z.read(name).decode("utf-8", "replace")
                left = [m for m in PHONE.findall(t) + EMAIL.findall(t) if "schemas" not in m]
                if left or "absPath" in t:
                    tmp.unlink()
                    raise SystemExit(f"개인정보가 남아 있음: {name} {left or 'absPath'}")
    tmp.replace(OUT)
    print(f"저장: {OUT}")
    for line in log:
        print("  -", line)
    print(f"  - 제거한 부품: {', '.join(sorted(drop_parts))}")


if __name__ == "__main__":
    main()
