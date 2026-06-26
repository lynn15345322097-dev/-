"""init_jobs.py — 初始化 generation_jobs.csv

读取 prompts.csv 和 models.csv，按 prompt × model × replicate 笛卡尔积
生成待执行任务清单写入 generation_jobs.csv。

MVP 规模：8 prompt × 2 model × 2 replicate = 32 job

初始字段约定：
    seed     = ""        （留空，由 generate_images.py 实际调用时生成）
    status   = pending
    attempts = 0
    所有时间字段、错误字段、图片路径字段留空

用法：
    python scripts/init_jobs.py                       # 写入默认路径
    python scripts/init_jobs.py --replicates 2        # 自定义副本数
    python scripts/init_jobs.py --overwrite           # 覆盖已有 jobs（默认拒绝覆盖非空文件）
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

PROMPTS_CSV = DATA_DIR / "prompts.csv"
MODELS_CSV = DATA_DIR / "models.csv"
JOBS_CSV = DATA_DIR / "generation_jobs.csv"

JOB_FIELDS = [
    "job_id", "prompt_id", "model_id", "replicate_idx", "seed",
    "status", "attempts",
    "original_prompt", "revised_prompt", "revision_reason",
    "raw_image_path", "error_code", "error_message",
    "timeout_sec", "safety_blocked",
    "created_at", "started_at", "finished_at",
]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"ERROR: 找不到文件 {path}")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def has_existing_jobs(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return len(rows) > 0


def build_jobs(prompts: list[dict], models: list[dict], replicates: int) -> list[dict]:
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    jobs: list[dict] = []
    counter = 0
    for prompt in prompts:
        for model in models:
            for rep in range(1, replicates + 1):
                counter += 1
                jobs.append({
                    "job_id": f"J{counter:04d}",
                    "prompt_id": prompt["prompt_id"],
                    "model_id": model["model_id"],
                    "replicate_idx": rep,
                    "seed": "",
                    "status": "pending",
                    "attempts": 0,
                    "original_prompt": prompt["prompt_text"],
                    "revised_prompt": "",
                    "revision_reason": "",
                    "raw_image_path": "",
                    "error_code": "",
                    "error_message": "",
                    "timeout_sec": "",
                    "safety_blocked": "",
                    "created_at": now_iso,
                    "started_at": "",
                    "finished_at": "",
                })
    return jobs


def write_jobs(path: Path, jobs: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=JOB_FIELDS)
        writer.writeheader()
        writer.writerows(jobs)


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 generation_jobs.csv")
    parser.add_argument("--replicates", type=int, default=2,
                        help="每个 (prompt, model) 的副本数 (默认 2)")
    parser.add_argument("--overwrite", action="store_true",
                        help="覆盖已存在的非空 generation_jobs.csv")
    args = parser.parse_args()

    if has_existing_jobs(JOBS_CSV) and not args.overwrite:
        sys.exit(
            f"ERROR: {JOBS_CSV} 已存在且非空。\n"
            "       如需重置，请加 --overwrite 参数（会清空原内容）。"
        )

    prompts = read_csv(PROMPTS_CSV)
    models = read_csv(MODELS_CSV)

    if not prompts:
        sys.exit(f"ERROR: {PROMPTS_CSV} 中无数据")
    if not models:
        sys.exit(f"ERROR: {MODELS_CSV} 中无数据")

    jobs = build_jobs(prompts, models, args.replicates)
    write_jobs(JOBS_CSV, jobs)

    print(f"OK  生成 {len(jobs)} 条 job 写入 {JOBS_CSV}")
    print(f"    {len(prompts)} prompt × {len(models)} model × {args.replicates} replicate = {len(jobs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
