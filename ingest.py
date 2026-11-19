"""Import the organizer's Chinese handbooks. Run again with a newer ZIP to refresh."""
import argparse
import io
import json
import os
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

import requests
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
PACK = "https://shuming-official-file.markyin.com/static/file/SAIGS01CompetitionMaterials.zip"
SITE = "https://www.dlife.love/saig/"


def chunks(text, size=460):
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)
    text = " ".join(text.split())
    while len(text) > size:
        cut = max(text.rfind(mark, size // 2, size) for mark in "。；！？")
        cut = cut + 1 if cut >= 0 else size
        yield text[:cut]
        text = text[cut:]
    if len(text) >= 8:
        yield text


def read_pack(path):
    rows = []
    def add(prefix, category, title, loc, value):
        for part, text in enumerate(chunks(value)):
            rows.append(dict(id=f"{prefix}.{loc}.{part+1}", category=category, title=title,
                             locator=loc, text=text, source=PACK, edition="赛事中文资料包"))
    with ZipFile(path, metadata_encoding="gbk") as z:
        for name in z.namelist():
            if "/中文/" not in name:
                continue
            title = Path(name).stem
            if name.endswith(".pdf"):
                overview = "概览" in title
                for page, obj in enumerate(PdfReader(io.BytesIO(z.read(name))).pages, 1):
                    category = "wuhan" if overview else "attraction"
                    if not overview and 160 <= page <= 169:
                        category = "food"
                    if not overview and 172 <= page <= 209:
                        category = "guide"
                    # Page numbers are physical PDF pages (starting at 1).
                    add("overview" if overview else "book", category, title, page, obj.extract_text())
            elif name.endswith(".docx") and "SAIG" not in title:
                category = "community" if "社区" in title else "spu"
                with ZipFile(io.BytesIO(z.read(name))) as doc:
                    xml = ET.fromstring(doc.read("word/document.xml"))
                    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                    for i, para in enumerate(xml.iter(ns+"p"), 1):
                        add(category, category, title, i, "".join(t.text or "" for t in para.iter(ns+"t")))
    if not {"wuhan","guide","food","attraction","community","spu"} <= {r["category"] for r in rows}:
        raise ValueError("赛题素材结构发生变化，请复核；保留上次成功版本")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path)
    args = ap.parse_args()
    path = args.zip or Path(tempfile.gettempdir()) / "saig-competition-materials.zip"
    if not path.exists():
        response = requests.get(PACK, timeout=90)
        response.raise_for_status()
        path.write_bytes(response.content)
    rows = read_pack(path)
    dest = ROOT / "data" / "handbooks.jsonl"
    dest.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dest.parent, encoding="utf-8", delete=False) as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False)+"\n")
    os.replace(out.name, dest)
    from collections import Counter
    print(dict(Counter(r["category"] for r in rows)))


if __name__ == "__main__":
    main()
