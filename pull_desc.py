import json
import logging
import os
import tempfile
from pathlib import Path

from jobbot import storage
from jobbot.common import STATE_DB_FILE

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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
    return storage.load_latest_job_batch(STATE_DB_FILE)


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
    json_path = Path(JSON_FILE)

    if latest_ts and latest_ts != json_ts:
        atomic_write_json(latest_csv_batch)
        logger.info(f"Desc: Staged batch {latest_ts} ({len(latest_csv_batch)} jobs)")
    elif not latest_ts and not json_path.exists():
        atomic_write_json([])
        logger.info("Desc: Created empty desc.json because no matched jobs exist yet.")
    else:
        logger.info("Desc: No new run detected or timestamp matches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
