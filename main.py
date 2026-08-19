from glob import glob
from pathlib import Path

from md_to_json import build_segments_json
from preprocess import process_json

if __name__ == "__main__":
    Path("/mnt/mmlab2024nas/trantran/processed-contexts").mkdir(parents=True, exist_ok=True)

    for file_name in glob("/mnt/mmlab2024nas/trantran/selected-contexts/*"):
        input_file = Path(file_name)

        print(f"Đang xử lý: {input_file.name}")

        process_json(
            file_name,
            "/mnt/mmlab2024nas/trantran/processed-contexts/processed.md",
        )

        build_segments_json(
            file_name,
            "/mnt/mmlab2024nas/trantran/processed-contexts/processed.md",
            f"/mnt/mmlab2024nas/trantran/processed-contexts/{input_file.name}",
        )