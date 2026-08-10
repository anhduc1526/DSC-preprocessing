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


def collect_segments(node: Node, path_stack: list[str], out: list[str]) -> None:
    # path bao gồm cả title của node hiện tại
    current_path = path_stack + [_strip_urls(node.title)]

    content = "\n".join(node.content_lines).strip()
    content = _strip_urls(content)
    content = _normalize_whitespace(content)

    if content:
        path_str = " > ".join(p for p in current_path if p)
        out.append(f"{path_str} | {content}")

    for child in node.children:
        collect_segments(child, current_path, out)


def md_to_segments(block_text: str) -> list[str]:
    root_node = parse_md_tree(block_text)
    if root_node is None:
        return []
    out: list[str] = []
    collect_segments(root_node, [], out)
    return out


def load_records(pattern: str) -> list[dict]:
    records = []
    for path in sorted(glob.glob(pattern)):
        data = json.load(open(path, encoding="utf-8"))
        records.extend(data if isinstance(data, list) else [data])
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
        new_rec["passage_segments"] = md_to_segments(block)
        new_records.append(new_rec)

    json.dump(new_records, open(output_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✅ {len(new_records)}/{len(records)} → {output_path}")


if __name__ == "__main__":
    build_segments_json("law.json", "processed.md", "law_segments.json")