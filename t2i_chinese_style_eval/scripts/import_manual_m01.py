"""import_manual_m01.py — 手动导入 M01 图片

用途：
  当 M01 图片不是通过 API 生成，而是从聊天界面下载为本地文件时，
  用这个脚本把图片复制进 images/raw/，并回填 generation_jobs.csv。

典型流程：
  1. 查看待补 M01 任务：
       python3 scripts/import_manual_m01.py --list-pending

  2. 单张 dry-run：
       python3 scripts/import_manual_m01.py --dry-run --job-id J0001 --source /path/to/image.png

  3. 单张真实导入：
       python3 scripts/import_manual_m01.py --execute --job-id J0001 --source /path/to/image.png

  4. 批量 dry-run（manifest 表头：job_id,source_path）：
       python3 scripts/import_manual_m01.py --dry-run --manifest data/manual_m01_import_manifest.csv

安全约定：
  - 只允许导入 model_id=M01 的任务。
  - 默认只允许导入 status=pending 的任务，避免覆盖已经成功的图片。
  - 不修改 prompt，不生成 seed，不写 metadata/rating_items。
  - 导入后 status=success, attempts+1, safety_blocked=false。
  - 不要和 generate_images.py 同时 --execute，因为两者都会写 generation_jobs.csv。
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = PROJECT_ROOT / "images" / "raw"
JOBS_CSV = DATA_DIR / "generation_jobs.csv"

JOB_FIELDS = [
    "job_id", "prompt_id", "model_id", "replicate_idx", "seed",
    "status", "attempts",
    "original_prompt", "revised_prompt", "revision_reason",
    "raw_image_path", "error_code", "error_message",
    "timeout_sec", "safety_blocked",
    "created_at", "started_at", "finished_at",
]

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_jobs() -> list[dict]:
    if not JOBS_CSV.exists():
        sys.exit(f"ERROR: 找不到 {JOBS_CSV}")
    with JOBS_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != JOB_FIELDS:
            sys.exit("ERROR: generation_jobs.csv 表头不符合预期，请先运行 validate_schema.py")
        return list(reader)


def write_jobs(rows: list[dict]) -> None:
    with JOBS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=JOB_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def resolve_source(value: str) -> Path:
    raw = Path(value).expanduser()
    candidates = [raw]
    if not raw.is_absolute():
        candidates.append(PROJECT_ROOT / raw)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[-1].resolve()


def sniff_image(path: Path) -> str:
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"文件扩展名必须是 {sorted(ALLOWED_EXTENSIONS)}，当前是 {ext or '(无扩展名)'}")
    head = path.read_bytes()[:16]
    if ext == ".png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("扩展名是 .png，但文件头不是 PNG")
    if ext in {".jpg", ".jpeg"} and not head.startswith(b"\xff\xd8\xff"):
        raise ValueError("扩展名是 .jpg/.jpeg，但文件头不是 JPEG")
    if ext == ".webp" and not (head.startswith(b"RIFF") and head[8:12] == b"WEBP"):
        raise ValueError("扩展名是 .webp，但文件头不是 WEBP")
    return ext


def load_manifest(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        sys.exit(f"ERROR: 找不到 manifest：{path}")
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        expected = ["job_id", "source_path"]
        if reader.fieldnames != expected:
            sys.exit(f"ERROR: manifest 表头必须是 {expected}")
        return [(r["job_id"].strip(), r["source_path"].strip()) for r in reader]


def select_imports(args: argparse.Namespace) -> list[tuple[str, Path]]:
    if args.manifest:
        pairs = load_manifest(resolve_source(args.manifest))
    else:
        pairs = [(args.job_id.strip(), args.source.strip())]

    imports: list[tuple[str, Path]] = []
    for job_id, source_text in pairs:
        if not job_id:
            sys.exit("ERROR: job_id 不能为空")
        if not source_text:
            sys.exit(f"ERROR: {job_id} 的 source_path 不能为空")
        source = resolve_source(source_text)
        if not source.exists():
            sys.exit(f"ERROR: {job_id} 的源文件不存在：{source}")
        if not source.is_file():
            sys.exit(f"ERROR: {job_id} 的源路径不是文件：{source}")
        try:
            sniff_image(source)
        except ValueError as e:
            sys.exit(f"ERROR: {job_id} 图片文件不合格：{e}")
        imports.append((job_id, source))

    seen: set[str] = set()
    duplicates = sorted({job_id for job_id, _ in imports if job_id in seen or seen.add(job_id)})
    if duplicates:
        sys.exit(f"ERROR: 同一次导入不能重复 job_id：{duplicates}")
    return imports


def list_pending(rows: list[dict]) -> None:
    pending = [r for r in rows if r["model_id"] == "M01" and r["status"] == "pending"]
    if not pending:
        print("没有 M01 pending 任务。")
        return
    print("M01 待手动导入任务：")
    print(f"{'job_id':<8} {'prompt_id':<14} {'rep':<4} prompt")
    print("-" * 78)
    for row in pending:
        prompt = row["original_prompt"]
        if len(prompt) > 46:
            prompt = prompt[:43] + "..."
        print(f"{row['job_id']:<8} {row['prompt_id']:<14} {row['replicate_idx']:<4} {prompt}")


def validate_import(rows: list[dict], job_id: str, source: Path) -> dict:
    matches = [r for r in rows if r["job_id"] == job_id]
    if not matches:
        sys.exit(f"ERROR: 找不到 job_id={job_id}")
    row = matches[0]
    if row["model_id"] != "M01":
        sys.exit(f"ERROR: {job_id} 是 {row['model_id']}，手动导入脚本只处理 M01")
    if row["status"] != "pending":
        sys.exit(f"ERROR: {job_id} 当前状态是 {row['status']}，默认只允许导入 pending 任务")
    if row.get("raw_image_path"):
        sys.exit(f"ERROR: {job_id} 已有 raw_image_path={row['raw_image_path']}，请先人工核对，不自动覆盖")
    if source.resolve().is_relative_to(RAW_DIR.resolve()):
        sys.exit("ERROR: 源文件已经在 images/raw/ 内。请从下载目录或临时导入目录导入，避免源/目标混淆")
    return row


def import_one(row: dict, source: Path, used_targets: set[Path]) -> Path:
    ext = source.suffix.lower()
    target = RAW_DIR / f"{row['job_id']}_manual_{timestamp()}{ext}"
    counter = 2
    while target.exists() or target in used_targets:
        target = RAW_DIR / f"{row['job_id']}_manual_{timestamp()}_{counter}{ext}"
        counter += 1
    used_targets.add(target)
    shutil.copy2(source, target)
    return target


def render_plan(rows: list[dict], imports: list[tuple[str, Path]]) -> list[tuple[dict, Path, Path]]:
    plan = []
    used_targets: set[Path] = set()
    for job_id, source in imports:
        row = validate_import(rows, job_id, source)
        ext = source.suffix.lower()
        target = RAW_DIR / f"{job_id}_manual_{timestamp()}{ext}"
        counter = 2
        while target.exists() or target in used_targets:
            target = RAW_DIR / f"{job_id}_manual_{timestamp()}_{counter}{ext}"
            counter += 1
        used_targets.add(target)
        plan.append((row, source, target))
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="手动导入 M01 聊天生成图片并回填 generation_jobs.csv")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-pending", action="store_true", help="列出 M01 pending 任务，不写文件")
    mode.add_argument("--dry-run", action="store_true", help="只检查并打印导入计划，不写文件")
    mode.add_argument("--execute", action="store_true", help="真实复制图片并回填 generation_jobs.csv")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--source", help="单张导入的图片路径，需配合 --job-id")
    source_group.add_argument("--manifest", help="批量导入清单 CSV，表头必须是 job_id,source_path")
    parser.add_argument("--job-id", help="单张导入的 job_id，例如 J0001")
    args = parser.parse_args()

    rows = read_jobs()

    if args.list_pending:
        list_pending(rows)
        return 0

    if args.source and not args.job_id:
        parser.error("--source 需要同时提供 --job-id")
    if args.job_id and not args.source:
        parser.error("--job-id 需要同时提供 --source")
    if not args.source and not args.manifest:
        parser.error("--dry-run/--execute 需要提供 --source 或 --manifest")

    imports = select_imports(args)
    plan = render_plan(rows, imports)

    print(f"准备导入 {len(plan)} 张 M01 图片：")
    print(f"{'job_id':<8} {'prompt_id':<14} {'source':<40} -> target")
    print("-" * 110)
    for row, source, target in plan:
        rel_target = target.relative_to(PROJECT_ROOT)
        print(f"{row['job_id']:<8} {row['prompt_id']:<14} {str(source):<40} -> {rel_target}")

    if args.dry_run:
        print("\n[DRY-RUN] 未复制图片；未修改 generation_jobs.csv。")
        return 0

    # 真正执行时重新计算目标文件名，避免 dry-run 和 execute 间隔太久导致命名冲突。
    row_by_id = {r["job_id"]: r for r in rows}
    used_targets: set[Path] = set()
    for job_id, source in imports:
        row = validate_import(rows, job_id, source)
        target = import_one(row, source, used_targets)
        rel_target = str(target.relative_to(PROJECT_ROOT))
        t = now_iso()
        attempts = int(row.get("attempts") or "0") + 1
        row.update({
            "seed": "",
            "status": "success",
            "attempts": str(attempts),
            "revised_prompt": "",
            "revision_reason": "manual_import_from_chat_image",
            "raw_image_path": rel_target,
            "error_code": "",
            "error_message": "",
            "timeout_sec": "",
            "safety_blocked": "false",
            "started_at": t,
            "finished_at": t,
        })
        row_by_id[job_id] = row
        print(f"[OK] {job_id} -> {rel_target}")

    write_jobs(rows)
    print("\n已写回 generation_jobs.csv。建议立刻运行：python3 scripts/validate_schema.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
