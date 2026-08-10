import re
import glob
import json
from typing import Optional

MIN_CONTENT_LEN = 10

LEVELS: list[tuple[str, re.Pattern]] = [
    ("phan",     re.compile(r"^Phần\s+[IVXLC\d]")),
    ("chuong",   re.compile(r"^Chương\s+[IVXLC\d]")),
    ("muc",      re.compile(r"^Mục\s+\d")),
    ("tieu_muc", re.compile(r"^Tiểu\s+mục\s+\d")),
    ("dieu",     re.compile(r"^Điều\s+\d")),
    ("khoan",    re.compile(r"^\d+\.\s")),
    ("diem",     re.compile(r"^[a-zđ]\)\s")),
]
LEVEL_ORDER  = {"phan": 0, "chuong": 1, "muc": 2, "tieu_muc": 2, "dieu": 3}
BULLET_NAMES = {"khoan", "diem"}
BULLET_RANK  = {"khoan": 0, "diem": 1, "numsec_leaf": 0, "dash": 1}

_RE_NUMSEC        = re.compile(r"^\d{1,3}(?:\.\d{1,3}){1,4}")
_RE_LETTER        = re.compile(r"[A-Za-zÀ-Ỹà-ỹ]")
_RE_DASH          = re.compile(r"^-\s+\S")
_RE_SENTENCE_END  = re.compile(r"[.;:]\s*$")


def load_records(pattern: str) -> list[dict]:
    records = []
    for path in sorted(glob.glob(pattern)):
        data = json.load(open(path, encoding="utf-8"))
        records.extend(data if isinstance(data, list) else [data])
    return records


def _numbered_section_id(line: str) -> Optional[str]:
    m = _RE_NUMSEC.match(line)
    if not m:
        return None
    so_hieu = m.group(0)
    rest = line[m.end():]
    if rest[:1] == ")":
        return None
    if any(len(p) == 3 for p in so_hieu.split(".")[1:]):
        return None
    if not _RE_LETTER.search(rest):
        return None
    return so_hieu


def _raw_level(line: str) -> Optional[tuple[str, int]]:
    so_hieu = _numbered_section_id(line)
    if so_hieu:
        return "numsec", so_hieu.count(".")
    for level, pat in LEVELS:
        if pat.match(line):
            if level in BULLET_NAMES:
                return "bullet", BULLET_RANK[level]
            return "fixed", LEVEL_ORDER[level]
    if _RE_DASH.match(line):
        return "bullet", BULLET_RANK["dash"]
    return None


def build_depth_map(text: str) -> dict[tuple[str, int], int]:
    raw_seen: dict[str, set[int]] = {"fixed": set(), "numsec": set()}
    for ln in text.split("\n"):
        r = _raw_level(ln.strip())
        if r and r[0] in raw_seen:
            raw_seen[r[0]].add(r[1])

    depth_map: dict[tuple[str, int], int] = {}
    next_depth = 2
    for kind in ("fixed", "numsec"):
        levels_sorted = sorted(raw_seen[kind])
        for i, raw in enumerate(levels_sorted):
            is_deepest = (kind == "numsec" and i == len(levels_sorted) - 1
                          and len(levels_sorted) > 1)
            if is_deepest:
                depth_map[(kind, raw)] = 0
            else:
                depth_map[(kind, raw)] = next_depth
                next_depth += 1
    return depth_map


def detect(line: str, depth_map: dict) -> Optional[tuple[str, int]]:
    r = _raw_level(line)
    if r is None:
        return None
    kind, raw = r
    if kind == "bullet":
        return ("bullet", raw)
    depth = depth_map.get((kind, raw), 2)
    if depth == 0:
        return ("bullet", BULLET_RANK["numsec_leaf"])
    return ("heading", depth)


def clean(text: str) -> str:
    text = text.replace("\r\n", " ").replace("\r", " ")
    text = re.sub(r"(\.\.\.\n?){2,}", "", text)
    lines, prev_blank = [], False
    for ln in text.split("\n"):
        ln = ln.strip()
        if ln == "" and prev_blank:
            continue
        lines.append(ln)
        prev_blank = (ln == "")
    return "\n".join(lines).strip()


def merge_lines(text: str, depth_map: dict) -> str:
    out: list[str] = []
    for ln in text.split("\n"):
        if not ln:
            out.append("")
        elif not out or not out[-1] or detect(ln, depth_map) is not None or _RE_SENTENCE_END.search(out[-1]):
            out.append(ln)
        else:
            out[-1] += " " + ln
    return "\n".join(out)


def parse_to_md(text: str, out: list[str], depth_map: dict) -> None:
    para: list[str] = []

    def flush():
        if para:
            block = " ".join(para).strip()
            if len(block) >= MIN_CONTENT_LEN:
                out.append(block + "\n")
            para.clear()

    for raw in text.split("\n"):
        ln = raw.strip()
        if not ln:
            flush()
            continue
        r = detect(ln, depth_map)
        if r is None:
            para.append(ln)
        elif r[0] == "bullet":
            flush()
            rank = r[1]
            content = ln[1:].strip() if _RE_DASH.match(ln) else ln
            out.append(f"{'  ' * rank}- {content}")
        else:
            flush()
            out.append(f"\n{'#' * r[1]} {ln}\n")
    flush()


def process_json(input_pattern: str, output_path: str) -> None:
    records = load_records(input_pattern)
    lines, errors = [], []
    for rec in records:
        try:
            meta = rec.get("name") or rec.get("link") or str(rec.get("id", "doc"))
            lines.append(f"# {meta}\n")
            cleaned = clean(rec.get("passage", ""))
            depth_map = build_depth_map(cleaned)
            merged = merge_lines(cleaned, depth_map)
            parse_to_md(merged, lines, depth_map)
            lines.append("\n---\n")
        except Exception as e:
            errors.append({"id": rec.get("id"), "error": str(e)})

    open(output_path, "w", encoding="utf-8").write("\n".join(lines))

    total = sum(len(l) for l in lines)
    print(f"✅ {len(records)-len(errors)}/{len(records)} → {output_path} ({total:,} chars)")
    if errors:
        print(f"❌ {errors}")