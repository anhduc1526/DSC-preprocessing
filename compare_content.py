"""
So sánh NỘI DUNG từng segment giữa 2 thư mục output (bổ sung cho compare_segments.py,
vốn chỉ đếm số lượng và so segment_type).

Với mỗi file JSON trùng tên:
  - Ghép record theo id/link/name (giống compare_segments.py).
  - Ghép segment trong record:
      * nếu số segment 2 bên bằng nhau -> ghép theo THỨ TỰ (index), nên vẫn bắt được
        trường hợp 'path' bị đổi (vd: heading chương được gộp thêm tiêu đề);
      * nếu khác nhau -> ghép theo 'path' (mỗi path xuất hiện nhiều lần thì ghép theo
        lần xuất hiện), phần không ghép được báo là only_in_A / only_in_B.
  - So sánh TẤT CẢ các trường của segment (không cần biết tên trường nội dung),
    báo trường nào khác nhau, kèm diff ngắn cho một số ví dụ đầu.
  - So sánh cả các trường cấp record (name, label, ...) trừ passage_segments.

Cách dùng:
    python compare_content.py /mnt/mmlab2024nas/trantran/processed-contexts-2 /mnt/mmlab2024nas/trantran/processed-contexts-4
    python compare_content.py /mnt/mmlab2024nas/trantran/processed-contexts-2 /mnt/mmlab2024nas/trantran/processed-contexts-4 --csv content_diff.csv --examples 20
    python compare_content.py /mnt/mmlab2024nas/trantran/processed-contexts-2 /mnt/mmlab2024nas/trantran/processed-contexts-4 --ignore-ws          # bỏ qua khác biệt khoảng trắng
    python compare_content.py /mnt/mmlab2024nas/trantran/processed-contexts-2 /mnt/mmlab2024nas/trantran/processed-contexts-4 --ignore-fields label name    # bỏ qua một số trường
"""

import argparse
import csv
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SEG_FIELD = "passage_segments"


def load_records(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ❌ Lỗi đọc {path.name}: {e}", file=sys.stderr)
        return []
    return data if isinstance(data, list) else [data]


def record_keys(records: list[dict]) -> dict[str, dict]:
    """Khoá record: id/link/name; nếu trùng khoá thì thêm hậu tố #n để không ghi đè."""
    out, seen = {}, Counter()
    for i, rec in enumerate(records):
        base = next((str(rec[k]) for k in ("id", "link", "name") if rec.get(k)), f"__idx_{i}")
        seen[base] += 1
        out[base if seen[base] == 1 else f"{base}#{seen[base]}"] = rec
    return out


def norm(v, ignore_ws: bool):
    if ignore_ws and isinstance(v, str):
        return re.sub(r"\s+", " ", v).strip()
    return v


def diff_fields(a: dict, b: dict, ignore_fields: set, ignore_ws: bool, skip: set = frozenset()) -> list[str]:
    keys = (set(a) | set(b)) - ignore_fields - skip
    return sorted(k for k in keys
                  if norm(a.get(k, "<missing>"), ignore_ws) != norm(b.get(k, "<missing>"), ignore_ws))


def align_segments(segs_a: list, segs_b: list):
    """Trả về (pairs, only_a, only_b); pairs là list (label, seg_a, seg_b)."""
    if len(segs_a) == len(segs_b):
        return [(f"#{i}", x, y) for i, (x, y) in enumerate(zip(segs_a, segs_b))], [], []

    def index_by_path(segs):
        d, seen = {}, Counter()
        for i, s in enumerate(segs):
            p = s.get("path", "") or f"__order_{i}"
            seen[p] += 1
            d[(p, seen[p])] = s
        return d

    da, db = index_by_path(segs_a), index_by_path(segs_b)
    pairs = [(f"path={k[0]!r}", da[k], db[k]) for k in da.keys() & db.keys()]
    only_a = [da[k] for k in da.keys() - db.keys()]
    only_b = [db[k] for k in db.keys() - da.keys()]
    return pairs, only_a, only_b


def short_diff(a, b, width=200) -> str:
    sa, sb = str(a), str(b)
    if len(sa) + len(sb) < 2 * width:
        return f"      A: {sa!r}\n      B: {sb!r}"
    sm = difflib.SequenceMatcher(None, sa, sb, autojunk=False)
    lines = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        ctx = 30
        lines.append(f"      @{i1}: {sa[max(0, i1 - ctx):i1]!r} [A: {sa[i1:i2][:width]!r} -> B: {sb[j1:j2][:width]!r}]")
        if len(lines) >= 3:
            lines.append("      ...")
            break
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir_a")
    ap.add_argument("dir_b")
    ap.add_argument("--csv", help="Xuất mọi segment/record khác nhau ra CSV")
    ap.add_argument("--examples", type=int, default=10, help="Số ví dụ in ra màn hình (mặc định 10)")
    ap.add_argument("--ignore-ws", action="store_true", help="Bỏ qua khác biệt về khoảng trắng/xuống dòng")
    ap.add_argument("--ignore-fields", nargs="*", default=[], help="Các trường bỏ qua khi so sánh")
    args = ap.parse_args()

    dir_a, dir_b = Path(args.dir_a), Path(args.dir_b)
    if not dir_a.is_dir() or not dir_b.is_dir():
        sys.exit("❌ Thư mục A hoặc B không tồn tại")
    ignore = set(args.ignore_fields)

    def list_files(d: Path):
        fs = {p.name: p for p in d.glob("*.json")}
        return fs or {p.name: p for p in d.glob("*") if p.is_file() and p.name != "processed.md"}

    fa, fb = list_files(dir_a), list_files(dir_b)
    common = sorted(set(fa) & set(fb))
    if not common:
        sys.exit("Không có file trùng tên để so sánh.")

    n_seg = n_seg_diff = n_rec = n_rec_diff = n_only_a = n_only_b = n_rec_missing = 0
    files_diff = set()
    field_counter = Counter()
    per_file = defaultdict(int)
    rows, shown = [], 0

    for name in common:
        ra, rb = record_keys(load_records(fa[name])), record_keys(load_records(fb[name]))
        n_rec_missing += len(set(ra) ^ set(rb))
        for key in sorted(set(ra) & set(rb)):
            n_rec += 1
            A, B = ra[key], rb[key]

            rec_fields = diff_fields(A, B, ignore, args.ignore_ws, skip={SEG_FIELD})
            if rec_fields:
                n_rec_diff += 1
                files_diff.add(name)
                per_file[name] += 1
                field_counter.update(f"record.{f}" for f in rec_fields)
                rows.append({"file": name, "record_key": key, "where": "record", "label": "",
                             "fields": ";".join(rec_fields)})

            sa = A.get(SEG_FIELD) or []
            sb = B.get(SEG_FIELD) or []
            pairs, only_a, only_b = align_segments(sa, sb)
            n_seg += len(pairs)
            n_only_a += len(only_a)
            n_only_b += len(only_b)
            if only_a or only_b:
                files_diff.add(name)
                per_file[name] += len(only_a) + len(only_b)
                for s in only_a:
                    rows.append({"file": name, "record_key": key, "where": "only_in_A",
                                 "label": s.get("path", ""), "fields": ""})
                for s in only_b:
                    rows.append({"file": name, "record_key": key, "where": "only_in_B",
                                 "label": s.get("path", ""), "fields": ""})

            for label, x, y in pairs:
                fields = diff_fields(x, y, ignore, args.ignore_ws)
                if not fields:
                    continue
                n_seg_diff += 1
                files_diff.add(name)
                per_file[name] += 1
                field_counter.update(fields)
                rows.append({"file": name, "record_key": key, "where": "segment",
                             "label": label, "fields": ";".join(fields)})
                if shown < args.examples:
                    shown += 1
                    print(f"📄 {name} | record [{key}] | segment {label} | khác ở: {', '.join(fields)}")
                    for f in fields[:3]:
                        print(f"    • {f}:")
                        print(short_diff(x.get(f, "<missing>"), y.get(f, "<missing>")))
                    print()

    print("=== TỔNG HỢP SO SÁNH NỘI DUNG ===")
    print(f"File trùng tên so sánh      : {len(common)}")
    print(f"Record so sánh              : {n_rec}  (record chỉ có 1 bên: {n_rec_missing})")
    print(f"Record khác ở trường cấp record: {n_rec_diff}")
    print(f"Segment ghép được           : {n_seg}")
    print(f"Segment khác nội dung       : {n_seg_diff}")
    print(f"Segment không ghép được     : only_in_A={n_only_a}, only_in_B={n_only_b}")
    print(f"Số file có khác biệt        : {len(files_diff)}/{len(common)}")
    if field_counter:
        print("\nTrường bị khác (số lần):")
        for f, n in field_counter.most_common():
            print(f"  {f:30s} {n}")
        print("\nTop file khác nhiều nhất:")
        for f, n in sorted(per_file.items(), key=lambda kv: -kv[1])[:10]:
            print(f"  {f}: {n}")
    else:
        print("\n✅ Nội dung 2 phiên bản giống hệt nhau (theo các trường đã so sánh).")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["file", "record_key", "where", "label", "fields"])
            w.writeheader()
            w.writerows(rows)
        print(f"\n📝 Đã ghi {len(rows)} dòng khác biệt ra: {args.csv}")


if __name__ == "__main__":
    main()
