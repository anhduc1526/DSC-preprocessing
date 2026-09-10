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
    ("hiep", "dinh"): "Hiệp định",
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


def _match_doc_type(lower_tokens: list) -> tuple:
    """Tìm loại văn bản khớp dài nhất ở ĐẦU danh sách token (đã lowercase).
    Trả về (label, key_tokens, matched_len) hoặc (None, None, 0) nếu không khớp."""
    matched_type = None
    matched_key_tokens = None
    matched_len = 0
    for key_tokens, label in _TYPE_MAP_RAW.items():
        klen = len(key_tokens)
        if lower_tokens[:klen] == list(key_tokens) and klen > matched_len:
            matched_type = label
            matched_key_tokens = key_tokens
            matched_len = klen
    return matched_type, matched_key_tokens, matched_len


def _match_connector(lower_tokens: list) -> tuple:
    """Tìm cụm nối kiểu 'sửa đổi'/'bổ sung'/... khớp dài nhất ở ĐẦU danh sách
    token (đã lowercase). Trả về (phrase, matched_len) hoặc (None, 0)."""
    connector = None
    connector_len = 0
    for key_tokens, phrase in _AMEND_CONNECTOR_RAW.items():
        klen = len(key_tokens)
        if lower_tokens[:klen] == list(key_tokens) and klen > connector_len:
            connector = phrase
            connector_len = klen
    return connector, connector_len


def _plausible_second_doc(matched_key_tokens: tuple, tokens_after_type: list) -> bool:
    """Một số tên loại văn bản (vd 'quy định', 'hướng dẫn', 'báo cáo') cũng là
    cụm từ tiếng Việt thông thường, rất hay xuất hiện trong PHẦN MÔ TẢ của
    chính văn bản 1 (vd "Nghị định 15/2020/NĐ-CP quy định xử phạt..."), chứ
    không phải đang trích dẫn một văn bản khác. Để tránh nhận nhầm, chỉ coi
    là 'văn bản thứ 2 thật sự' khi có bằng chứng cụ thể theo ngay sau:
      - có số hiệu (token số) ngay sau tên loại VB, hoặc
      - riêng "Luật"/"Bộ luật": từ khoá này đủ đặc trưng (hiếm khi xuất hiện
        tình cờ như văn tiếng Việt thông thường), nên LUÔN được chấp nhận,
        không cần số hiệu/năm đi kèm, vd "...-Luat-dat-dai-..." -> "Luật Dat dai".
    """
    if tokens_after_type and tokens_after_type[0].isdigit():
        return True
    if matched_key_tokens in (("luat",), ("bo", "luat")):
        return True
    return False


# Số token tối đa được phép "nhảy qua" (coi là đệm/nối) khi dò tìm
# "Luật"/"Bộ luật" ở phía trước, để tránh quét lan quá xa vào phần mô tả
# không liên quan.
_LUAT_LOOKAHEAD_WINDOW = 8


def _is_doc_type_start_token(tok: str) -> bool:
    """Trong các slug này, một từ khoá LOẠI VĂN BẢN (Luật, Nghị định, Pháp
    lệnh...) chỉ thực sự đánh dấu một VĂN BẢN KHÁC đang được TRÍCH DẪN khi
    từ đó được viết hoa chữ cái đầu - đúng theo quy ước của nguồn dữ liệu
    (mỗi văn bản/cụm từ khoá mới bắt đầu bằng chữ hoa). Nếu viết thường, đó
    chỉ là một từ tiếng Việt bình thường xuất hiện tình cờ trong mô tả, vd
    "luat" trong "...-phap-luat-giao-thong-..." (pháp luật = luật pháp nói
    chung, không phải trích dẫn một Luật cụ thể) -> KHÔNG được coi là một
    loại văn bản mới. Ngược lại "Luat" viết hoa trong "...-Luat-giao-thong-
    duong-bo-..." mới thực sự là bắt đầu 1 văn bản khác."""
    return bool(tok) and tok[0].isupper()


def _match_next_doc_type(lower_tokens: list, tokens: list) -> Optional[tuple]:
    """Thử tìm 'loại văn bản tiếp theo' ngay ở ĐẦU danh sách token, CÓ THỂ có
    hoặc KHÔNG có từ nối (sửa đổi/bổ sung/bãi bỏ/...) đứng trước - từ nối là
    tuỳ chọn, không bắt buộc. Vd cả hai đều được coi là 'văn bản tiếp nối':
      "...-sua-doi-Nghi-dinh-..."   (có từ nối)
      "...-Nghi-dinh-..."           (không có từ nối, 2 loại VB đứng liền nhau)

    Để tránh nhận nhầm các cụm từ thông thường trùng tên loại VB (vd "quy
    định", "hướng dẫn"...) làm văn bản thứ 2 giả, kết quả CHỈ được chấp nhận
    NGAY LẬP TỨC (ở vị trí đầu) nếu _plausible_second_doc() xác nhận có bằng
    chứng số hiệu/năm đi kèm.

    Nếu vị trí đầu không khớp gì, hoặc khớp nhưng bị từ chối vì thiếu bằng
    chứng (vd "Hướng dẫn", "Quy định các"...), KHÔNG bỏ cuộc ngay - thay vào
    đó dò tiếp trong một cửa sổ giới hạn (_LUAT_LOOKAHEAD_WINDOW token) để
    tìm "Luật"/"Bộ luật" (từ khoá đủ đặc trưng, không cần bằng chứng số/năm).
    Mọi thứ đứng trước điểm tìm thấy (từ nối, từ đệm như "các"/"về", cụm loại
    VB bị từ chối...) coi là phần đệm, không cần giữ lại. Vd:
      "Thong-tu-huong-dan-Luat-phong-chong-rua-tien-..."
        -> bỏ qua "huong-dan", thấy "Luat" ngay sau -> chấp nhận.
      "Luat-sua-doi-cac-Luat-ve-thue-2014-..."
        -> bỏ qua "sua-doi-cac" (từ nối + từ đệm), thấy "Luat" -> chấp nhận.

    Trả về (connector_or_None, prefix_len, type_label, type_key_tokens,
    type_len, filler_text) nếu tìm thấy loại văn bản hợp lệ, hoặc None nếu
    không. `prefix_len` là tổng số token đã tiêu thụ trước khi type_label bắt
    đầu (gồm cả từ nối lẫn phần đệm bị nhảy qua, nếu có); `filler_text` là
    cụm từ đệm (viết thường, giữ nguyên từ gốc) tương ứng, hoặc "" nếu không
    có (không dùng để hiển thị nữa - vì VB1 không có số hiệu riêng nên khi
    tìm thấy VB2, ta chỉ lấy nhãn của VB2, bỏ hẳn phần đệm này)."""
    connector, connector_len = _match_connector(lower_tokens)
    after_lower = lower_tokens[connector_len:]
    after_tokens = tokens[connector_len:]

    matched_type, matched_key_tokens, matched_len = _match_doc_type(after_lower)
    if (
        matched_type is not None
        and after_tokens
        and _is_doc_type_start_token(after_tokens[0])
        and _plausible_second_doc(matched_key_tokens, after_tokens[matched_len:])
    ):
        return connector, connector_len, matched_type, matched_key_tokens, matched_len, ""

    # Dò tiếp trong cửa sổ giới hạn để tìm riêng "Luật"/"Bộ luật". Chỉ được
    # phép "nhảy qua" các từ đệm/nối bằng CHỮ thông thường (vd "các", "về",
    # "hướng", "dẫn"...). Nếu gặp token số hoặc mã cơ quan (vd "15", "2020",
    # "ND", "CP"...) thì dừng ngay - đó là dấu hiệu đang ở giữa SỐ HIỆU RIÊNG
    # của chính VB1 (vd "Nghị định 15/2020/NĐ-CP"), không phải phần đệm dẫn
    # tới một Luật khác, nên không được nhảy qua.
    limit = min(_LUAT_LOOKAHEAD_WINDOW, len(after_lower))
    for skip in range(0, limit):
        m_type, m_key, m_len = _match_doc_type(after_lower[skip:])
        if m_type is not None and _is_doc_type_start_token(after_tokens[skip]):
            # Chấp nhận làm VB2 nếu: (a) là loại "trích dẫn bằng tên" đủ đặc
            # trưng (Luật/Bộ luật/Pháp lệnh - không cần bằng chứng số hiệu),
            # HOẶC (b) có bằng chứng số hiệu/năm đi kèm ngay sau (giống điều
            # kiện _plausible_second_doc ở vị trí đầu) - vd "...-Nghi-dinh-18-
            # 2021-ND-CP-..." có "18" (số) ngay sau "Nghị định" là bằng chứng
            # rõ ràng, dù đứng sau nhiều từ đệm mô tả.
            if m_key in _WINDOW_LOOKAHEAD_KEYS or _plausible_second_doc(m_key, after_tokens[skip + m_len:]):
                filler = " ".join(after_tokens[:skip]).lower()
                return connector, connector_len + skip, m_type, m_key, m_len, filler
        tok = after_tokens[skip]
        if tok.isdigit() or _is_agency_code_token(tok):
            break

    return None


def _contains_doc_type_key(tokens: list, keys: set) -> bool:
    """Kiểm tra xem trong tokens có xuất hiện (ở BẤT KỲ vị trí nào, không
    chỉ đầu) một loại văn bản có key nằm trong `keys` hay không. Chỉ tính
    các vị trí mà token bắt đầu bằng chữ hoa (xem _is_doc_type_start_token)
    - bỏ qua các trường hợp trùng tên tình cờ viết thường (vd "luat" trong
    "phap-luat")."""
    lower_tokens = [t.lower() for t in tokens]
    for i in range(len(tokens)):
        if not _is_doc_type_start_token(tokens[i]):
            continue
        _mt, m_key, _ml = _match_doc_type(lower_tokens[i:])
        if m_key in keys:
            return True
    return False


def _strip_trailing_connector_and_year(tokens: list) -> list:
    """Bỏ phần đuôi 'năm chung' (+ từ đệm 'nam' nếu có) và/hoặc cụm nối
    (sửa đổi/bổ sung/...) ở CUỐI danh sách token, vd:
    ["quan","ly","thue","sua","doi","2016"] -> ["quan","ly","thue"]
    Dùng để làm sạch tên luật cuối cùng trong chuỗi nhiều Luật liên tiếp,
    trước khi phần đuôi đó là năm ban hành/hiệu lực của VĂN BẢN SỬA ĐỔI
    chung (không phải năm riêng của luật được liệt kê)."""
    t = list(tokens)
    if t and t[-1].isdigit() and len(t[-1]) == 4:
        t = t[:-1]
        if t and t[-1].lower() == "nam":
            t = t[:-1]
    lower_t = [x.lower() for x in t]
    best_len = 0
    for key_tokens, _phrase in _AMEND_CONNECTOR_RAW.items():
        klen = len(key_tokens)
        if klen <= len(lower_t) and lower_t[-klen:] == list(key_tokens) and klen > best_len:
            best_len = klen
    if best_len:
        t = t[:-best_len]
    return t


_LUAT_KEYS = {("luat",), ("bo", "luat")}

# Các loại văn bản mà tên gọi thường là CHỮ (không có số hiệu/mã cơ quan
# kiểu QH14, TT-BYT...) nên được xử lý theo kiểu "lấy tên bằng chữ + năm
# ban hành" giống Luật, thay vì cố tìm số hiệu/cơ quan. "Hiệp định" dùng
# chung logic này (vd "Hiep-dinh-Thuong-mai-...-2000" -> "Hiệp định Thuong
# mai ... năm 2000"). "Pháp lệnh" cũng thường được trích dẫn bằng TÊN (vd
# "...-huong-dan-Phap-lenh-Uu-dai-nguoi-co-cong-voi-cach-mang-...") nên
# dùng chung logic này.
_TITLE_TYPE_KEYS = _LUAT_KEYS | {("hiep", "dinh"), ("phap", "lenh")}

# Các loại văn bản đủ ĐẶC TRƯNG (hiếm khi trùng tình cờ với văn tiếng Việt
# thông thường) để được chấp nhận làm "văn bản thứ 2" khi dò tìm trong cửa
# sổ giới hạn của _match_next_doc_type(), kể cả khi KHÔNG có số hiệu/năm đi
# kèm ngay sau (chỉ có tên bằng chữ). Ngoài Luật/Bộ luật, "Pháp lệnh" cũng
# đủ đặc trưng để đưa vào đây.
_WINDOW_LOOKAHEAD_KEYS = _LUAT_KEYS | {("phap", "lenh")}


def _split_multi_luat_titles(rest_tokens: list) -> list:
    """Tách nhiều tên luật (đặt tên bằng chữ, KHÔNG có số hiệu riêng) đứng
    liền nhau, phân cách bởi các lần lặp lại từ khóa 'Luật'/'Bộ luật', vd:
      "thue-gia-tri-gia-tang-Luat-thue-tieu-thu-dac-biet-Luat-quan-ly-thue-sua-doi-2016"
        -> ["Luật Thue gia tri gia tang", "Luật Thue tieu thu dac biet", "Luật Quan ly thue"]
    (rest_tokens là phần token đứng SAU loại VB 'Luật' đầu tiên đã match).
    Năm chung ở cuối (nếu có, vd '...-sua-doi-2016') là năm của văn bản SỬA
    ĐỔI chung, không phải năm ban hành riêng từng luật, nên bị bỏ qua, không
    gắn vào tên luật nào."""
    lower_rest = [t.lower() for t in rest_tokens]
    titles: list = []
    current: list = []
    i = 0
    n = len(rest_tokens)
    while i < n:
        _mt, m_key, m_len = _match_doc_type(lower_rest[i:])
        if m_key in _LUAT_KEYS and current and _is_doc_type_start_token(rest_tokens[i]):
            title = " ".join(current)
            title = title[0].upper() + title[1:]
            titles.append(f"Luật {title}")
            current = []
            i += m_len
            continue
        current.append(rest_tokens[i])
        i += 1

    current = _strip_trailing_connector_and_year(current)
    if current:
        title = " ".join(current)
        title = title[0].upper() + title[1:]
        titles.append(f"Luật {title}")

    return titles


def _label_from_name_core(name: str) -> list:
    """Suy ra 'label' (số hiệu văn bản, có dấu) từ trường 'name' (không dấu, nối bằng '-').

    Vd:
      Quyet-dinh-36-2012-QD-TTg-...-147304
        -> "Quyết định 36/2012/QĐ-TTg"
      Cong-van-45-TANDTC-PC-2020-...-438602
        -> "Công văn 45/TANDTC-PC năm 2020"
      TCVN-ISO-IEC-17020-2012-...-914763
        -> "Tiêu chuẩn quốc gia TCVN 17020:2012"
      Thong-tu-14-2019-TT-BYT-sua-doi-Thong-tu-37-2018-TT-BYT-...
        -> ["Thông tư 14/2019/TT-BYT", "Thông tư 37/2018/TT-BYT"]

    Trả về list các label (số hiệu văn bản, có dấu). Thông thường chỉ có 1
    phần tử; nếu tên văn bản chứa nhiều loại văn bản khác nhau nối bằng cụm
    "sửa đổi"/"bổ sung"/... (và cả 2 văn bản đều có đầy đủ số hiệu/năm/cơ
    quan riêng), trả về list gồm nhiều label. Trả về list rỗng nếu không suy
    luận được gì.
    """
    if not name:
        return []

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
            return []

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
            elif code_key == "qcvn" and _is_agency_code_token(cand):
                # Chỉ QCVN mới có phần "/cơ quan ban hành" (vd "/BYT"). TCVN
                # không có kiểu hậu tố này; nếu có token dạng mã ở đây, đó
                # thường là phần LẶP LẠI tham chiếu tới tiêu chuẩn quốc tế
                # tương đương (vd "TCVN-ISO-19011-2018-ISO-19011-2018-...")
                # -> bỏ qua, không coi là cơ quan ban hành.
                agency = _fix_agency_token(cand)

        result = f"{prefix} {code} {number}"
        if year:
            result += f":{year}"
        if codex_ref:
            result += f" ({codex_ref})"
        elif agency:
            result += f"/{agency}"
        return [result]

    # --- match loại văn bản (ưu tiên chuỗi token dài nhất khớp) ---
    matched_type, matched_key_tokens, matched_len = _match_doc_type(lower_tokens)
    if matched_type is None:
        return []

    rest_tokens = tokens[matched_len:]
    rest_lower = lower_tokens[matched_len:]

    # --- Nhiều "Luật"/"Bộ luật" đặt tên bằng chữ đứng liền nhau (không có số
    # hiệu riêng từng luật), vd văn bản sửa đổi gộp nhiều luật cùng lúc:
    # "Luat-thue-gia-tri-gia-tang-Luat-thue-tieu-thu-dac-biet-Luat-quan-ly-thue-sua-doi-2016-..."
    #   -> ["Luật Thue gia tri gia tang", "Luật Thue tieu thu dac biet", "Luật Quan ly thue"]
    # Chỉ coi là "liệt kê nhiều Luật liên tiếp" khi KHÔNG có từ nối (sửa đổi/
    # bổ sung/...) đứng ngay sau VB1 - vd "Luat-A-Luat-B-Luat-C-sua-doi-2016"
    # (từ nối chỉ xuất hiện ở CUỐI, trước năm chung). Nếu có từ nối NGAY SAU
    # VB1 (vd "Luat-sua-doi-cac-Luat-ve-thue-2014"), đây là VB1 KHÔNG có số
    # hiệu riêng đang TRÍCH DẪN tới 1 Luật khác, không phải liệt kê nhiều
    # Luật -> để rơi xuống nhánh "next_doc" bên dưới xử lý (chỉ lấy nhãn của
    # Luật được trích dẫn, bỏ phần "sửa đổi các" không cần thiết cho search).
    connector_probe, _connector_probe_len = _match_connector(rest_lower)
    if not connector_probe and matched_key_tokens in _LUAT_KEYS and _contains_doc_type_key(rest_tokens, _LUAT_KEYS):
        multi_titles = _split_multi_luat_titles(rest_tokens)
        if len(multi_titles) > 1:
            return multi_titles
        # không tách được rõ ràng -> rơi xuống xử lý bình thường bên dưới

    labels: list = []

    # --- VB1 không có số hiệu riêng, mà "loại VB1 [connector] loại VB2 +
    # số hiệu" đứng liền ngay sau (connector là TUỲ CHỌN), vd:
    # "Thong-tu-sua-doi-Thong-tu-02-2021-TT-BNV-..." (có connector)
    # "Van-ban-hop-nhat-Luat-Ke-toan-..." (không có connector) - trường hợp
    # hiếm, nhưng vẫn xử lý nhất quán, không phụ thuộc từ khóa nối.
    # VB1 KHÔNG có số hiệu riêng, nên tự nó không có giá trị tra cứu/tìm
    # kiếm độc lập - chỉ dùng để dò ra VB2 (văn bản THỰC SỰ được trích dẫn/
    # tham chiếu) rồi trả về ĐÚNG nhãn của VB2 đó, bỏ hẳn phần "VB1 [nối]"
    # phía trước (vd "Thông tư hướng dẫn" hay "Luật sửa đổi các" không cần
    # thiết cho mục đích tìm kiếm). Vd:
    #   "Thong-tu-huong-dan-Luat-phong-chong-rua-tien-..." -> "Luật Phong chong rua tien"
    #   "Luat-sua-doi-cac-Luat-ve-thue-2014-..." -> "Luật Ve thue năm 2014"
    next_doc = _match_next_doc_type(rest_lower, rest_tokens)
    if next_doc is not None:
        _connector, prefix_len, matched_type2, matched_key_tokens2, matched_len2, _filler = next_doc
        remainder_tokens = rest_tokens[prefix_len + matched_len2:]

        # Nếu VB2 tìm được là "Luật"/"Bộ luật", có thể VB1 đang sửa đổi/dẫn
        # chiếu tới NHIỀU Luật cùng lúc, mỗi Luật đặt tên bằng chữ và phân
        # cách bởi các lần lặp lại từ khoá "Luật" (không có số hiệu riêng),
        # vd "Luat-sua-doi-Luat-Dau-tu-cong-Luat-Dau-tu-theo-...":
        #   -> ["Luật Dau tu cong", "Luật Dau tu theo phuong thuc doi tac cong tu"]
        # Thử tách trước; nếu không tách được (chỉ có đúng 1 Luật) thì mới
        # rơi xuống xử lý như 1 VB2 duy nhất bên dưới.
        if matched_key_tokens2 in _LUAT_KEYS:
            multi_titles = _split_multi_luat_titles(remainder_tokens)
            if len(multi_titles) > 1:
                return multi_titles

        tail, _ = _parse_number_year_agency(matched_type2, matched_key_tokens2, remainder_tokens)
        if tail:
            return [tail]
        return [matched_type2]

    # --- VB1 có đầy đủ số hiệu/năm/cơ quan riêng. Sau đó lặp lại: nếu phần
    # còn lại (có connector hay không) khớp tiếp một loại VB khác (cũng có
    # đầy đủ số hiệu riêng), gom tiếp vào danh sách label - không phụ thuộc
    # từ khóa "sửa đổi/bổ sung/bãi bỏ/...", chỉ cần nhận diện được loại VB
    # tiếp theo là đủ. Vd:
    # "Thong-tu-14-2019-TT-BYT-sua-doi-Thong-tu-37-2018-TT-BYT-..."
    #   -> ["Thông tư 14/2019/TT-BYT", "Thông tư 37/2018/TT-BYT"]
    cur_type, cur_key_tokens = matched_type, matched_key_tokens
    cur_rest_tokens, cur_rest_lower = rest_tokens, rest_lower

    while True:
        label, consumed = _parse_number_year_agency(cur_type, cur_key_tokens, cur_rest_tokens)
        if not label:
            break
        labels.append(label)

        remainder_tokens = cur_rest_tokens[consumed:]
        remainder_lower = cur_rest_lower[consumed:]
        next_doc2 = _match_next_doc_type(remainder_lower, remainder_tokens)
        if next_doc2 is None:
            break
        _connector2, prefix_len2, matched_type2, matched_key_tokens2, matched_len2, _filler2 = next_doc2
        cur_type, cur_key_tokens = matched_type2, matched_key_tokens2
        cur_rest_tokens = remainder_tokens[prefix_len2 + matched_len2:]
        cur_rest_lower = remainder_lower[prefix_len2 + matched_len2:]

    return labels


# Tiền tố "Dự thảo" (bản dự thảo, chưa ban hành chính thức), vd:
# "Du-thao-Nghi-dinh-quy-dinh-ve-bao-ve-du-lieu-ca-nhan-465185"
# "Du-thao-Luat-Phong-chong-bao-luc-gia-dinh-sua-doi-490095"
# Tiền tố này không phải một phần của loại văn bản (Nghị định/Luật/...),
# nên tách riêng ra trước, xử lý phần còn lại như bình thường, rồi gắn lại
# "Dự thảo " vào đầu mỗi label suy ra được.
_RE_DU_THAO_PREFIX = re.compile(r"^du-thao-", re.IGNORECASE)


def label_from_name(name: str) -> list:
    """Suy ra 'label' từ 'name'. Là wrapper của _label_from_name_core(), có
    thêm xử lý riêng cho tiền tố "Dự thảo" (xem _RE_DU_THAO_PREFIX)."""
    if not name:
        return []

    draft_prefix = ""
    m = _RE_DU_THAO_PREFIX.match(name)
    if m:
        draft_prefix = "Dự thảo "
        name = name[m.end():]

    labels = _label_from_name_core(name)
    if draft_prefix:
        labels = [draft_prefix + lbl for lbl in labels]
    return labels


def _parse_number_year_agency(matched_type: str, matched_key_tokens, rest: list) -> tuple:
    """Suy ra phần 'số hiệu/năm/cơ quan' còn lại sau khi đã xác định loại văn bản
    (matched_type). Trả về tuple (label, consumed):
      - label: chuỗi đầy đủ bắt đầu bằng matched_type, hoặc "" nếu không suy
        luận được gì.
      - consumed: số token đầu tiên của `rest` đã được dùng để tạo ra label
        đó (dùng để biết phần còn lại của `rest` bắt đầu từ đâu, vd để tìm
        tiếp connector + loại văn bản thứ hai đứng ngay sau)."""
    # Bỏ từ đệm "so" (số) nếu đứng ngay sau loại VB, vd "Huong-dan-so-65-..."
    skip = 0
    if rest and rest[0].lower() == "so":
        rest = rest[1:]
        skip = 1

    # --- Riêng "Luật"/"Bộ luật": KHÔNG lấy số hiệu văn bản (vd "08/2017/QH14"),
    # mà lấy TÊN LUẬT bằng chữ đứng sau, vd:
    # "Luat-08-2017-QH14-Thuy-loi-2017-322933" -> "Luật Thuy loi năm 2017"
    # (bỏ qua phần số hiệu/năm/mã cơ quan ở đầu, lấy các từ chữ theo sau làm
    # tên luật, và năm ban hành 4 chữ số theo sau tên luật đó).
    if matched_key_tokens in _TITLE_TYPE_KEYS:
        idx = 0
        while idx < len(rest) and (rest[idx].isdigit() or _is_agency_code_token(rest[idx])):
            idx += 1
        title_tokens: list = []
        year = None
        j = idx
        while j < len(rest):
            if rest[j].isdigit() and len(rest[j]) == 4:
                year = rest[j]
                j += 1
                break
            # từ "nam" (năm) đứng ngay trước năm 4 chữ số chỉ là từ đệm báo
            # hiệu năm ban hành, không phải một phần tên luật -> bỏ qua.
            if (
                rest[j].lower() == "nam"
                and j + 1 < len(rest)
                and rest[j + 1].isdigit()
                and len(rest[j + 1]) == 4
            ):
                j += 1
                continue
            title_tokens.append(rest[j])
            j += 1
        title = " ".join(title_tokens)
        if title:
            title = title[0].upper() + title[1:]

        # Trường hợp đặc biệt: năm đứng ngay sau một từ viết tắt VIẾT HOA
        # TOÀN BỘ (vd "...-GATT-1994-..."). Ở đây năm là 1 PHẦN của tên
        # chính thức (vd "Hiệp định ... GATT 1994"), không phải năm ban
        # hành riêng của văn bản đang xét -> không chèn thêm chữ "năm".
        attach_year_directly = bool(
            title_tokens
            and title_tokens[-1].isalpha()
            and title_tokens[-1].isupper()
            and len(title_tokens[-1]) >= 2
        )

        if title and year:
            if attach_year_directly:
                return f"{matched_type} {title} {year}".strip(), skip + j
            return f"{matched_type} {title} năm {year}".strip(), skip + j
        if title:
            return f"{matched_type} {title}".strip(), skip + j
        if year:
            return f"{matched_type} năm {year}".strip(), skip + j
        return matched_type, skip + j

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
            return f"{matched_type} {title} {year}".strip(), skip + year_idx + 1
        # Không có số hiệu và cũng không có năm 4 chữ số nào trong phần còn lại
        # -> vẫn trả về loại VB + toàn bộ phần tiêu đề bằng chữ, thay vì bỏ trắng.
        # vd "Nghi-dinh-quy-dinh-xu-phat-...-an-ninh-mang"
        #   -> "Nghị định quy dinh xu phat vi pham hanh chinh trong linh vuc an ninh mang"
        title = " ".join(rest)
        if title:
            title = title[0].upper() + title[1:]
            return f"{matched_type} {title}".strip(), skip + len(rest)
        return matched_type, skip + len(rest)
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
        consumed = skip + 1 + 1 + len(agency_tokens)  # number + year + agency
        if agency_tokens:
            return f"{matched_type} {number}/{year}/{'-'.join(agency_tokens)}", consumed
        return f"{matched_type} {number}/{year}", consumed

    if year_idx is not None:
        # dạng ngoại lệ (vd Công văn): Number-AgencyCode...-Year-mô tả
        pre_year_tokens = rest2[:year_idx]
        year = rest2[year_idx]
        consumed = skip + 1 + year_idx + 1  # number + pre_year_tokens + year

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
                return f"{matched_type} {number}/{first_code}-{'-'.join(agency_tokens)} năm {year}", consumed
            return f"{matched_type} {number}/{first_code} năm {year}", consumed

        agency_tokens = [
            _fix_agency_token(t)
            for t in pre_year_tokens
            if _is_agency_code_token(t)
        ]
        if agency_tokens:
            return f"{matched_type} {number}/{'-'.join(agency_tokens)} năm {year}", consumed
        return f"{matched_type} {number} năm {year}", consumed

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
    consumed = skip + 1 + len(agency_tokens)  # number + agency
    if agency_tokens:
        return f"{matched_type} {number}/{'-'.join(agency_tokens)}", consumed
    return f"{matched_type} {number}", consumed


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
    Không ghi đè nếu 'name' đã tồn tại và có giá trị.

    'label' được suy ra bởi label_from_name() dưới dạng list[str]. Nếu tên
    văn bản chỉ ứng với 1 label, giữ 'label' là string (như trước đây) để
    không phá vỡ tương thích ngược; nếu có nhiều label (tên chứa nhiều loại
    văn bản, vd "... sửa đổi ..."), 'label' sẽ là 1 list các string."""
    if not rec.get("name"):
        rec["name"] = name_from_link(rec.get("link", ""))
    if not rec.get("label"):
        labels = label_from_name(rec.get("name", ""))
        if len(labels) > 1:
            rec["label"] = labels
        else:
            rec["label"] = labels[0] if labels else ""
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