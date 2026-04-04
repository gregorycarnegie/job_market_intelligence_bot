import csv
import json
import os
import tempfile
from pathlib import Path

CSV_FILE = "jobs.csv"
JSON_FILE = "desc.json"
CSV_HEADERS = ["time", "title", "description", "link"]


def atomic_write_json(payload: list[dict[str, str]]) -> None:
    json_path = Path(JSON_FILE)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=json_path.parent or ".",
        delete=False,
    ) as temp_file:
        json.dump(payload, temp_file, indent=4, ensure_ascii=False)
        temp_path = temp_file.name
    os.replace(temp_path, json_path)


def load_latest_csv_batch() -> tuple[str | None, list[dict[str, str]]]:
    csv_path = Path(CSV_FILE)
    if not csv_path.exists():
        return None, []

    latest_ts = None
    latest_csv_batch = []

    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            row_time = row.get("time")
            if not row_time:
                continue

            link_parts = [row.get("link", "")]
            if row.get(None):
                link_parts.extend(row[None])
            link = ",".join(part for part in link_parts if part)

            if latest_ts != row_time:
                latest_ts = row_time
                latest_csv_batch = []

            latest_csv_batch.append(
                {
                    "time": row_time,
                    "title": row.get("title", ""),
                    "description": row.get("description", ""),
                    "link": link,
                }
            )

    return latest_ts, latest_csv_batch


def load_json_timestamp() -> str | None:
    json_path = Path(JSON_FILE)
    if not json_path.exists():
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return None
    if data:
        return data[0].get("time")
    return None


def main() -> int:
    latest_ts, latest_csv_batch = load_latest_csv_batch()
    json_ts = load_json_timestamp()

    if latest_ts and latest_ts != json_ts:
        atomic_write_json(latest_csv_batch)
        print(f"Desc: Staged batch {latest_ts} ({len(latest_csv_batch)} jobs)")
    else:
        print("Desc: No new run detected or timestamp matches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
