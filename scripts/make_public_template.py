"""원본 엑셀 → 사이트 다운로드용 양식(site/template/양식.xlsx) 만들기. 원본은 읽기만 한다.

사이트에서 누구나 받을 수 있는 파일이라 개인정보를 지운다:
  - 텍스트 상자의 '담당자' 줄 (이름·직급·전화번호·이메일)
  - 엑셀 내부에 저장된 원본 파일 경로 (OneDrive 폴더 경로)
그 밖의 모든 부품(서식·수식·그림·텍스트 상자의 나머지 내용)은 바이트 그대로 복사.

실행: python scripts/make_public_template.py [원본.xlsx]
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, SOURCE_XLSX  # noqa: E402

OUT = ROOT / "site" / "template" / "양식.xlsx"
CONTACT_LINE = "담당자"
PHONE = re.compile(r"\b0\d{1,2}-\d{3,4}-\d{4}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PARA = re.compile(r"<a:p>.*?</a:p>|<a:p [^>]*>.*?</a:p>", re.S)


def para_text(p: str) -> str:
    return "".join(re.findall(r"<a:t[^>]*>([^<]*)</a:t>", p))


def clean_drawing(xml: str) -> tuple[str, list[str]]:
    removed = []

    def repl(m):
        t = para_text(m.group(0))
        # 'ㅇ 담당자 : 이름 (전화 / 이메일)' 줄, 또는 전화번호·이메일이 들어 있는 줄만 지움
        if re.match(rf"^\s*ㅇ\s*{CONTACT_LINE}\s*:", t) or PHONE.search(t) or EMAIL.search(t):
            removed.append(t.strip())
            return ""
        return m.group(0)

    return PARA.sub(repl, xml), removed


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE_XLSX
    zin = zipfile.ZipFile(src)
    removed_all = []
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith("xl/drawings/drawing") and info.filename.endswith(".xml"):
                text, removed = clean_drawing(data.decode("utf-8"))
                removed_all += [f"{info.filename}: {r}" for r in removed]
                data = text.encode("utf-8")
            elif info.filename == "xl/workbook.xml":
                text = data.decode("utf-8")
                text2 = re.sub(r"<mc:AlternateContent[^>]*><mc:Choice[^>]*><x15ac:absPath [^>]*/></mc:Choice></mc:AlternateContent>",
                               "", text)
                if text2 != text:
                    removed_all.append("xl/workbook.xml: 원본 파일 저장 경로(absPath)")
                data = text2.encode("utf-8")
            zout.writestr(info, data, compress_type=info.compress_type)
    # 최종 점검: 전화번호·이메일이 하나라도 남아 있으면 중단
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
    for r in removed_all:
        print("  지움 →", r)


if __name__ == "__main__":
    main()
