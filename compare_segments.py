"""
So sánh output giữa 2 thư mục processed-contexts (vd: bản cũ vs bản mới sau khi
sửa preprocess.py).

Với mỗi file JSON (ghép theo tên file, 1:1), script sẽ:
  - Đếm số lượng segment theo từng segment_type (structured, unstructured_whole,
    root_preamble, ...) trong từng record và tổng theo cả file.
  - So sánh số lượng đó giữa 2 thư mục, in ra phần chênh lệch.
  - Tổng hợp thống kê chung cho toàn bộ dataset (tất cả các file).
  - Xuất báo cáo chi tiết ra CSV (tuỳ chọn --csv).

Cách dùng:
    python compare_segments.py DIR_A DIR_B
    python compare_segments.py /path/processed-contexts /path/processed-contexts-2 --csv report.csv

Mặc định (không truyền tham số) sẽ dùng:
    processed-contexts  vs  processed-contexts-2
(nằm cùng cấp với script, hoặc sửa DEFAULT_DIR_A / DEFAULT_DIR_B bên dưới).
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

DEFAULT_DIR_A = "processed-contexts"
DEFAULT_DIR_B = "processed-contexts-2"

# Các segment_type đã biết (chỉ dùng để giữ thứ tự in cho đẹp, script vẫn
# tự động nhận diện type lạ nếu có).
KNOWN_TYPES = ["structured", "root_preamble", "unstructured_whole"]


def load_json_records(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ❌ Lỗi đọc {path.name}: {e}", file=sys.stderr)
        return []
    return data if isinstance(data, list) else [data]


def record_key(rec: dict, idx: int) -> str:
    """Khoá để ghép record giữa 2 phiên bản: ưu tiên id/link/name, fallback index."""
    for k in ("id", "link", "name"):
        v = rec.get(k)
        if v:
            return str(v)
    return f"__idx_{idx}"


def segment_key(seg: dict, order: int) -> str:
    """Khoá để ghép segment trong cùng 1 record: ưu tiên path, fallback theo
    thứ tự xuất hiện (vì path có thể trùng/rỗng, đặc biệt root_preamble path='')."""
    path = seg.get("path", "")
    if path:
        return path
    return f"__order_{order}"


def find_type_changes(recs_a: list[dict], recs_b: list[dict]) -> list[dict]:
    """So khớp record theo record_key, so khớp segment theo segment_key (path),
    trả về danh sách các segment bị đổi segment_type giữa A và B."""
    map_a = {record_key(r, i): r for i, r in enumerate(recs_a)}
    map_b = {record_key(r, i): r for i, r in enumerate(recs_b)}

    changes = []
    for key in map_a.keys() & map_b.keys():
        rec_a, rec_b = map_a[key], map_b[key]
        segs_a = rec_a.get("passage_segments", []) or []
        segs_b = rec_b.get("passage_segments", []) or []

        dict_a = {segment_key(s, i): s for i, s in enumerate(segs_a)}
        dict_b = {segment_key(s, i): s for i, s in enumerate(segs_b)}

        for skey in dict_a.keys() & dict_b.keys():
            ta = dict_a[skey].get("segment_type")
            tb = dict_b[skey].get("segment_type")
            if ta != tb:
                changes.append({
                    "record_key": key,
                    "path": dict_a[skey].get("path", ""),
                    "type_A": ta,
                    "type_B": tb,
                })
    return changes


def count_segment_types(records: list[dict]) -> Counter:
    """Đếm segment_type trên toàn bộ passage_segments của 1 file."""
    c = Counter()
    for rec in records:
        segs = rec.get("passage_segments", [])
        if not isinstance(segs, list):
            continue
        for seg in segs:
            c[seg.get("segment_type", "<missing>")] += 1
    return c


def ordered_types(*counters: Counter) -> list[str]:
    types = set()
    for c in counters:
        types.update(c.keys())
    # known types trước theo thứ tự cố định, type lạ xếp sau (alphabet)
    known = [t for t in KNOWN_TYPES if t in types]
    unknown = sorted(t for t in types if t not in KNOWN_TYPES)
    return known + unknown


def fmt_row(label: str, cols: list[str], widths: list[int]) -> str:
    parts = [label.ljust(widths[0])]
    for col, w in zip(cols, widths[1:]):
        parts.append(str(col).rjust(w))
    return "  ".join(parts)


def compare(dir_a: Path, dir_b: Path, csv_path: str | None):
    files_a = {p.name: p for p in dir_a.glob("*.json")} if dir_a.exists() else {}
    files_b = {p.name: p for p in dir_b.glob("*.json")} if dir_b.exists() else {}
    # Nếu output không có đuôi .json (theo main.py là copy tên input_file.name,
    # có thể không có .json), fallback lấy tất cả file (trừ processed.md).
    if not files_a:
        files_a = {p.name: p for p in dir_a.glob("*") if p.is_file() and p.name != "processed.md"}
    if not files_b:
        files_b = {p.name: p for p in dir_b.glob("*") if p.is_file() and p.name != "processed.md"}

    all_names = sorted(set(files_a) | set(files_b))
    only_a = sorted(set(files_a) - set(files_b))
    only_b = sorted(set(files_b) - set(files_a))
    common = sorted(set(files_a) & set(files_b))

    if only_a:
        print(f"⚠️  {len(only_a)} file chỉ có ở {dir_a}: {only_a}")
    if only_b:
        print(f"⚠️  {len(only_b)} file chỉ có ở {dir_b}: {only_b}")
    if not common:
        print("Không có file trùng tên để so sánh.")
        return

    total_a, total_b = Counter(), Counter()
    csv_rows = []
    type_change_rows = []  # danh sách segment bị đổi loại (structured <-> unstructured...)
    diff_file_count = 0
    files_with_type_change = 0

    print(f"\nSo sánh {len(common)} file trùng tên giữa:\n  A = {dir_a}\n  B = {dir_b}\n")

    for name in common:
        recs_a = load_json_records(files_a[name])
        recs_b = load_json_records(files_b[name])

        cnt_a = count_segment_types(recs_a)
        cnt_b = count_segment_types(recs_b)
        total_a += cnt_a
        total_b += cnt_b

        types = ordered_types(cnt_a, cnt_b)
        row_diff = {t: cnt_b.get(t, 0) - cnt_a.get(t, 0) for t in types}
        has_diff = any(row_diff.values()) or len(recs_a) != len(recs_b)

        for t in types:
            csv_rows.append({
                "file": name,
                "segment_type": t,
                "count_A": cnt_a.get(t, 0),
                "count_B": cnt_b.get(t, 0),
                "diff_B_minus_A": row_diff[t],
                "records_A": len(recs_a),
                "records_B": len(recs_b),
            })

        # Phát hiện segment bị đổi loại (so khớp theo record_key + path)
        changes = find_type_changes(recs_a, recs_b)
        if changes:
            files_with_type_change += 1
            has_diff = True

        if has_diff:
            diff_file_count += 1
            print(f"📄 {name}  (records: A={len(recs_a)} B={len(recs_b)})")
            widths = [18, 8, 8, 8]
            print("  " + fmt_row("segment_type", ["A", "B", "diff"], widths))
            for t in types:
                d = row_diff[t]
                mark = "" if d == 0 else (" ▲" if d > 0 else " ▼")
                print("  " + fmt_row(t, [cnt_a.get(t, 0), cnt_b.get(t, 0), f"{d:+d}{mark}"], widths))

            if changes:
                print(f"  🔀 {len(changes)} segment bị đổi loại:")
                for ch in changes:
                    path_display = ch["path"] if ch["path"] else "(root_preamble / không path)"
                    print(f"      - [{ch['record_key']}] {path_display}")
                    print(f"          {ch['type_A']}  →  {ch['type_B']}")
                    type_change_rows.append({
                        "file": name,
                        "record_key": ch["record_key"],
                        "path": ch["path"],
                        "type_A": ch["type_A"],
                        "type_B": ch["type_B"],
                    })
            print()

    if diff_file_count == 0:
        print("✅ Không có chênh lệch segment_type nào giữa các file trùng tên.\n")
    else:
        print(f"➡️  {diff_file_count}/{len(common)} file có chênh lệch.\n")

    total_type_changes = len(type_change_rows)
    if total_type_changes == 0:
        print("✅ Không có segment nào bị đổi loại (structured/unstructured/root_preamble) giữa 2 phiên bản.\n")
    else:
        change_pair_counter = Counter((r["type_A"], r["type_B"]) for r in type_change_rows)
        print(f"🔀 Tổng cộng {total_type_changes} segment bị đổi loại, trong {files_with_type_change}/{len(common)} file.")
        print("   Chi tiết theo kiểu chuyển đổi:")
        for (ta, tb), n in change_pair_counter.most_common():
            print(f"     {ta} → {tb}: {n}")
        print()

    # Tổng hợp toàn dataset
    types = ordered_types(total_a, total_b)
    widths = [18, 10, 10, 10]
    print("=== TỔNG HỢP TOÀN DATASET ===")
    print(fmt_row("segment_type", ["A (tổng)", "B (tổng)", "diff"], widths))
    for t in types:
        d = total_b.get(t, 0) - total_a.get(t, 0)
        mark = "" if d == 0 else (" ▲" if d > 0 else " ▼")
        print(fmt_row(t, [total_a.get(t, 0), total_b.get(t, 0), f"{d:+d}{mark}"], widths))
    print(fmt_row("TOTAL segments", [sum(total_a.values()), sum(total_b.values()),
                                      f"{sum(total_b.values()) - sum(total_a.values()):+d}"], widths))

    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "file", "segment_type", "count_A", "count_B", "diff_B_minus_A",
                "records_A", "records_B",
            ])
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"\n📝 Đã ghi báo cáo tổng hợp số lượng ra: {csv_path}")

        # File CSV thứ 2: liệt kê từng segment bị đổi loại cụ thể
        changes_csv_path = str(Path(csv_path).with_name(Path(csv_path).stem + "_type_changes.csv"))
        with open(changes_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["file", "record_key", "path", "type_A", "type_B"])
            writer.writeheader()
            writer.writerows(type_change_rows)
        print(f"📝 Đã ghi danh sách segment bị đổi loại ra: {changes_csv_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir_a", nargs="?", default=DEFAULT_DIR_A, help="Thư mục output phiên bản A (vd: processed-contexts)")
    ap.add_argument("dir_b", nargs="?", default=DEFAULT_DIR_B, help="Thư mục output phiên bản B (vd: processed-contexts-2)")
    ap.add_argument("--csv", default=None, help="Đường dẫn file CSV để xuất báo cáo chi tiết theo từng file")
    args = ap.parse_args()

    dir_a, dir_b = Path(args.dir_a), Path(args.dir_b)
    if not dir_a.exists():
        print(f"❌ Không tìm thấy thư mục A: {dir_a}", file=sys.stderr)
    if not dir_b.exists():
        print(f"❌ Không tìm thấy thư mục B: {dir_b}", file=sys.stderr)
    if not dir_a.exists() or not dir_b.exists():
        sys.exit(1)

    compare(dir_a, dir_b, args.csv)


if __name__ == "__main__":
    main()
