"""Create blind image copies plus metadata.csv and rating_items.csv.

The rating website must not read generation_jobs.csv or raw image paths. This
script is the offline bridge: it reads successful generation jobs, copies each
raw image into images/blind/ with an anonymous filename, writes metadata.csv as
the private decoding table, and writes rating_items.csv for the website.
"""

from __future__ import annotations

import argparse
import csv
import random
import shutil
import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = PROJECT_ROOT / "images" / "raw"
BLIND_DIR = PROJECT_ROOT / "images" / "blind"

JOBS_CSV = DATA_DIR / "generation_jobs.csv"
PROMPTS_CSV = DATA_DIR / "prompts.csv"
METADATA_CSV = DATA_DIR / "metadata.csv"
RATING_ITEMS_CSV = DATA_DIR / "rating_items.csv"

METADATA_FIELDS = [
    "image_id", "blind_filename", "job_id", "prompt_id", "model_id",
    "replicate_idx", "seed",
    "original_prompt", "revised_prompt", "revision_reason",
    "raw_image_path", "blind_image_path",
    "image_width", "image_height", "generated_at",
]

RATING_FIELDS = [
    "image_id", "blind_filename", "target_style", "prompt_level",
    "prompt_text", "expected_elements", "forbidden_elements",
]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"ERROR: missing {path}")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def has_data_rows(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.reader(f)) > 1


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_rows(seed: int) -> tuple[list[dict], list[dict], list[tuple[Path, Path]]]:
    prompts = {r["prompt_id"]: r for r in read_csv(PROMPTS_CSV)}
    jobs = [r for r in read_csv(JOBS_CSV) if r.get("status") == "success"]
    if not jobs:
        sys.exit("ERROR: no successful generation jobs found")

    missing = [r["job_id"] for r in jobs if not r.get("raw_image_path")]
    if missing:
        sys.exit(f"ERROR: successful jobs missing raw_image_path: {missing}")

    jobs.sort(key=lambda r: r["job_id"])
    rng = random.Random(seed)
    rng.shuffle(jobs)

    metadata_rows: list[dict] = []
    rating_rows: list[dict] = []
    copies: list[tuple[Path, Path]] = []

    for idx, job in enumerate(jobs, 1):
        prompt = prompts.get(job["prompt_id"])
        if not prompt:
            sys.exit(f"ERROR: prompt_id not found for {job['job_id']}: {job['prompt_id']}")

        src = (PROJECT_ROOT / job["raw_image_path"]).resolve()
        if not src.is_file():
            sys.exit(f"ERROR: raw image not found for {job['job_id']}: {src}")
        if not src.is_relative_to(PROJECT_ROOT):
            sys.exit(f"ERROR: raw image path escapes project root: {src}")

        image_id = f"img_{idx:04d}"
        blind_filename = f"{image_id}{src.suffix.lower() or '.png'}"
        blind_rel = f"images/blind/{blind_filename}"
        dst = PROJECT_ROOT / blind_rel
        width, height = image_size(src)

        metadata_rows.append({
            "image_id": image_id,
            "blind_filename": blind_filename,
            "job_id": job["job_id"],
            "prompt_id": job["prompt_id"],
            "model_id": job["model_id"],
            "replicate_idx": job["replicate_idx"],
            "seed": job.get("seed", ""),
            "original_prompt": job["original_prompt"],
            "revised_prompt": job.get("revised_prompt", ""),
            "revision_reason": job.get("revision_reason", ""),
            "raw_image_path": job["raw_image_path"],
            "blind_image_path": blind_rel,
            "image_width": str(width),
            "image_height": str(height),
            "generated_at": job.get("finished_at", ""),
        })
        rating_rows.append({
            "image_id": image_id,
            "blind_filename": blind_filename,
            "target_style": prompt["target_style"],
            "prompt_level": prompt["prompt_level"],
            "prompt_text": prompt["prompt_text"],
            "expected_elements": prompt["expected_elements"],
            "forbidden_elements": prompt["forbidden_elements"],
        })
        copies.append((src, dst))

    return metadata_rows, rating_rows, copies


def main() -> int:
    parser = argparse.ArgumentParser(description="Create blind image set for subjective rating")
    parser.add_argument("--execute", action="store_true", help="write files")
    parser.add_argument("--force", action="store_true", help="overwrite existing metadata/rating/blind images")
    parser.add_argument("--seed", type=int, default=20260626, help="shuffle seed for anonymous ordering")
    args = parser.parse_args()

    if not args.force and (has_data_rows(METADATA_CSV) or has_data_rows(RATING_ITEMS_CSV)):
        sys.exit("ERROR: metadata.csv or rating_items.csv already has data rows; use --force to overwrite")

    metadata_rows, rating_rows, copies = build_rows(args.seed)
    print(f"successful images: {len(metadata_rows)}")
    print(f"shuffle seed: {args.seed}")
    print("first 5 mappings:")
    for row in metadata_rows[:5]:
        print(f"  {row['image_id']} <- {row['job_id']} ({row['prompt_id']} {row['model_id']})")

    if not args.execute:
        print("[DRY-RUN] no files written")
        return 0

    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    if args.force:
        for old in BLIND_DIR.iterdir():
            if old.is_file() and old.name != ".gitkeep":
                old.unlink()

    for src, dst in copies:
        shutil.copy2(src, dst)

    write_csv(METADATA_CSV, METADATA_FIELDS, metadata_rows)
    write_csv(RATING_ITEMS_CSV, RATING_FIELDS, rating_rows)
    print(f"[OK] wrote {METADATA_CSV.relative_to(PROJECT_ROOT)}")
    print(f"[OK] wrote {RATING_ITEMS_CSV.relative_to(PROJECT_ROOT)}")
    print(f"[OK] copied {len(copies)} images into {BLIND_DIR.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
