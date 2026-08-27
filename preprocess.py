import re
import glob
import json
from typing import Optional

MIN_CONTENT_LEN = 10

_RE_KHOAN = re.compile(r"^\d+\.\s")
_RE_DIEM  = re.compile(r"^[a-zđ]\)\s")

LEVELS: list[tuple[str, re.Pattern]] = [
    ("phan",     re.compile(r"^Phần\s+[IVXLC\d]")),
    ("chuong",   re.compile(r"^Chương\s+[IVXLC\d]")),
    ("muc",      re.compile(r"^Mục\s+\d")),
    ("tieu_muc", re.compile(r"^Tiểu\s+mục\s+\d")),
    ("dieu",     re.compile(r"^Điều\s+\d")),
    ("khoan",    _RE_KHOAN),
    ("diem",     _RE_DIEM),
]
# "muc_hoa": mục lớn dạng chữ cái hoa, vd "A. CÁC NỘI DUNG..."
# "muc_la_ma": mục dạng số La Mã, vd "I. Nội dung thành phần..."
LEVEL_ORDER  = {"phan": 0, "muc_hoa": 1, "chuong": 2, "muc_la_ma": 3,
                "muc": 4, "tieu_muc": 4, "dieu": 5}
BULLET_NAMES = {"khoan", "diem"}
BULLET_RANK  = {"khoan": 0, "diem": 1, "numsec_leaf": 0, "dash": 1, "plus": 2}

_RE_NUMSEC        = re.compile(r"^\d{1,3}(?:\.\d{1,3}){1,4}")
_RE_LETTER        = re.compile(r"[A-Za-zÀ-Ỹà-ỹ]")
_RE_DASH          = re.compile(r"^-\s+\S")
_RE_PLUS          = re.compile(r"^\+\s+\S")
_RE_SENTENCE_END  = re.compile(r"[.;:]\s*$")

# Mục lớn 1 chữ cái ("A.", "B.", "C.") và mục La Mã ("I.", "II.", ...)
_RE_ROMAN_MULTI   = re.compile(r"^([IVXLCDM]{2,})\.\s+(\S.*)$")
_RE_SINGLE_LETTER = re.compile(r"^([A-ZĐ])\.\s+(\S.*)$")
_ROMAN_CHARS      = set("IVXLCDM")


def _is_all_upper_title(text: str) -> bool:
    """True nếu phần chữ trong text đều viết hoa (kiểu tiêu đề mục lớn)."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c == c.upper() for c in letters)


def _classify_letter_roman(line: str) -> Optional[str]:
    """
    Phân biệt 2 kiểu mục dễ nhầm lẫn vì cùng dùng 1 chữ cái:
      - "muc_hoa":   A. B. C. ... (tiêu đề thường viết HOA TOÀN BỘ)
      - "muc_la_ma": I. II. III. ... (tiêu đề chỉ viết hoa chữ đầu)
    Chuỗi La Mã từ 2 ký tự trở lên (II., III., IV., ...) là không thể nhầm nên
    luôn được nhận là muc_la_ma. Với 1 ký tự (I., V., X., L., C., D., M. - vừa
    có thể là chữ cái thường vừa có thể là số La Mã) thì dựa vào cách viết hoa
    của phần tiêu đề phía sau để quyết định.
    """
    m = _RE_ROMAN_MULTI.match(line)
    if m:
        return "muc_la_ma"
    m = _RE_SINGLE_LETTER.match(line)
    if m:
        letter, rest = m.group(1), m.group(2)
        if letter in _ROMAN_CHARS and not _is_all_upper_title(rest):
            return "muc_la_ma"
        return "muc_hoa"
    return None


# Ký tự vô hình dùng để "phá" một dòng trông giống số/chữ thứ tự (khoản,
# numsec, điểm, mục chữ hoa, mục La Mã) nhưng thực ra không nối tiếp đúng
# dãy — nhờ vậy các regex nhận diện phía dưới sẽ không khớp nữa và dòng đó
# được xử lý như văn bản thường.
_SEQ_BREAK = "\u2063"
_RE_LEADING_DIGITS = re.compile(r"^\d+")

# Thứ tự bảng chữ cái tiếng Việt dùng cho điểm ("a)", "b)"...) và mục lớn
# chữ hoa ("A.", "B."...): "đ" xếp ngay sau "d", trước "e".
_VN_LOWER_ORDER = "abcdđefghijklmnopqrstuvwxyz"
_VN_UPPER_ORDER = "ABCDĐEFGHIJKLMNOPQRSTUVWXYZ"

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

# "Độ sâu" tương đối của từng loại đánh số, dùng để quyết định khi gặp một
# heading ở độ sâu O thì những bộ đếm nào (sâu hơn O) cần được reset.
# Thứ bậc: phan(0) > muc_hoa(1) > chuong(2) > muc_la_ma(3) > muc/tieu_muc(4)
#          > dieu(5) > khoan/numsec(6) > diem(7)
_ORDER_MUC_HOA   = 1
_ORDER_MUC_LA_MA = 3
_ORDER_KHOAN     = 6
_ORDER_DIEM      = 7


def _letter_index(ch: str, order: str) -> Optional[int]:
    try:
        return order.index(ch)
    except ValueError:
        return None


def _roman_to_int(s: str) -> Optional[int]:
    total, prev = 0, 0
    for ch in reversed(s):
        val = _ROMAN_VALUES.get(ch)
        if val is None:
            return None
        total += -val if val < prev else val
        prev = max(prev, val)
    return total


class _SeqGuard:
    """Theo dõi số/chữ thứ tự khi quét văn bản theo thứ tự xuất hiện, để
    phát hiện các dòng CHỈ GIỐNG mẫu "1." / "3.1" / "a)" / "A." / "II."
    nhưng không thực sự nối tiếp dãy trước đó (vd một đoạn văn tình cờ bắt
    đầu bằng "7. ..." ngay sau khoản "2."). Trước đây code chỉ kiểm tra
    hình thức (regex khớp) mà không kiểm tra thứ tự.
    """

    def __init__(self) -> None:
        self.khoan_last: Optional[int] = None
        self.numsec_path: list[int] = []
        self.diem_last: Optional[int] = None
        self.muc_hoa_last: Optional[int] = None
        self.muc_la_ma_last: Optional[int] = None

    def reset_deeper_than(self, order: float) -> None:
        """Reset mọi bộ đếm ở cấp SÂU HƠN `order`, giữ nguyên các cấp cha."""
        if order < _ORDER_MUC_HOA:
            self.muc_hoa_last = None
        if order < _ORDER_MUC_LA_MA:
            self.muc_la_ma_last = None
        if order < _ORDER_KHOAN:
            self.khoan_last = None
            self.numsec_path = []
        if order < _ORDER_DIEM:
            self.diem_last = None

    def check_khoan(self, n: int) -> bool:
        # Không ép buộc phải bắt đầu từ 1 (đoạn trích có thể bị cắt), nhưng
        # từ số thứ hai trở đi bắt buộc phải là số liền trước + 1.
        ok = self.khoan_last is None or n == self.khoan_last + 1
        if ok:
            self.khoan_last = n
        return ok

    def check_numsec(self, so_hieu: str) -> bool:
        nums = [int(p) for p in so_hieu.split(".")]
        path = self.numsec_path
        if not path:
            ok = True  # mốc numsec đầu tiên trong phạm vi hiện tại
        else:
            d = len(nums)
            if d == len(path) + 1:
                # đi sâu thêm một cấp: phải là con đầu tiên (vd 3 -> 3.1)
                ok = nums[:-1] == path and nums[-1] == 1
            elif d <= len(path):
                # cùng cấp hoặc lùi lên cấp cha: phần tiền tố phải khớp và
                # số cuối phải tăng thêm 1 (vd 3.2 -> 3.3, hoặc 1.2.1 -> 1.3)
                ok = nums[:-1] == path[: d - 1] and nums[-1] == path[d - 1] + 1
            else:
                ok = False
        if ok:
            self.numsec_path = nums
        return ok

    def check_diem(self, letter: str) -> bool:
        idx = _letter_index(letter, _VN_LOWER_ORDER)
        if idx is None:
            return False
        ok = self.diem_last is None or idx == self.diem_last + 1
        if ok:
            self.diem_last = idx
        return ok

    def check_muc_hoa(self, letter: str) -> bool:
        idx = _letter_index(letter, _VN_UPPER_ORDER)
        if idx is None:
            return False
        ok = self.muc_hoa_last is None or idx == self.muc_hoa_last + 1
        if ok:
            self.muc_hoa_last = idx
        return ok

    def check_muc_la_ma(self, roman: str) -> bool:
        val = _roman_to_int(roman)
        if val is None:
            return False
        ok = self.muc_la_ma_last is None or val == self.muc_la_ma_last + 1
        if ok:
            self.muc_la_ma_last = val
        return ok


def _insert_seq_break(core: str, end: int) -> str:
    return core[:end] + _SEQ_BREAK + core[end:]


def guard_sequence(text: str) -> str:
    """Duyệt qua toàn bộ văn bản theo thứ tự dòng và vô hiệu hoá các dòng
    "1./2./3.", "3.1/3.2", "a)/b)", "A./B." hay "I./II." không thực sự nối
    tiếp dãy hợp lệ, bằng cách chèn _SEQ_BREAK để các bước nhận diện
    heading/bullet phía sau bỏ qua chúng (coi như văn bản thường). Việc
    đánh số/chữ được reset theo đúng phân cấp mỗi khi gặp một heading ở cấp
    cha (Phần/Chương/Mục/Điều/mục La Mã/mục chữ hoa/khoản...), vì văn bản
    luật thường đánh lại từ đầu ở mỗi cấp con mới.
    """
    guard = _SeqGuard()
    out_lines: list[str] = []
    for ln in text.split("\n"):
        if not ln:
            out_lines.append(ln)
            continue

        has_dash = bool(_RE_DASH.match(ln))
        core = ln[1:].strip() if has_dash else ln
        prefix = ln[: len(ln) - len(core)]

        # 1) numsec: "3.1", "1.2.3", ...
        so_hieu = _numbered_section_id(core)
        if so_hieu:
            if guard.check_numsec(so_hieu):
                guard.reset_deeper_than(_ORDER_KHOAN)
                out_lines.append(ln)
            else:
                end = _RE_LEADING_DIGITS.match(core).end()
                out_lines.append(prefix + _insert_seq_break(core, end))
            continue

        # 2) mục lớn dạng chữ cái hoa ("A.") hoặc dạng La Mã ("I.", "II.")
        letter_roman = _classify_letter_roman(core)
        if letter_roman == "muc_hoa":
            m = _RE_SINGLE_LETTER.match(core)
            if guard.check_muc_hoa(m.group(1)):
                guard.reset_deeper_than(_ORDER_MUC_HOA)
                out_lines.append(ln)
            else:
                out_lines.append(prefix + _insert_seq_break(core, 1))
            continue
        if letter_roman == "muc_la_ma":
            m = _RE_ROMAN_MULTI.match(core) or _RE_SINGLE_LETTER.match(core)
            roman = m.group(1)
            if guard.check_muc_la_ma(roman):
                guard.reset_deeper_than(_ORDER_MUC_LA_MA)
                out_lines.append(ln)
            else:
                out_lines.append(prefix + _insert_seq_break(core, len(roman)))
            continue

        # 3) khoan: "1.", "2." ...
        if _RE_KHOAN.match(core):
            n = int(_RE_LEADING_DIGITS.match(core).group(0))
            if guard.check_khoan(n):
                guard.reset_deeper_than(_ORDER_KHOAN)
                out_lines.append(ln)
            else:
                end = _RE_LEADING_DIGITS.match(core).end()
                out_lines.append(prefix + _insert_seq_break(core, end))
            continue

        # 4) diem: "a)", "b)", "đ)" ...
        if _RE_DIEM.match(core):
            if guard.check_diem(core[0]):
                out_lines.append(ln)
            else:
                out_lines.append(prefix + _insert_seq_break(core, 1))
            continue

        # 5) các heading cấu trúc khác (Phần/Chương/Mục/Tiểu mục/Điều) →
        # reset mọi bộ đếm ở cấp sâu hơn heading này.
        r = _raw_level(ln)
        if r and r[0] == "fixed":
            guard.reset_deeper_than(r[1])
        out_lines.append(ln)

    return "\n".join(out_lines)


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
    # Nhiều văn bản gói cả khoản/điểm vào trong gạch đầu dòng, dạng
    # "- 1. Nội dung...", "- a) Nội dung...". Bóc "-" ra để nhận diện đúng
    # cấp độ thật sự bên trong, thay vì coi tất cả là bullet chung chung.
    has_dash = bool(_RE_DASH.match(line))
    core = line[1:].strip() if has_dash else line

    so_hieu = _numbered_section_id(core)
    if so_hieu:
        return "numsec", so_hieu.count(".")

    letter_roman = _classify_letter_roman(core)
    if letter_roman:
        return "fixed", LEVEL_ORDER[letter_roman]

    for level, pat in LEVELS:
        if pat.match(core):
            if level in BULLET_NAMES:
                return "bullet", BULLET_RANK[level]
            return "fixed", LEVEL_ORDER[level]

    if _RE_PLUS.match(line):
        return "bullet", BULLET_RANK["plus"]
    if has_dash:
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
            block = " ".join(para).strip().replace(_SEQ_BREAK, "")
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
            cleaned = guard_sequence(cleaned)
            depth_map = build_depth_map(cleaned)
            merged = merge_lines(cleaned, depth_map)
            parse_to_md(merged, lines, depth_map)
            lines.append("\n---\n")
        except Exception as e:
            errors.append({"id": rec.get("id"), "error": str(e)})

    open(output_path, "w", encoding="utf-8").write("\n".join(lines).replace(_SEQ_BREAK, ""))

    total = sum(len(l) for l in lines)
    print(f"✅ {len(records)-len(errors)}/{len(records)} → {output_path} ({total:,} chars)")
    if errors:
        print(f"❌ {errors}")