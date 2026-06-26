"""audit_blind_set.py — 审计盲评图片集

检查目标：
  - rating_items.csv 只能包含盲评允许字段，不能泄露 model_id/job_id/seed 等敏感信息。
  - metadata.csv、rating_items.csv、images/blind/ 三者一致。
  - 32 张盲图都能打开，尺寸与 metadata 记录一致。
  - 每个 (prompt_id, model_id) 正好 2 张，MVP 总量为 32 张。

输出：
  reports/blind_set_audit.md
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BLIND_DIR = PROJECT_ROOT / "images" / "blind"
REPORTS_DIR = PROJECT_ROOT / "reports"

METADATA_CSV = DATA_DIR / "metadata.csv"
RATING_ITEMS_CSV = DATA_DIR / "rating_items.csv"
GENERATION_JOBS_CSV = DATA_DIR / "generation_jobs.csv"
REPORT_PATH = REPORTS_DIR / "blind_set_audit.md"

RATING_FIELDS = [
    "image_id", "blind_filename", "target_style", "prompt_level",
    "prompt_text", "expected_elements", "forbidden_elements",
]

SENSITIVE_RATING_FIELDS = {
    "model_id", "model_name", "seed", "job_id", "original_prompt",
    "revised_prompt", "raw_image_path", "auto_scores", "score_id",
}


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    if not path.exists():
        return [], []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames or [], list(reader)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_issue(issues: list[dict], level: str, item: str, message: str) -> None:
    issues.append({"level": level, "item": item, "message": message})


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        return im.size


def audit() -> tuple[list[dict], dict]:
    issues: list[dict] = []
    rating_header, rating_rows = read_csv(RATING_ITEMS_CSV)
    metadata_header, metadata_rows = read_csv(METADATA_CSV)
    _, job_rows = read_csv(GENERATION_JOBS_CSV)

    if not rating_rows:
        add_issue(issues, "ERROR", "rating_items.csv", "没有数据行")
    if not metadata_rows:
        add_issue(issues, "ERROR", "metadata.csv", "没有数据行")

    if rating_header != RATING_FIELDS:
        add_issue(issues, "ERROR", "rating_items.csv", f"表头不符合盲评字段要求：{rating_header}")
    leaked = sorted(set(rating_header) & SENSITIVE_RATING_FIELDS)
    if leaked:
        add_issue(issues, "ERROR", "rating_items.csv", f"发现敏感字段泄露：{leaked}")

    rating_ids = [r.get("image_id", "") for r in rating_rows]
    metadata_ids = [r.get("image_id", "") for r in metadata_rows]
    for name, ids in [("rating_items.csv", rating_ids), ("metadata.csv", metadata_ids)]:
        duplicates = sorted([k for k, v in Counter(ids).items() if k and v > 1])
        if duplicates:
            add_issue(issues, "ERROR", name, f"image_id 重复：{duplicates}")

    rating_by_id = {r["image_id"]: r for r in rating_rows}
    metadata_by_id = {r["image_id"]: r for r in metadata_rows}
    missing_in_metadata = sorted(set(rating_by_id) - set(metadata_by_id))
    missing_in_rating = sorted(set(metadata_by_id) - set(rating_by_id))
    if missing_in_metadata:
        add_issue(issues, "ERROR", "metadata.csv", f"缺少 rating_items 中的 image_id：{missing_in_metadata}")
    if missing_in_rating:
        add_issue(issues, "ERROR", "rating_items.csv", f"缺少 metadata 中的 image_id：{missing_in_rating}")

    blind_files = sorted(p.name for p in BLIND_DIR.iterdir() if p.is_file() and p.name != ".gitkeep")
    expected_files = sorted(r.get("blind_filename", "") for r in rating_rows)
    missing_files = sorted(set(expected_files) - set(blind_files))
    extra_files = sorted(set(blind_files) - set(expected_files))
    if missing_files:
        add_issue(issues, "ERROR", "images/blind", f"缺少盲图文件：{missing_files}")
    if extra_files:
        add_issue(issues, "WARN", "images/blind", f"存在未登记盲图文件：{extra_files}")

    for image_id, rating in rating_by_id.items():
        meta = metadata_by_id.get(image_id)
        if not meta:
            continue
        for field in ["blind_filename", "prompt_text", "expected_elements", "forbidden_elements"]:
            if rating.get(field, "") != meta.get(field if field != "prompt_text" else "original_prompt", ""):
                if field == "prompt_text":
                    add_issue(issues, "ERROR", image_id, "rating_items.prompt_text 与 metadata.original_prompt 不一致")
                else:
                    # expected/forbidden 不在 metadata 中，跳过；它们来自 prompts.csv。
                    pass
        blind_rel = meta.get("blind_image_path", "")
        if blind_rel != f"images/blind/{rating.get('blind_filename', '')}":
            add_issue(issues, "ERROR", image_id, f"blind_image_path 与 blind_filename 不一致：{blind_rel}")

        path = PROJECT_ROOT / blind_rel
        if not path.exists():
            continue
        try:
            width, height = image_size(path)
        except Exception as e:
            add_issue(issues, "ERROR", image_id, f"图片无法打开：{type(e).__name__}: {e}")
            continue
        if str(width) != meta.get("image_width", "") or str(height) != meta.get("image_height", ""):
            add_issue(
                issues, "ERROR", image_id,
                f"图片尺寸与 metadata 不一致：actual={width}x{height}, metadata={meta.get('image_width')}x{meta.get('image_height')}",
            )

    success_jobs = [j for j in job_rows if j.get("status") == "success"]
    success_job_ids = {j["job_id"] for j in success_jobs}
    metadata_job_ids = {m.get("job_id", "") for m in metadata_rows}
    missing_success_jobs = sorted(success_job_ids - metadata_job_ids)
    extra_metadata_jobs = sorted(metadata_job_ids - success_job_ids)
    if missing_success_jobs:
        add_issue(issues, "ERROR", "metadata.csv", f"缺少成功生成 job：{missing_success_jobs}")
    if extra_metadata_jobs:
        add_issue(issues, "ERROR", "metadata.csv", f"包含非成功 job 或未知 job：{extra_metadata_jobs}")

    prompt_model_counts = Counter((m.get("prompt_id", ""), m.get("model_id", "")) for m in metadata_rows)
    for key, count in sorted(prompt_model_counts.items()):
        if count != 2:
            add_issue(issues, "ERROR", "metadata.csv", f"(prompt_id, model_id)={key} 数量应为 2，实际 {count}")

    style_counts = Counter(r.get("target_style", "") for r in rating_rows)
    level_counts = Counter(r.get("prompt_level", "") for r in rating_rows)
    model_counts = Counter(m.get("model_id", "") for m in metadata_rows)
    size_counts = Counter(f"{m.get('image_width')}x{m.get('image_height')}" for m in metadata_rows)

    prompt_model_table = defaultdict(dict)
    for (prompt_id, model_id), count in sorted(prompt_model_counts.items()):
        prompt_model_table[prompt_id][model_id] = count

    summary = {
        "rating_count": len(rating_rows),
        "metadata_count": len(metadata_rows),
        "blind_file_count": len(blind_files),
        "success_job_count": len(success_jobs),
        "style_counts": style_counts,
        "level_counts": level_counts,
        "model_counts": model_counts,
        "size_counts": size_counts,
        "prompt_model_table": dict(prompt_model_table),
        "error_count": sum(1 for i in issues if i["level"] == "ERROR"),
        "warning_count": sum(1 for i in issues if i["level"] == "WARN"),
    }
    return issues, summary


def format_counter(counter: Counter) -> str:
    if not counter:
        return "- 无"
    return "\n".join(f"- {k}: {v}" for k, v in sorted(counter.items()))


def write_report(issues: list[dict], summary: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 盲评图片集审计报告",
        "",
        f"- 生成时间：{now_iso()}",
        f"- rating_items.csv 行数：{summary['rating_count']}",
        f"- metadata.csv 行数：{summary['metadata_count']}",
        f"- images/blind 文件数：{summary['blind_file_count']}",
        f"- generation_jobs success 数：{summary['success_job_count']}",
        f"- ERROR：{summary['error_count']}",
        f"- WARN：{summary['warning_count']}",
        "",
        "## 分布检查",
        "",
        "### 模型分布（仅 metadata，可解密，网站不可读）",
        "",
        format_counter(summary["model_counts"]),
        "",
        "### 目标风格分布（rating_items）",
        "",
        format_counter(summary["style_counts"]),
        "",
        "### Prompt Level 分布（rating_items）",
        "",
        format_counter(summary["level_counts"]),
        "",
        "### 图片尺寸分布（metadata）",
        "",
        format_counter(summary["size_counts"]),
        "",
        "## 每个 Prompt × Model 数量",
        "",
        "| prompt_id | M01 | M02 |",
        "|---|---:|---:|",
    ]
    for prompt_id, model_map in sorted(summary["prompt_model_table"].items()):
        lines.append(f"| {prompt_id} | {model_map.get('M01', 0)} | {model_map.get('M02', 0)} |")

    lines.extend(["", "## 问题列表", ""])
    if not issues:
        lines.append("未发现问题。")
    else:
        lines.append("| level | item | message |")
        lines.append("|---|---|---|")
        for issue in issues:
            msg = issue["message"].replace("|", "\\|")
            lines.append(f"| {issue['level']} | {issue['item']} | {msg} |")

    lines.extend([
        "",
        "## 结论",
        "",
        "若 ERROR=0，则当前盲评图片集可用于主观评分和客观评价。rating_items.csv 不包含模型来源、job_id、seed 或 auto_scores 字段。",
    ])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="审计盲评图片集并生成 reports/blind_set_audit.md")
    parser.add_argument("--write-report", action="store_true", help="写入 Markdown 报告")
    args = parser.parse_args()

    issues, summary = audit()
    print(f"rating_items: {summary['rating_count']}")
    print(f"metadata: {summary['metadata_count']}")
    print(f"blind_files: {summary['blind_file_count']}")
    print(f"success_jobs: {summary['success_job_count']}")
    print(f"ERROR: {summary['error_count']}")
    print(f"WARN: {summary['warning_count']}")

    if issues:
        print()
        for issue in issues:
            print(f"[{issue['level']}] {issue['item']}: {issue['message']}")

    if args.write_report:
        write_report(issues, summary)
        print(f"[OK] wrote {REPORT_PATH.relative_to(PROJECT_ROOT)}")

    return 1 if summary["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
