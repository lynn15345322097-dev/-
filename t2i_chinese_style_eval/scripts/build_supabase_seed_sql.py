"""Build a Supabase/Postgres seed SQL file from the current CSV data.

This script does not connect to any database. It reads local CSV files and writes
db/002_seed_current_data.sql, which can be reviewed before applying.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "db" / "002_seed_current_data.sql"
EVALUATION_SET_ID = "mvp_2026_06"

DEFAULT_REVIEWERS = [
    ("LYNN", "123321", "admin"),
    ("reviewer01", "moping01", "reviewer"),
    ("reviewer02", "moping02", "reviewer"),
    ("reviewer03", "moping03", "reviewer"),
    ("reviewer04", "moping04", "reviewer"),
    ("reviewer05", "moping05", "reviewer"),
    ("reviewer06", "moping06", "reviewer"),
    ("reviewer07", "moping07", "reviewer"),
    ("reviewer08", "moping08", "reviewer"),
    ("reviewer09", "moping09", "reviewer"),
    ("reviewer10", "moping10", "reviewer"),
]

BLIND_LABELS = {
    "M01": "Model_A",
    "M02": "Model_B",
    "M03": "Model_C",
}


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def sql_str(value: object) -> str:
    if value is None:
        return "null"
    text = str(value)
    if text == "":
        return "null"
    return "'" + text.replace("'", "''") + "'"


def sql_int(value: str) -> str:
    if value is None or str(value).strip() == "":
        return "null"
    return str(int(value))


def sql_bool(value: str) -> str:
    if value is None or str(value).strip() == "":
        return "null"
    return "true" if str(value).strip().lower() in {"true", "1", "yes"} else "false"


def password_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def values(rows: list[list[str]]) -> str:
    return ",\n".join("    (" + ", ".join(row) + ")" for row in rows)


def main() -> int:
    prompts = read_csv("prompts.csv")
    models = read_csv("models.csv")
    jobs = read_csv("generation_jobs.csv")
    metadata = read_csv("metadata.csv")
    rating_items = read_csv("rating_items.csv")
    human_scores = read_csv("human_scores.csv")

    metadata_by_image = {row["image_id"]: row for row in metadata}
    job_by_id = {row["job_id"]: row for row in jobs}

    lines: list[str] = [
        "-- Seed current SumiRate data into Supabase/Postgres.",
        "-- Generated from local CSV files. Review before applying.",
        "begin;",
        "",
    ]

    lines.append(
        "insert into evaluation_sets (evaluation_set_id, name, description, status) values\n"
        f"    ({sql_str(EVALUATION_SET_ID)}, 'MVP 2026-06', 'Initial 48-image blind rating set', 'active')\n"
        "on conflict (evaluation_set_id) do update set\n"
        "    name = excluded.name,\n"
        "    description = excluded.description,\n"
        "    status = excluded.status;"
    )
    lines.append("")

    model_rows = [
        [sql_str(r["model_id"]), sql_str(r["model_name"]), sql_str(r["provider"]), sql_str(r.get("notes", ""))]
        for r in models
    ]
    lines.append(
        "insert into models (model_id, model_name, provider, notes) values\n"
        + values(model_rows)
        + "\non conflict (model_id) do update set\n"
        "    model_name = excluded.model_name,\n"
        "    provider = excluded.provider,\n"
        "    notes = excluded.notes;"
    )
    lines.append("")

    blind_rows = [
        [sql_str(EVALUATION_SET_ID), sql_str(model_id), sql_str(label)]
        for model_id, label in BLIND_LABELS.items()
    ]
    lines.append(
        "insert into model_blind_labels (evaluation_set_id, model_id, blind_model_label) values\n"
        + values(blind_rows)
        + "\non conflict (evaluation_set_id, model_id) do update set\n"
        "    blind_model_label = excluded.blind_model_label;"
    )
    lines.append("")

    prompt_rows = [
        [
            sql_str(r["prompt_id"]),
            sql_str(r["target_style"]),
            sql_str(r["prompt_level"]),
            sql_str(r["prompt_text"]),
            sql_str(r.get("expected_elements", "")),
            sql_str(r.get("forbidden_elements", "")),
        ]
        for r in prompts
    ]
    lines.append(
        "insert into prompts (prompt_id, target_style, prompt_level, prompt_text, expected_elements, forbidden_elements) values\n"
        + values(prompt_rows)
        + "\non conflict (prompt_id) do update set\n"
        "    target_style = excluded.target_style,\n"
        "    prompt_level = excluded.prompt_level,\n"
        "    prompt_text = excluded.prompt_text,\n"
        "    expected_elements = excluded.expected_elements,\n"
        "    forbidden_elements = excluded.forbidden_elements,\n"
        "    updated_at = now();"
    )
    lines.append("")

    job_rows = []
    for r in jobs:
        job_rows.append([
            sql_str(r["job_id"]),
            sql_str(r["prompt_id"]),
            sql_str(r["model_id"]),
            sql_int(r.get("replicate_idx", "")),
            sql_int(r.get("seed", "")),
            sql_str(r["status"]),
            sql_int(r.get("attempts", "")),
            sql_str(r["original_prompt"]),
            sql_str(r.get("revised_prompt", "")),
            sql_str(r.get("revision_reason", "")),
            sql_str(r.get("raw_image_path", "")),
            sql_str(r.get("error_code", "")),
            sql_str(r.get("error_message", "")),
            sql_int(r.get("timeout_sec", "")),
            sql_bool(r.get("safety_blocked", "")),
            sql_str(r.get("created_at", "")),
            sql_str(r.get("started_at", "")),
            sql_str(r.get("finished_at", "")),
        ])
    lines.append(
        "insert into generation_jobs (job_id, prompt_id, model_id, replicate_idx, seed, status, attempts, original_prompt, revised_prompt, revision_reason, raw_image_path, error_code, error_message, timeout_sec, safety_blocked, created_at, started_at, finished_at) values\n"
        + values(job_rows)
        + "\non conflict (job_id) do update set\n"
        "    status = excluded.status,\n"
        "    attempts = excluded.attempts,\n"
        "    raw_image_path = excluded.raw_image_path,\n"
        "    error_code = excluded.error_code,\n"
        "    error_message = excluded.error_message,\n"
        "    safety_blocked = excluded.safety_blocked,\n"
        "    started_at = excluded.started_at,\n"
        "    finished_at = excluded.finished_at;"
    )
    lines.append("")

    item_rows = []
    for r in rating_items:
        meta = metadata_by_image[r["image_id"]]
        item_rows.append([
            sql_str(r["image_id"]),
            sql_str(EVALUATION_SET_ID),
            sql_str(meta["job_id"]),
            sql_str(r["blind_filename"]),
            sql_str(meta.get("blind_image_path", "")),
            sql_str(r["target_style"]),
            sql_str(r["prompt_level"]),
            sql_str(meta.get("original_prompt") or r["prompt_text"]),
            sql_str(r.get("expected_elements", "")),
            sql_str(r.get("forbidden_elements", "")),
            sql_int(meta.get("image_width", "")),
            sql_int(meta.get("image_height", "")),
            sql_str(meta.get("generated_at", "")),
        ])
    lines.append(
        "insert into rating_items (image_id, evaluation_set_id, job_id, blind_filename, blind_image_path, target_style, prompt_level, prompt_text, expected_elements, forbidden_elements, image_width, image_height, generated_at) values\n"
        + values(item_rows)
        + "\non conflict (image_id) do update set\n"
        "    blind_filename = excluded.blind_filename,\n"
        "    blind_image_path = excluded.blind_image_path,\n"
        "    target_style = excluded.target_style,\n"
        "    prompt_level = excluded.prompt_level,\n"
        "    prompt_text = excluded.prompt_text,\n"
        "    expected_elements = excluded.expected_elements,\n"
        "    forbidden_elements = excluded.forbidden_elements,\n"
        "    image_width = excluded.image_width,\n"
        "    image_height = excluded.image_height,\n"
        "    generated_at = excluded.generated_at;"
    )
    lines.append("")

    reviewer_rows = [
        [sql_str(rid), sql_str(rid), sql_str(password_hash(pwd)), sql_str(role)]
        for rid, pwd, role in DEFAULT_REVIEWERS
    ]
    lines.append(
        "insert into reviewers (reviewer_id, display_name, password_hash, role) values\n"
        + values(reviewer_rows)
        + "\non conflict (reviewer_id) do update set\n"
        "    display_name = excluded.display_name,\n"
        "    password_hash = excluded.password_hash,\n"
        "    role = excluded.role;"
    )
    lines.append("")

    if human_scores:
        rating_rows = []
        for r in human_scores:
            meta = metadata_by_image[r["image_id"]]
            job = job_by_id[meta["job_id"]]
            model_id = meta["model_id"]
            rating_rows.append([
                sql_str(r["rating_id"]),
                sql_str(EVALUATION_SET_ID),
                sql_str(r["image_id"]),
                sql_str(meta["job_id"]),
                sql_str(job["prompt_id"]),
                sql_str(r["rater_id"]),
                sql_str(BLIND_LABELS.get(model_id, "Model_Unknown")),
                sql_int(r["style_consistency_score"]),
                sql_int(r["element_accuracy_score"]),
                sql_int(r["error_control_score"]),
                sql_int(r["overall_score"]),
                sql_str(r.get("error_tags", "")),
                sql_str(r.get("comment", "")),
                sql_str(r["rated_at"]),
                sql_str(r["rated_at"]),
            ])
        lines.append(
            "insert into ratings (rating_id, evaluation_set_id, image_id, job_id, prompt_id, reviewer_id, blind_model_label, style_consistency_score, element_accuracy_score, error_control_score, overall_score, error_tags, comment, created_at, updated_at) values\n"
            + values(rating_rows)
            + "\non conflict (evaluation_set_id, image_id, reviewer_id) do update set\n"
            "    style_consistency_score = excluded.style_consistency_score,\n"
            "    element_accuracy_score = excluded.element_accuracy_score,\n"
            "    error_control_score = excluded.error_control_score,\n"
            "    overall_score = excluded.overall_score,\n"
            "    error_tags = excluded.error_tags,\n"
            "    comment = excluded.comment,\n"
            "    updated_at = excluded.updated_at;"
        )
        lines.append("")

    lines.extend(["commit;", ""])
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
