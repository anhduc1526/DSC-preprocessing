import re
import glob
import json
from typing import Optional

_RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# Markdown link: [text](url) -> giữ lại "text", bỏ url
_RE_MD_LINK = re.compile(r"\[([^\]]*)\]\((?:https?://|www\.)[^\)]*\)")
# URL trần (http/https hoặc www...)
_RE_RAW_URL = re.compile(r"(?:https?://|www\.)\S+")


def _strip_urls(text: str) -> str:
    """Loại bỏ markdown-link và URL trần khỏi text, chỉ giữ lại phần chữ."""
    text = _RE_MD_LINK.sub(lambda m: m.group(1), text)
    text = _RE_RAW_URL.sub("", text)
    # dọn khoảng trắng dư ra sau khi xóa url
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([,.;:])", r"\1", text)
    return text.strip()


def _normalize_whitespace(text: str) -> str:
    """
    Chuẩn hoá xuống dòng:
    - \\r\\n hoặc \\r đơn -> \\n
    - Nhiều dòng trống liên tiếp (đoạn văn mới) -> ". " (nếu câu trước chưa có dấu kết câu)
    - Xuống dòng đơn (cùng đoạn) -> " "
    - Dọn khoảng trắng thừa
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Nhiều \n liên tiếp = ngắt đoạn -> nối bằng ". " để tách ý rõ ràng
    def _para_join(m: re.Match) -> str:
        return ". "

    text = re.sub(r"\n{2,}", _para_join, text)
    # \n đơn còn lại (xuống dòng trong cùng đoạn) -> khoảng trắng
    text = text.replace("\n", " ")

    # dọn dấu ". ." hoặc khoảng trắng kép sinh ra do thay thế
    text = re.sub(r"\.\s*\.", ".", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text.strip()


class Node:
    def __init__(self, title: str, level: int):
        self.title = title
        self.level = level
        self.content_lines: list[str] = []
        self.children: list["Node"] = []


def parse_md_tree(block_text: str) -> Optional[Node]:
    root = Node("__root__", 0)
    stack = [root]
    for raw in block_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _RE_HEADING.match(raw)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            node = Node(title, level)
            while stack[-1].level >= level:
                stack.pop()
            stack[-1].children.append(node)
            stack.append(node)
        else:
            ln = raw.strip()
            if ln:
                stack[-1].content_lines.append(ln)
    return root.children[0] if root.children else None


def collect_segments(node: Node, path_stack: list[str], out: list[dict]) -> None:
    current_path = path_stack + [_strip_urls(node.title)]

    content = "\n".join(node.content_lines).strip()
    content = _strip_urls(content)
    content = _normalize_whitespace(content)

    if content:
        path_str = " > ".join(p for p in current_path if p)
        out.append({
            "path": path_str,
            "content": content,
            "segment_type": "structured",
        })

    for child in node.children:
        collect_segments(child, current_path, out)


def md_to_segments(block_text: str) -> list[dict]:
    root_node = parse_md_tree(block_text)
    if root_node is None:
        return []

    out: list[dict] = []

    # Nội dung nằm trước heading đầu tiên (nếu có)
    root_content = "\n".join(root_node.content_lines).strip()
    root_content = _strip_urls(root_content)
    root_content = _normalize_whitespace(root_content)

    if root_content:
        segment_type = "structured" if root_node.children else "unstructured_whole"
        # nếu có children -> đây chỉ là đoạn mở đầu (preamble)
        if root_node.children:
            segment_type = "root_preamble"
        out.append({
            "path": "",
            "content": root_content,
            "segment_type": segment_type,
        })

    for child in root_node.children:
        collect_segments(child, [], out)

    return out


_TYPE_MAP_RAW = {
    ("thong", "tu", "lien", "tich"): "Thông tư liên tịch",
    ("nghi", "quyet", "lien", "tich"): "Nghị quyết liên tịch",
    ("quy", "chuan", "ky", "thuat", "quoc", "gia"): "Quy chuẩn kỹ thuật quốc gia",
    ("quyet", "dinh"): "Quyết định",
    ("nghi", "dinh"): "Nghị định",
    ("thong", "tu"): "Thông tư",
    ("nghi", "quyet"): "Nghị quyết",
    ("phap", "lenh"): "Pháp lệnh",
    ("chi", "thi"): "Chỉ thị",
    ("thong", "bao"): "Thông báo",
    ("cong", "van"): "Công văn",
    ("cong", "dien"): "Công điện",
    ("bo", "luat"): "Bộ luật",
    ("luat",): "Luật",
    ("hien", "phap"): "Hiến pháp",
    ("sac", "lenh"): "Sắc lệnh",
    ("quy", "che"): "Quy chế",
    ("quy", "dinh"): "Quy định",
    ("ke", "hoach"): "Kế hoạch",
    ("huong", "dan"): "Hướng dẫn",
    ("bao", "cao"): "Báo cáo",
    ("cong", "uoc"): "Công ước",
    ("dieu", "le"): "Điều lệ",
    ("quy", "chuan"): "Quy chuẩn",
    ("van", "ban", "hop", "nhat"): "Văn bản hợp nhất",
}

# Các cụm mở đầu khác nhau nhưng cùng dẫn tới TCVN/QCVN, vd
# "Tieu-chuan-Viet-Nam-TCVN-8710-1-2011-..." nên được coi như bắt đầu
# bằng "TCVN" (bỏ phần tiền tố chữ này đi trước khi xử lý tiếp).
_TCVN_PREFIX_ALIASES = [
    ("tieu", "chuan", "viet", "nam"),
    ("tieu", "chuan", "quoc", "gia"),
]

# Các cụm từ nối biểu thị VB này sửa đổi/bổ sung/thay thế/bãi bỏ VB khác,
# vd "Thong-tu-sua-doi-Thong-tu-02-2021-TT-BNV-..."
# (ưu tiên chuỗi token dài nhất khớp, giống _TYPE_MAP_RAW)
_AMEND_CONNECTOR_RAW = {
    ("sua", "doi", "bo", "sung"): "sửa đổi, bổ sung",
    ("bo", "sung", "sua", "doi"): "bổ sung, sửa đổi",
    ("sua", "doi"): "sửa đổi",
    ("bo", "sung"): "bổ sung",
    ("bai", "bo"): "bãi bỏ",
    ("huy", "bo"): "hủy bỏ",
    ("thay", "the"): "thay thế",
}

# Một số ký hiệu cơ quan/loại VB cần khôi phục dấu (D -> Đ, ...)
# - khớp NGUYÊN token (vd "QD" -> "QĐ")
_AGENCY_FIX = {"QD": "QĐ", "ND": "NĐ", "HD": "HĐ", "CD": "CĐ"}
# - khớp CỤM CON bên trong token dài hơn (vd "TWDTN" -> "TWĐTN")
_AGENCY_SUBSTR_FIX = [
    ("TWD", "TWĐ"),  # Trung ương Đoàn / Trung ương Đảng, vd TWDTN, TWDCS...
]


def _is_agency_code_token(t: str) -> bool:
    """Token được coi là 'mã cơ quan/đơn vị' (kiểu QD, VKSTC, TTg, T1, K2...)
    nếu có ít nhất 1 chữ hoa, và tổng (số chữ hoa + số chữ số) >= 2.

    - "QD", "VKSTC", "TANDTC" -> toàn chữ hoa, >=2 chữ hoa -> True
    - "TTg" -> 2 chữ hoa (dù có 1 chữ thường "g" theo quy ước viết tắt
      "Thủ tướng Chính phủ") -> True
    - "T1" -> 1 chữ hoa + 1 chữ số = tổng 2 -> True (trước đây bị loại oan
      vì chỉ đếm chữ hoa, không tính chữ số)
    - "Quy", "che", "Vien" -> chỉ 1 chữ hoa (chữ cái đầu), không có chữ số
      -> False, vẫn được coi là từ tiếng Việt thường, không phải mã cơ quan
    """
    upper_count = sum(1 for c in t if c.isupper())
    digit_count = sum(1 for c in t if c.isdigit())
    return upper_count >= 1 and (upper_count + digit_count) >= 2


def _fix_agency_token(tok: str) -> str:
    up = tok.upper()
    if up in _AGENCY_FIX:
        return _AGENCY_FIX[up]
    for old, new in _AGENCY_SUBSTR_FIX:
        idx = up.find(old)
        if idx != -1:
            return tok[:idx] + new + tok[idx + len(old):]
    return tok


def label_from_name(name: str) -> str:
    """Suy ra 'label' (số hiệu văn bản, có dấu) từ trường 'name' (không dấu, nối bằng '-').

    Vd:
      Quyet-dinh-36-2012-QD-TTg-...-147304
        -> "Quyết định 36/2012/QĐ-TTg"
      Cong-van-45-TANDTC-PC-2020-...-438602
        -> "Công văn 45/TANDTC-PC năm 2020"
      TCVN-ISO-IEC-17020-2012-...-914763
        -> "Tiêu chuẩn quốc gia TCVN 17020:2012"

    Trả về chuỗi rỗng nếu không suy luận được.
    """
    if not name:
        return ""

    tokens = name.split("-")
    # bỏ token ID cuối cùng (số dài, thường 5-6 chữ số) nếu có
    if tokens and tokens[-1].isdigit() and len(tokens[-1]) > 4:
        tokens = tokens[:-1]

    lower_tokens = [t.lower() for t in tokens]

    # Bỏ tiền tố dạng chữ đứng trước mã TCVN (vd "Tieu-chuan-Viet-Nam-TCVN-...")
    # để xử lý thống nhất như khi tên bắt đầu thẳng bằng "TCVN-..."
    for prefix_tokens in _TCVN_PREFIX_ALIASES:
        plen = len(prefix_tokens)
        if (
            lower_tokens[:plen] == list(prefix_tokens)
            and len(lower_tokens) > plen
            and lower_tokens[plen] in ("tcvn", "qcvn")
        ):
            tokens = tokens[plen:]
            lower_tokens = lower_tokens[plen:]
            break

    # --- TCVN / QCVN: Type-[ISO-IEC...]-Number-Year -> "{Type} {CODE} number:year"
    # Mã đôi khi dính liền với phần theo sau (không có dấu "-"), vd
    # "TCVNISO-IEC17021-1-2015-..." hoặc "TCVN4319-2012-...", nên cần tách
    # trước khi xử lý.
    if lower_tokens and lower_tokens[0][:4] in ("tcvn", "qcvn"):
        code_key = lower_tokens[0][:4]
        prefix = "Tiêu chuẩn quốc gia" if code_key == "tcvn" else "Quy chuẩn kỹ thuật quốc gia"
        base_code = code_key.upper()

        # Phần còn lại ngay sau mã, nếu dính liền (vd "TCVNISO" -> "ISO",
        # "TCVN4319" -> "4319"), coi như 1 token riêng đứng đầu danh sách.
        work_tokens = ([tokens[0][4:]] if len(tokens[0]) > 4 else []) + tokens[1:]

        # Tách tiếp các token dạng CHỮ+SỐ dính liền khác (vd "IEC17021" -> "IEC","17021")
        rest_tokens: list[str] = []
        for t in work_tokens:
            m = re.match(r"^([A-Za-z]+)(\d.*)$", t)
            if m:
                rest_tokens.append(m.group(1))
                rest_tokens.append(m.group(2))
            else:
                rest_tokens.append(t)

        idx_num = None
        for i in range(0, len(rest_tokens)):
            if rest_tokens[i].isdigit():
                idx_num = i
                break
        if idx_num is None:
            return ""

        # Mã tổ chức quốc tế xen giữa (vd ISO, IEC) nằm giữa TCVN/QCVN và số hiệu
        # -> "TCVN ISO 9001" hoặc "TCVN ISO/IEC 17020" (nhiều mã nối nhau bằng "/")
        extra_code_tokens = [t.upper() for t in rest_tokens[0:idx_num]]
        code = f"{base_code} {'/'.join(extra_code_tokens)}" if extra_code_tokens else base_code

        # Gom các token số liên tiếp thành 1 "run" (số hiệu có thể nhiều phần, vd 8400-44)
        run = []
        j = idx_num
        while j < len(rest_tokens) and rest_tokens[j].isdigit():
            run.append(rest_tokens[j])
            j += 1

        # Nếu run có >=2 phần và phần cuối đúng 4 chữ số -> đó là năm, phần còn lại là số hiệu
        year = None
        if len(run) >= 2 and len(run[-1]) == 4:
            year = run[-1]
            number = "-".join(run[:-1])
        else:
            number = "-".join(run)

        agency = None
        codex_ref = None
        if j < len(rest_tokens):
            cand = rest_tokens[j]
            # Trường hợp đặc biệt: TCVN tương đương/dựa trên tiêu chuẩn quốc tế
            # CODEX STAN, vd "TCVN-10746-2015-CODEX-STAN-214-1999-..."
            #   -> "... (CODEX STAN 214-1999)"
            if (
                cand.upper() == "CODEX"
                and j + 1 < len(rest_tokens)
                and rest_tokens[j + 1].upper() == "STAN"
            ):
                codex_num_tokens = []
                k = j + 2
                while k < len(rest_tokens) and rest_tokens[k].isdigit():
                    codex_num_tokens.append(rest_tokens[k])
                    k += 1
                if len(codex_num_tokens) >= 2 and len(codex_num_tokens[-1]) == 4:
                    codex_year = codex_num_tokens[-1]
                    codex_number = "-".join(codex_num_tokens[:-1])
                    codex_ref = f"CODEX STAN {codex_number}-{codex_year}"
                elif codex_num_tokens:
                    codex_ref = f"CODEX STAN {'-'.join(codex_num_tokens)}"
                else:
                    codex_ref = "CODEX STAN"
            # Trường hợp TCVN tương đương/dựa trên tiêu chuẩn ASEAN STAN, vd
            # "TCVN-11508-2016-ASEAN-STAN-28-2012-..." -> "(ASEAN STAN 28/2012)"
            # (tương tự CODEX STAN, chỉ khác dấu nối số hiệu/năm dùng "/" thay vì "-").
            elif (
                cand.upper() == "ASEAN"
                and j + 1 < len(rest_tokens)
                and rest_tokens[j + 1].upper() == "STAN"
            ):
                asean_num_tokens = []
                k = j + 2
                while k < len(rest_tokens) and rest_tokens[k].isdigit():
                    asean_num_tokens.append(rest_tokens[k])
                    k += 1
                if len(asean_num_tokens) >= 2 and len(asean_num_tokens[-1]) == 4:
                    asean_year = asean_num_tokens[-1]
                    asean_number = "-".join(asean_num_tokens[:-1])
                    codex_ref = f"ASEAN STAN {asean_number}-{asean_year}"
                elif asean_num_tokens:
                    codex_ref = f"ASEAN STAN {'-'.join(asean_num_tokens)}"
                else:
                    codex_ref = "ASEAN STAN"
            elif _is_agency_code_token(cand):
                agency = _fix_agency_token(cand)

        result = f"{prefix} {code} {number}"
        if year:
            result += f":{year}"
        if codex_ref:
            result += f" ({codex_ref})"
        elif agency:
            result += f"/{agency}"
        return result

    # --- match loại văn bản (ưu tiên chuỗi token dài nhất khớp) ---
    matched_type = None
    matched_key_tokens = None
    matched_len = 0
    for key_tokens, label in _TYPE_MAP_RAW.items():
        klen = len(key_tokens)
        if lower_tokens[:klen] == list(key_tokens) and klen > matched_len:
            matched_type = label
            matched_key_tokens = key_tokens
            matched_len = klen
    if matched_type is None:
        return ""

    rest = tokens[matched_len:]
    rest_lower = lower_tokens[matched_len:]

    # --- văn bản sửa đổi/bổ sung/... văn bản khác, vd:
    # "Thong-tu-sua-doi-Thong-tu-02-2021-TT-BNV-xep-luong-..."
    #   -> "Thông tư sửa đổi Thông tư 02/2021/TT-BNV"
    connector = None
    connector_len = 0
    for key_tokens, phrase in _AMEND_CONNECTOR_RAW.items():
        klen = len(key_tokens)
        if rest_lower[:klen] == list(key_tokens) and klen > connector_len:
            connector = phrase
            connector_len = klen
    if connector:
        remainder_tokens = rest[connector_len:]
        remainder_lower = rest_lower[connector_len:]
        matched_type2 = None
        matched_key_tokens2 = None
        matched_len2 = 0
        for key_tokens, label in _TYPE_MAP_RAW.items():
            klen = len(key_tokens)
            if remainder_lower[:klen] == list(key_tokens) and klen > matched_len2:
                matched_type2 = label
                matched_key_tokens2 = key_tokens
                matched_len2 = klen
        if matched_type2:
            rest3 = remainder_tokens[matched_len2:]
            tail = _parse_number_year_agency(matched_type2, matched_key_tokens2, rest3)
            if tail:
                return f"{matched_type} {connector} {tail}".strip()
            return f"{matched_type} {connector} {matched_type2}".strip()
        # không tìm thấy loại VB thứ hai sau connector -> bỏ qua, xử lý bình thường

    return _parse_number_year_agency(matched_type, matched_key_tokens, rest)


def _parse_number_year_agency(matched_type: str, matched_key_tokens, rest: list) -> str:
    """Suy ra phần 'số hiệu/năm/cơ quan' còn lại sau khi đã xác định loại văn bản
    (matched_type), trả về chuỗi đầy đủ bắt đầu bằng matched_type. Trả về ""
    nếu không suy luận được gì."""
    # Bỏ từ đệm "so" (số) nếu đứng ngay sau loại VB, vd "Huong-dan-so-65-..."
    if rest and rest[0].lower() == "so":
        rest = rest[1:]

    # --- Riêng "Luật"/"Bộ luật": KHÔNG lấy số hiệu văn bản (vd "08/2017/QH14"),
    # mà lấy TÊN LUẬT bằng chữ đứng sau, vd:
    # "Luat-08-2017-QH14-Thuy-loi-2017-322933" -> "Luật Thuy loi năm 2017"
    # (bỏ qua phần số hiệu/năm/mã cơ quan ở đầu, lấy các từ chữ theo sau làm
    # tên luật, và năm ban hành 4 chữ số theo sau tên luật đó).
    if matched_key_tokens in (("luat",), ("bo", "luat")):
        idx = 0
        while idx < len(rest) and (rest[idx].isdigit() or _is_agency_code_token(rest[idx])):
            idx += 1
        title_tokens: list = []
        year = None
        j = idx
        while j < len(rest):
            if rest[j].isdigit() and len(rest[j]) == 4:
                year = rest[j]
                break
            title_tokens.append(rest[j])
            j += 1
        title = " ".join(title_tokens)
        if title:
            title = title[0].upper() + title[1:]
        if title and year:
            return f"{matched_type} {title} năm {year}".strip()
        if title:
            return f"{matched_type} {title}".strip()
        if year:
            return f"{matched_type} năm {year}".strip()
        return matched_type

    if not rest or not rest[0].isdigit():
        # Trường hợp không có số hiệu ngay sau loại VB, vd:
        # "Luat-cong-nghe-cao-2008-21-2008-QH12" -> "Luật Công nghệ cao 2008"
        # (tên luật bằng chữ, theo sau là năm ban hành)
        year_idx = None
        for i, t in enumerate(rest):
            if t.isdigit() and len(t) == 4:
                year_idx = i
                break
        if year_idx is not None and year_idx > 0:
            title_tokens = rest[:year_idx]
            year = rest[year_idx]
            title = " ".join(title_tokens)
            if title:
                title = title[0].upper() + title[1:]
            return f"{matched_type} {title} {year}".strip()
        # Không có số hiệu và cũng không có năm 4 chữ số nào trong phần còn lại
        # -> vẫn trả về loại VB + toàn bộ phần tiêu đề bằng chữ, thay vì bỏ trắng.
        # vd "Nghi-dinh-quy-dinh-xu-phat-...-an-ninh-mang"
        #   -> "Nghị định quy dinh xu phat vi pham hanh chinh trong linh vuc an ninh mang"
        title = " ".join(rest)
        if title:
            title = title[0].upper() + title[1:]
            return f"{matched_type} {title}".strip()
        return matched_type
    number = rest[0]
    rest2 = rest[1:]

    # tìm năm: token số có đúng 4 chữ số
    year_idx = None
    for i, t in enumerate(rest2):
        if t.isdigit() and len(t) == 4:
            year_idx = i
            break

    if year_idx == 0:
        # dạng chuẩn: Number-Year-AgencyCode...
        year = rest2[0]
        agency_tokens = []
        for t in rest2[1:]:
            if not _is_agency_code_token(t):
                break
            agency_tokens.append(_fix_agency_token(t))
        if agency_tokens:
            return f"{matched_type} {number}/{year}/{'-'.join(agency_tokens)}"
        return f"{matched_type} {number}/{year}"

    if year_idx is not None:
        # dạng ngoại lệ (vd Công văn): Number-AgencyCode...-Year-mô tả
        pre_year_tokens = rest2[:year_idx]
        year = rest2[year_idx]

        # Trường hợp riêng của "Hướng dẫn": số hiệu có dạng "66-HD/TWĐTN-BTC",
        # trong đó "HD" ngay sau number chính là ký hiệu của LOẠI văn bản
        # (giữ nguyên, nối bằng "-"), còn phần sau là cơ quan ban hành (nối bằng "/").
        # Khác với "QD"/"ND" vốn là ký hiệu CƠ QUAN nên vẫn xử lý theo nhánh mặc định.
        if (
            matched_key_tokens == ("huong", "dan")
            and pre_year_tokens
            and pre_year_tokens[0].upper() == "HD"
        ):
            first_code = pre_year_tokens[0]
            agency_tokens = [
                _fix_agency_token(t)
                for t in pre_year_tokens[1:]
                if _is_agency_code_token(t)
            ]
            if agency_tokens:
                return f"{matched_type} {number}-{first_code}/{'-'.join(agency_tokens)} năm {year}"
            return f"{matched_type} {number}-{first_code} năm {year}"

        agency_tokens = [
            _fix_agency_token(t)
            for t in pre_year_tokens
            if _is_agency_code_token(t)
        ]
        if agency_tokens:
            return f"{matched_type} {number}/{'-'.join(agency_tokens)} năm {year}"
        return f"{matched_type} {number} năm {year}"

    # Không có năm ở đâu cả (vd "08-CP-phe-chuan-..."): nếu token ngay sau
    # number là mã cơ quan (>=2 chữ hoa liên tiếp), gom các token liên tiếp
    # kiểu này lại làm mã cơ quan, phần còn lại (chữ thường) là mô tả nên bỏ qua.
    # Riêng "Hướng dẫn": nếu token đầu tiên là "HD" thì đó là ký hiệu của
    # LOẠI văn bản (giữ nguyên, không đổi thành "HĐ" như mã cơ quan thường thấy).
    agency_tokens = []
    for i, t in enumerate(rest2):
        if not _is_agency_code_token(t):
            break
        if i == 0 and matched_key_tokens == ("huong", "dan") and t.upper() == "HD":
            agency_tokens.append(t)
        else:
            agency_tokens.append(_fix_agency_token(t))
    if agency_tokens:
        return f"{matched_type} {number}/{'-'.join(agency_tokens)}"
    return f"{matched_type} {number}"


def name_from_link(link: str) -> str:
    """Suy ra 'name' từ 'link': lấy phần cuối cùng sau dấu '/' cuối, bỏ phần
    mở rộng sau dấu '.' cuối cùng (vd '.aspx').
    Vd: 'https://.../Quyet-dinh-36-2012-QD-TTg-...-147304.aspx'
        -> 'Quyet-dinh-36-2012-QD-TTg-...-147304'
    """
    if not link:
        return ""
    last = link.rstrip("/").rsplit("/", 1)[-1]
    if "." in last:
        last = last.rsplit(".", 1)[0]
    return last


def ensure_name(rec: dict) -> dict:
    """Thêm trường 'name' nếu record chưa có (hoặc rỗng), suy ra từ 'link'.
    Không ghi đè nếu 'name' đã tồn tại và có giá trị."""
    if not rec.get("name"):
        rec["name"] = name_from_link(rec.get("link", ""))
    if not rec.get("label"):
        rec["label"] = label_from_name(rec.get("name", ""))
    return rec


def load_records(pattern: str) -> list[dict]:
    records = []
    for path in sorted(glob.glob(pattern)):
        data = json.load(open(path, encoding="utf-8"))
        recs = data if isinstance(data, list) else [data]
        records.extend(ensure_name(rec) for rec in recs)
    return records


def load_md_blocks(md_path: str) -> list[str]:
    text = open(md_path, encoding="utf-8").read()
    blocks = re.split(r"\n-{3,}\n", text)
    return [b.strip() for b in blocks if b.strip()]


def build_segments_json(json_pattern: str, md_path: str, output_path: str) -> None:
    records = load_records(json_pattern)
    blocks = load_md_blocks(md_path)

    if len(records) != len(blocks):
        print(f"⚠️ số record ({len(records)}) khác số block trong md ({len(blocks)}), ghép theo thứ tự")

    new_records = []
    for rec, block in zip(records, blocks):
        new_rec = {k: v for k, v in rec.items() if k != "passage"}
        new_rec["passage_segments"] = md_to_segments(block)   # giờ là list[dict]
        new_records.append(new_rec)

    json.dump(new_records, open(output_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✅ {len(new_records)}/{len(records)} → {output_path}")


if __name__ == "__main__":
    build_segments_json("law.json", "processed.md", "law_segments.json")