from glob import glob
from pathlib import Path

from md_to_json import build_segments_json
from preprocess import process_json

RAW_DIR = Path("data/raw/selected-contexts")
PROCESSED_DIR = Path("data/processed/processed-contexts")

if __name__ == "__main__":
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    for file_name in glob(str(RAW_DIR / "*")):
        input_file = Path(file_name)

        print(f"Đang xử lý: {input_file.name}")

        process_json(
            file_name,
            str(PROCESSED_DIR / "processed.md"),
        )

        build_segments_json(
            file_name,
            str(PROCESSED_DIR / "processed.md"),
            str(PROCESSED_DIR / input_file.name),
        )