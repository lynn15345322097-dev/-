"""SumiRate subjective rating app, using the provided reference UI verbatim.

The pages are rendered from web/reference/.../code.html and only receive small
server-side substitutions for data, form actions, and navigation. The app reads
only rating_items.csv and images/blind/, and writes human_scores.csv/app.db.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"
DATA_DIR = PROJECT_ROOT / "data"
BLIND_IMAGE_DIR = PROJECT_ROOT / "images" / "blind"
REF_DIR = WEB_DIR / "reference" / "stitch_traditional_t2i_style_evaluator"
RATING_ITEMS_CSV = DATA_DIR / "rating_items.csv"
HUMAN_SCORES_CSV = DATA_DIR / "human_scores.csv"
RATINGS_CSV = DATA_DIR / "ratings.csv"
DB_PATH = WEB_DIR / "app.db"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(PROJECT_ROOT / ".env")
load_env_file(PROJECT_ROOT / ".env.supabase")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8063"))
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
EVALUATION_SET_ID = os.environ.get("EVALUATION_SET_ID", "mvp_2026_06")

ADMIN_IDS: set[str] = set(os.environ.get("ADMIN_IDS", "LYNN").split(",")) - {""}

BLIND_MODEL_LABELS = {
    "M01": "Model_A",
    "M02": "Model_B",
    "M03": "Model_C",
}


def is_admin(rater_id: str | None) -> bool:
    return bool(rater_id) and rater_id in ADMIN_IDS

ERROR_TAGS = [
    "现代插画化",
    "对象错误",
    "门类混搭",
    "写实摄影化",
    "西式元素混入",
    "色彩失真",
    "构图失范",
    "其他",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def ref_page(name: str) -> str:
    return (REF_DIR / name / "code.html").read_text(encoding="utf-8")


def metadata_by_image_id() -> dict[str, dict[str, str]]:
    metadata_csv_path = DATA_DIR / "metadata.csv"
    if not metadata_csv_path.exists():
        return {}
    with metadata_csv_path.open(newline="", encoding="utf-8") as f:
        return {
            row["image_id"]: row
            for row in csv.DictReader(f)
            if row.get("image_id")
        }


def real_prompt_for_image(image_id: str, fallback: str = "") -> str:
    meta = metadata_by_image_id().get(image_id, {})
    return (meta.get("original_prompt") or fallback or "").strip()


def supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def generation_jobs_by_id() -> dict[str, dict[str, str]]:
    jobs_csv_path = DATA_DIR / "generation_jobs.csv"
    if not jobs_csv_path.exists():
        return {}
    with jobs_csv_path.open(newline="", encoding="utf-8") as f:
        return {
            row["job_id"]: row
            for row in csv.DictReader(f)
            if row.get("job_id")
        }


def supabase_rating_payload(
    *,
    rating_id: str,
    image_id: str,
    rater_id: str,
    rated_at: str,
    values: dict[str, int],
    error_tags: str,
    comment: str,
) -> dict[str, object]:
    meta = metadata_by_image_id().get(image_id)
    if not meta:
        raise ValueError(f"missing metadata for image_id={image_id}")
    job = generation_jobs_by_id().get(meta["job_id"])
    if not job:
        raise ValueError(f"missing generation job for job_id={meta['job_id']}")
    model_id = meta.get("model_id", "")
    return {
        "rating_id": rating_id,
        "evaluation_set_id": EVALUATION_SET_ID,
        "image_id": image_id,
        "job_id": meta["job_id"],
        "prompt_id": job["prompt_id"],
        "reviewer_id": rater_id,
        "blind_model_label": BLIND_MODEL_LABELS.get(model_id, "Model_Unknown"),
        "style_consistency_score": values["style_consistency_score"],
        "element_accuracy_score": values["element_accuracy_score"],
        "error_control_score": values["error_control_score"],
        "overall_score": values["overall_score"],
        "error_tags": error_tags or None,
        "comment": comment or None,
        "created_at": rated_at,
        "updated_at": rated_at,
    }


def upsert_supabase_rating(payload: dict[str, object]) -> None:
    if not supabase_enabled():
        return
    endpoint = (
        f"{SUPABASE_URL}/rest/v1/ratings"
        "?on_conflict=evaluation_set_id,image_id,reviewer_id"
    )
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
    )
    try:
        with urlopen(request, timeout=15):
            return
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase rating upsert failed: HTTP {exc.code} {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Supabase rating upsert failed: {exc.reason}") from exc


def apply_top_nav(page: str, active: str, rater_id: str | None) -> str:
    active_class = "text-primary border-b-2 border-primary pb-1 transition-colors duration-300"
    inactive_class = "text-on-surface-variant hover:text-primary transition-colors duration-300"
    nav_items = [
        ("profile", "Dashboard", "/profile"),
        ("rate", "Gallery", "/rate"),
    ]
    if is_admin(rater_id):
        nav_items.append(("admin", "Archive", "/admin"))
    links = "\n".join(
        f'<a class="{active_class if key == active else inactive_class}" href="{href}">{label}</a>'
        for key, label, href in nav_items
    )

    def replace_nav(match: re.Match[str]) -> str:
        return f'{match.group(1)}\n{links}\n</nav>'

    page = re.sub(
        r'(<nav class="[^"]*">)\s*<a[^>]*>Dashboard</a>\s*<a[^>]*>Gallery</a>\s*<a[^>]*>Archive</a>\s*</nav>',
        replace_nav,
        page,
        count=1,
        flags=re.DOTALL,
    )
    page = page.replace('href="#">Dashboard</a>', 'href="/profile">Dashboard</a>')
    page = page.replace('href="#">Gallery</a>', 'href="/rate">Gallery</a>')
    page = page.replace('href="#">Archive</a>', 'href="/admin">Archive</a>' if is_admin(rater_id) else 'href="/profile">Archive</a>')
    return page


def localize_zh(page: str) -> str:
    """Localize visible UI copy to Chinese without changing layout or styles."""
    page = page.replace(
        "cursor: url('https://cdn-icons-png.flaticon.com/32/3011/3011153.png'), auto;",
        "cursor: auto;",
    )
    replacements = {
        "Quality Recognition System": "传统视觉风格评分系统",
        "进入工作室 <span class=\"text-secondary font-label-sm ml-2 text-sm opacity-50\">/ ACCESS</span>": "进入工作室",
        "审查者身份标识 / IDENTITY": "评审者编号",
        "通行令牌 / ACCESS TOKEN": "通行令牌",
        "申请权限": "申请权限",
        "故障申报": "问题反馈",
        "Dashboard": "主页",
        "Gallery": "评分",
        "Archive": "管理",
        "Reviewer Status": "评审进度",
        "Logout": "退出",
        "Inspector": "评审员",
        "Ink Master Level": "评审任务",
        "Composition": "构图",
        "Tone": "色调",
        "Contrast": "对比",
        "Stamp": "落款",
        "Finalize Rating": "完成评分",
        "Target Style / 目标风格": "目标风格",
        "Prompt Context / 提示语背景": "提示语",
        "Return to Studio / 返回工作室": "返回主页",
        "Skip / 跳过": "跳过",
        "Rating Form / 评审表": "评审表",
        "Style / 风格相符度": "形式风格一致性",
        "Accuracy / 意境准确性": "文化元素准确性",
        "Accuracy / 元素准确性": "文化元素准确性",
        "Propriety / 笔墨得体": "文化语境得体性",
        "Propriety / 语境得体": "文化语境得体性",
        "Overall / 综合感官": "整体评分",
        "Overall / 整体评分": "整体评分",
        "Scale 1-5": "1-5 分",
        "Error Checklist / 瑕疵识别": "错误类型",
        "Apply Seal / 落款评定": "提交评定",
        "Rated / 已评定": "已提交",
        "Return / 返回主页": "返回主页",
        "评分已完成": "评分已完成",
        "当前没有未评分图像。": "当前没有未评分图像。",
        "评分管理概览": "评分管理概览",
        "Active Reviewers": "活跃评审者",
        "评审员 (Reviewer)": "评审者",
        "Export": "导出",
        "Import": "导入",
        "Items": "任务数",
        "Scores": "评分数",
        "Raters": "评审者数",
        "completed": "已完成",
        "Start Rating": "开始评分",
        "Start / Continue": "开始 / 继续",
    }
    for old, new in replacements.items():
        page = page.replace(old, new)
    return page


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    BLIND_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            create table if not exists raters (
                rater_id text primary key,
                display_name text not null,
                password_hash text,
                created_at text not null
            );
            create table if not exists rating_items (
                image_id text primary key,
                blind_filename text not null,
                target_style text not null,
                prompt_level text not null,
                prompt_text text not null,
                expected_elements text,
                forbidden_elements text
            );
            create table if not exists feedback (
                id integer primary key autoincrement,
                rater_id text not null,
                content text not null,
                created_at text not null
            );
            create table if not exists human_scores (
                rating_id text primary key,
                image_id text not null,
                rater_id text not null,
                rated_at text not null,
                style_consistency_score integer not null,
                element_accuracy_score integer not null,
                error_control_score integer not null,
                overall_score integer not null,
                error_tags text,
                comment text,
                unique(image_id, rater_id)
            );
            """
        )
        try:
            conn.execute("alter table raters add column password_hash text")
        except sqlite3.OperationalError:
            pass
        for old_col, new_col in [
            ("style_fidelity", "style_consistency_score"),
            ("element_accuracy", "element_accuracy_score"),
            ("context_appropriateness", "error_control_score"),
        ]:
            try:
                conn.execute(f"alter table human_scores rename column {old_col} to {new_col}")
            except sqlite3.OperationalError:
                pass
    # Pre-seed admin + 10 reviewer accounts
    seed_raters = [
        ("LYNN", "123321"),
    ] + [
        ("reviewer01", "moping01"),
        ("reviewer02", "moping02"),
        ("reviewer03", "moping03"),
        ("reviewer04", "moping04"),
        ("reviewer05", "moping05"),
        ("reviewer06", "moping06"),
        ("reviewer07", "moping07"),
        ("reviewer08", "moping08"),
        ("reviewer09", "moping09"),
        ("reviewer10", "moping10"),
    ]
    with connect() as conn:
        for rid, pwd in seed_raters:
            conn.execute(
                "insert or ignore into raters (rater_id, display_name, password_hash, created_at) values (?, ?, ?, ?)",
                (rid, rid, hash_password(pwd), now_iso()),
            )
    import_rating_items()
    export_human_scores()
    export_ratings()


def import_rating_items() -> int:
    if not RATING_ITEMS_CSV.exists():
        return 0

    count = 0
    image_ids = set()
    metadata = metadata_by_image_id()
    with RATING_ITEMS_CSV.open(newline="", encoding="utf-8") as f, connect() as conn:
        for row in csv.DictReader(f):
            image_id = row.get("image_id", "").strip()
            blind_filename = row.get("blind_filename", "").strip()
            if not image_id or not blind_filename:
                continue

            prompt_text = (metadata.get(image_id, {}).get("original_prompt") or row.get("prompt_text", "")).strip()
            image_ids.add(image_id)
            conn.execute(
                """
                insert into rating_items (
                    image_id, blind_filename, target_style, prompt_level,
                    prompt_text, expected_elements, forbidden_elements
                ) values (
                    ?, ?, ?, ?, ?, ?, ?
                )
                on conflict(image_id) do update set
                    blind_filename=excluded.blind_filename,
                    target_style=excluded.target_style,
                    prompt_level=excluded.prompt_level,
                    prompt_text=excluded.prompt_text,
                    expected_elements=excluded.expected_elements,
                    forbidden_elements=excluded.forbidden_elements
                """,
                (
                    image_id,
                    blind_filename,
                    row.get("target_style", ""),
                    row.get("prompt_level", ""),
                    prompt_text,
                    row.get("expected_elements", ""),
                    row.get("forbidden_elements", ""),
                ),
            )
            count += 1

        if image_ids:
            placeholders = ",".join("?" for _ in image_ids)
            conn.execute(
                f"delete from rating_items where image_id not in ({placeholders})",
                list(image_ids)
            )
        else:
            conn.execute("delete from rating_items")
            
    return count


def export_human_scores() -> None:
    with connect() as conn:
        rows = conn.execute(
            """
            select rating_id, image_id, rater_id, rated_at,
                   style_consistency_score, element_accuracy_score, error_control_score,
                   overall_score, error_tags, comment
            from human_scores
            order by rated_at, rater_id, image_id
            """
        ).fetchall()
    with HUMAN_SCORES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "rating_id",
                "image_id",
                "rater_id",
                "rated_at",
                "style_consistency_score",
                "element_accuracy_score",
                "error_control_score",
                "overall_score",
                "error_tags",
                "comment",
            ]
        )
        for row in rows:
            writer.writerow([row[k] for k in row.keys()])


def export_ratings() -> None:
    # Build image_id → {job_id, prompt_id, model_id} from metadata.csv
    meta = {}
    metadata_csv_path = DATA_DIR / "metadata.csv"
    if metadata_csv_path.exists():
        with metadata_csv_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                iid = row.get("image_id")
                if iid:
                    meta[iid] = row

    with connect() as conn:
        rows = conn.execute(
            """
            select rating_id, image_id, rater_id, rated_at,
                   style_consistency_score, element_accuracy_score, error_control_score,
                   overall_score, error_tags, comment
            from human_scores
            order by rated_at, rater_id, image_id
            """
        ).fetchall()

    with RATINGS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "reviewer_id",
            "job_id",
            "prompt_id",
            "blind_model_label",
            "style_consistency_score",
            "element_accuracy_score",
            "error_control_score",
            "overall_score",
            "备注",
            "created_at"
        ])
        for row in rows:
            info = meta.get(row["image_id"], {})
            real_job_id = info.get("job_id", "")
            prompt_id = info.get("prompt_id", "")
            model_id = info.get("model_id", "")

            if model_id == "M01":
                blind_model_label = "Model_A"
            elif model_id == "M02":
                blind_model_label = "Model_B"
            else:
                blind_model_label = f"Model_{model_id}" if model_id else "Unknown"

            errors = row["error_tags"]
            comment = row["comment"]
            notes_parts = []
            if errors:
                notes_parts.append(f"错误类型: {errors}")
            if comment:
                notes_parts.append(f"评语: {comment}")
            notes = " | ".join(notes_parts)

            writer.writerow([
                row["rater_id"],
                real_job_id,
                prompt_id,
                blind_model_label,
                row["style_consistency_score"],
                row["element_accuracy_score"] if row["element_accuracy_score"] != 0 else "",
                row["error_control_score"] if row["error_control_score"] != 0 else "",
                row["overall_score"] if row["overall_score"] != 0 else "",
                notes,
                row["rated_at"]
            ])


def progress_for(rater_id: str | None = None) -> dict[str, int]:
    with connect() as conn:
        total = conn.execute("select count(*) from rating_items").fetchone()[0]
        raters = conn.execute("select count(*) from raters").fetchone()[0]
        if rater_id:
            done = conn.execute(
                "select count(*) from human_scores where rater_id = ?", (rater_id,)
            ).fetchone()[0]
        else:
            done = conn.execute("select count(*) from human_scores").fetchone()[0]
    return {"total": total, "done": done, "remaining": max(total - done, 0), "raters": raters}


def next_item(rater_id: str, exclude_image_id: str | None = None) -> sqlite3.Row | None:
    with connect() as conn:
        params: list[str] = [rater_id]
        exclude_clause = ""
        if exclude_image_id:
            exclude_clause = "and image_id != ?"
            params.append(exclude_image_id)
        row = conn.execute(
            """
            select *
            from rating_items
            where image_id not in (
                select image_id from human_scores where rater_id = ?
            )
            {exclude_clause}
            order by abs(random())
            limit 1
            """.format(exclude_clause=exclude_clause),
            params,
        ).fetchone()
        if row is not None or not exclude_image_id:
            return row
        return conn.execute(
            """
            select *
            from rating_items
            where image_id not in (
                select image_id from human_scores where rater_id = ?
            )
            order by abs(random())
            limit 1
            """,
            (rater_id,),
        ).fetchone()


def prev_item(rater_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            select ri.*, hs.style_consistency_score, hs.element_accuracy_score, hs.error_control_score, hs.overall_score, hs.comment
            from rating_items ri
            join human_scores hs on ri.image_id = hs.image_id
            where hs.rater_id = ?
            order by hs.rated_at desc
            limit 1
            """,
            (rater_id,),
        ).fetchone()


def get_item_with_score(image_id: str, rater_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            select ri.*, hs.style_consistency_score, hs.element_accuracy_score, hs.error_control_score,
                   hs.overall_score, hs.comment, hs.error_tags as prev_error_tags
            from rating_items ri
            left join human_scores hs on ri.image_id = hs.image_id and hs.rater_id = ?
            where ri.image_id = ?
            """,
            (rater_id, image_id),
        ).fetchone()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def render_thumbnail_sidebar(rater_id: str, current_image_id: str) -> str:
    with connect() as conn:
        items = conn.execute("select image_id from rating_items order by image_id").fetchall()
        rated_rows = conn.execute(
            "select image_id from human_scores where rater_id = ?", (rater_id,)
        ).fetchall()
    rated_set = {row["image_id"] for row in rated_rows}

    thumbnails = []
    for item in items:
        iid = item["image_id"]
        is_rated = iid in rated_set
        is_current = iid == current_image_id
        border = "border-primary" if is_current else ("border-emerald-600/40" if is_rated else "border-outline-variant/30")
        bg = "bg-surface-container-highest" if is_current else ""
        status_text = "已评" if is_rated else "未评"
        status_color = "text-emerald-700" if is_rated else "text-secondary"

        thumbnails.append(
            f"""<a href="/rate?image_id={esc(iid)}" class="flex items-center gap-2 p-2 rounded {bg} hover:bg-surface-container-highest transition-colors border {border}">
<div class="w-11 h-11 shrink-0 bg-surface-variant overflow-hidden">
<img src="/image/{esc(iid)}.png" class="w-full h-full object-cover" loading="lazy" onerror="this.style.display='none'"/>
</div>
<div class="flex-1 min-w-0">
<p class="font-label-sm text-label-sm truncate">{esc(iid)}</p>
<span class="text-[10px] {status_color}">{status_text}</span>
</div>
</a>"""
        )

    return f"""<aside class="hidden lg:flex h-screen w-56 sticky top-20 flex-col border-r border-outline-variant/20 bg-surface-container-low shrink-0">
<div class="p-3 border-b border-outline-variant/20">
<h3 class="font-label-sm text-label-sm text-secondary">评测图片</h3>
<p class="text-[10px] text-secondary mt-0.5">{len(rated_set)}/{len(items)} 已评</p>
</div>
<div class="flex-1 overflow-y-auto p-2 space-y-1">
{"".join(thumbnails)}
</div>
</aside>"""


def render_login(error: str = "") -> str:
    page = ref_page("login")
    page = page.replace(
        '<form action="#" class="space-y-8" onsubmit="return false;">',
        '<form method="post" action="/login" class="space-y-8">',
    )
    page = page.replace('id="reviewer-id" placeholder="请输入审查者编号" type="text"', 'id="reviewer-id" name="rater_id" placeholder="请输入审查者编号" type="text" required')
    page = page.replace('id="access-token" placeholder="••••••••" type="password"', 'id="access-token" name="password" placeholder="••••••••" type="password" required')
    page = page.replace('href="#">申请权限</a>', 'href="/login">申请权限</a>')
    page = page.replace('href="#">故障申报</a>', 'href="/login">故障申报</a>')
    page = page.replace('<!-- Micro-interaction Script -->', '<!-- Micro-interaction Script disabled for real form submit -->')
    page = page.split("<!-- Micro-interaction Script disabled for real form submit -->")[0] + "</body></html>"
    if error:
        page = page.replace(
            '<form method="post" action="/login" class="space-y-8">',
            f'<p class="mb-5 text-error font-label-sm text-label-sm">{esc(error)}</p><form method="post" action="/login" class="space-y-8">',
        )
    return page


def render_profile(rater_id: str) -> str:
    p = progress_for(rater_id)
    pct = 0 if p["total"] == 0 else round(p["done"] / p["total"] * 100)
    page = ref_page("profile")
    page = page.replace("Inspector 01", esc(rater_id))
    page = page.replace("Reviewer Status", f"{p['done']}/{p['total']} Rated")

    page = page.replace(">124<", f">{p['total']}<")
    page = page.replace(">98<", f">{p['done']}<")
    page = page.replace(">26<", f">{p['remaining']}<")
    page = page.replace(
        "艺术之眼，审时度势。今日共有三项核心任务等待您的终极鉴别。保持专注，让每一笔触都归其位。",
        f"已完成 {p['done']} / {p['total']} 项评分（{pct}%），剩余 {p['remaining']} 项待评。",
    )

    page = re.sub(
        r"<!-- Recent Seals \(Evaluations\) -->.*?</section>",
        "",
        page,
        count=1,
        flags=re.DOTALL,
    )

    page = apply_top_nav(page, "profile", rater_id)

    # Clean footer: remove 资源/规范指南/墨迹库/法律/隐私协议/版权声明 links
    page = re.sub(
        r'<div class="flex gap-16 font-label-sm text-label-sm">.*?</div>\s*</div>',
        '</div>',
        page,
        count=1,
        flags=re.DOTALL,
    )

    page = page.replace("</body>", f"""
<script>
document.querySelectorAll('button').forEach((button) => {{
  const text = button.innerText || '';
  if (text.includes('开始') || text.includes('Begin') || text.includes('继续') || text.includes('Continue') || text.includes('Start')) button.onclick = () => location.href = '/rate';
}});
</script>
</body>""")
    return page


def render_done(rater_id: str = "") -> str:
    page = ref_page("rate")
    # Replace left sidebar with thumbnail list
    page = re.sub(
        r'<aside class="hidden md:flex h-screen w-64 sticky top-20.*?</aside>',
        render_thumbnail_sidebar(rater_id, ""),
        page,
        count=1,
        flags=re.DOTALL,
    )
    page = page.replace("__STYLE_HEADER__", "")
    page = page.replace("__PROMPT_BOX__", "")
    page = page.replace("__COMMENT_VALUE__", "")
    page = page.replace("__PREV_BUTTON__", "")

    # Build the completion page content
    done_content = f"""<div class="max-w-2xl mx-auto text-center py-16">
<h2 class="font-headline-md text-headline-md text-primary mb-6">您已完成全部图像评分。</h2>
<p class="font-body-lg text-body-lg text-primary mb-2">感谢您的参与和支持！</p>
<p class="font-body-md text-body-md text-on-surface-variant mb-12">本次评分结果将用于中国传统视觉风格 T2I 图像生成评价研究。<br/>数据将匿名处理，仅用于研究分析。</p>
<div class="max-w-md mx-auto text-left">
<p class="font-label-sm text-label-sm text-secondary mb-2">可选反馈</p>
<form method="post" action="/feedback">
<textarea class="w-full min-h-32 bg-transparent border border-outline-variant rounded-sm p-3 font-body-md text-body-md focus:ring-0 focus:border-primary mb-6" name="content" placeholder="如有任何建议或想法，请在此留言..."></textarea>
<button class="w-full py-4 bg-primary text-on-primary font-headline-md hover:opacity-90 transition-all" type="submit">提交反馈并结束</button>
</form>
</div>
</div>"""

    # Replace the main content area (keep sidebar, replace everything between sidebar and rating form)
    page = re.sub(
        r'(<!-- Main Content Canvas -->).*?(<!-- Right Rating Sidebar -->)',
        r'\1' + done_content + r'\2',
        page,
        count=1,
        flags=re.DOTALL,
    )
    # Remove the rating form sidebar
    page = re.sub(
        r'<!-- Right Rating Sidebar -->.*?</aside>',
        '',
        page,
        count=1,
        flags=re.DOTALL,
    )
    page = apply_top_nav(page, "rate", rater_id)
    return page


def replace_radio_names(page: str, prefilled_scores: dict[str, int] | None = None) -> str:
    mapping = {
        "style": "style_consistency_score",
        "accuracy": "element_accuracy_score",
        "propriety": "error_control_score",
        "overall": "overall_score",
    }
    page = page.replace(" checked=\"\"", "")
    for old, new in mapping.items():
        for score in range(1, 6):
            checked_str = ""
            if prefilled_scores and prefilled_scores.get(new) == score:
                checked_str = " checked"
            page = page.replace(
                f'id="{old[0]}{score}" name="{old}" type="radio"',
                f'id="{old[0]}{score}" name="{new}" value="{score}" type="radio"{checked_str} required',
            )
    return page


def render_error_checklist() -> str:
    return "\n".join(
        f"""<label class="flex items-center gap-3 cursor-pointer">
<input class="w-5 h-5 border-2 border-outline-variant rounded-sm text-primary focus:ring-0" name="error_tags" value="{esc(tag)}" type="checkbox"/>
<span class="font-body-md">{esc(tag)}</span>
</label>"""
        for tag in ERROR_TAGS
    )


def render_rate(rater_id: str, message: str = "", show_prev: bool = False, image_id: str | None = None) -> str:
    is_rated = False
    rated_error_tags: list[str] = []

    if show_prev:
        item = prev_item(rater_id)
        if item is None:
            item = next_item(rater_id)
            show_prev = False
    elif image_id:
        item = get_item_with_score(image_id, rater_id)
        if item is None:
            item = next_item(rater_id)
        elif item["style_consistency_score"] is not None:
            is_rated = True
            if item["prev_error_tags"]:
                rated_error_tags = [t.strip() for t in item["prev_error_tags"].split("；") if t.strip()]
    else:
        item = next_item(rater_id)

    if item is None:
        return render_done(rater_id)

    current_image_id = item["image_id"]
    page = ref_page("rate")
    image_src = f"/image/{esc(current_image_id)}.png"

    # Replace left sidebar with thumbnail list
    page = re.sub(
        r'<aside class="hidden md:flex h-screen w-64 sticky top-20.*?</aside>',
        render_thumbnail_sidebar(rater_id, current_image_id),
        page,
        count=1,
        flags=re.DOTALL,
    )

    page = page.replace("Inspector 01", esc(rater_id))

    prompt_text = real_prompt_for_image(current_image_id, item["prompt_text"])
    header_style_text = f"{esc(item['target_style'])} · {esc(item['prompt_level'])} · {esc(current_image_id)}"
    if show_prev:
        header_style_text += " (正在修改上一张已评分图片)"
    elif is_rated:
        header_style_text += " (已评分，可修改)"

    page = page.replace("__STYLE_HEADER__", header_style_text)

    # Inject the exact generation prompt into the right sidebar above rating form.
    prompt_box = f"""<div class="mb-4 p-3 bg-surface-container-high border border-outline-variant/30 rounded-sm">
<p class="font-label-sm text-label-sm text-secondary mb-1">目标风格</p>
<p class="font-body-md font-semibold mb-2">{esc(item['target_style'])} · {esc(item['prompt_level'])}</p>
<p class="font-label-sm text-label-sm text-secondary mb-1">提示词</p>
<p class="font-body-md text-body-md text-on-surface-variant">{esc(prompt_text)}</p>
</div>"""
    page = page.replace("__PROMPT_BOX__", prompt_box)

    page = page.replace(
        'src="https://lh3.googleusercontent.com/aida-public/AB6AXuBleeff-Ofj14uKDDtSIqCjnAZkHlxT8cOPI1ueeJOIbGN_5tVFatJMwRytlB_MADW3S6NQrpxyDtbu9dBogXaLm_coFnle7UMkC14J_JJwzEq-kWv2jdlq6uY2V1UyqbTH1p_0qJJN-mc34w213OwossAsFOAZH6F0rNtGuzVWWjX7PrPKwx6a3Q5TOipMht_B3xDEKUeTKo-I9qW-yPjMd0WkGJItT-Ws71DQ3UurW81ejjeI4FItVOTTKmOGJUSeq6oFQvmYI4Y"',
        f'src="{image_src}" onerror="this.alt=\'Image not available: {esc(current_image_id)}.png\'"',
    )
    page = page.replace('<form class="flex flex-col gap-12" id="ratingForm">', f'<form class="flex flex-col gap-12" id="ratingForm" method="post" action="/rate"><input type="hidden" name="image_id" value="{esc(current_image_id)}">')

    prefilled = None
    if show_prev or is_rated:
        prefilled = {
            "style_consistency_score": item["style_consistency_score"],
            "element_accuracy_score": item["element_accuracy_score"],
            "error_control_score": item["error_control_score"],
            "overall_score": item["overall_score"],
        }
    page = replace_radio_names(page, prefilled)

    comment_val = ""
    if show_prev or is_rated:
        comment_val = esc(item["comment"] or "")
    page = page.replace("__COMMENT_VALUE__", comment_val)
    page = page.replace("comment value", comment_val)

    # Pre-check error tags if revisiting a rated image
    if rated_error_tags:
        for tag in rated_error_tags:
            page = page.replace(
                f'value="{esc(tag)}" type="checkbox"',
                f'value="{esc(tag)}" type="checkbox" checked',
            )

    if show_prev:
        prev_btn_html = '<button class="px-8 py-3 text-primary hover:text-primary-dark transition-colors border border-primary rounded-sm font-label-sm" type="button" onclick="location.href=\'/rate\'">返回当前</button>'
    else:
        prev_btn_html = '<button class="px-8 py-3 text-primary hover:text-primary-dark transition-colors border border-primary rounded-sm font-label-sm" type="button" onclick="location.href=\'/rate?skip=1\'">下一张图片</button>'
    page = page.replace("__PREV_BUTTON__", prev_btn_html)

    if message:
        page = page.replace(
            '<!-- Content Header Area -->',
            f'<div class="max-w-3xl mx-auto mb-4 flex items-center justify-center gap-3 py-2 px-6 bg-surface-container-high rounded-full"><span class="font-label-sm text-label-sm">{esc(message)}</span></div>\n<!-- Content Header Area -->',
        )
    page = page.replace(
        "document.getElementById('ratingForm').addEventListener('submit', (e) => {",
        "document.getElementById('ratingForm').addEventListener('submit', (e) => {\n            return true;\n        });\n        document.getElementById('ratingForm_unused')?.addEventListener('submit', (e) => {",
    )

    page = apply_top_nav(page, "rate", rater_id)
    page = page.replace("Return to Studio / 返回工作室", "Return to Studio / 返回工作室")
    return page


def render_admin(rater_id: str | None, imported: int | None = None) -> str:
    p = progress_for()
    page = ref_page("admin")
    page = page.replace("Inspector 01", esc(rater_id or "Admin"))
    page = page.replace("监控当前评分进程，分析评审质量与进度，管理核心数据流转。", f"监控当前评分进程。Items {p['total']} · Scores {p['done']} · Raters {p['raters']}。")
    if imported is not None:
        page = page.replace("评分管理概览", f"评分管理概览 · Imported {imported}")

    page = apply_top_nav(page, "admin", rater_id)

    # Inject feedback list
    with connect() as conn:
        fb_rows = conn.execute(
            "select rater_id, content, created_at from feedback order by created_at desc"
        ).fetchall()
    if fb_rows:
        fb_html = '<section class="mt-12"><h3 class="font-headline-md text-primary mb-4">评审者反馈</h3><div class="space-y-4">'
        for fb in fb_rows:
            fb_html += f"""<div class="p-4 bg-surface-container-low border border-outline-variant/20">
<p class="font-label-sm text-label-sm text-secondary mb-1">{esc(fb['rater_id'])} · {esc(fb['created_at'][:19])}</p>
<p class="font-body-md text-body-md">{esc(fb['content'])}</p>
</div>"""
        fb_html += '</div></section>'
        page = page.replace("<!-- Footer Seal Decoration -->", fb_html + "\n<!-- Footer Seal Decoration -->")

    page = page.replace("</body>", """
<script>
document.querySelectorAll('button').forEach((button) => {
  const text = button.innerText || '';
  if (text.includes('Export') || text.includes('导出')) button.onclick = () => location.href = '/admin/export';
  if (text.includes('Import') || text.includes('导入')) button.onclick = () => fetch('/admin/import', {method:'POST'}).then(()=>location.reload());
});
</script>
</body>""")
    return page


class App(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def rater_id(self) -> str | None:
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        morsel = jar.get("rater_id")
        return morsel.value if morsel else None

    def send_html(self, body: str, status: int = 200, headers: dict[str, str] | None = None, set_cookie: str | None = None) -> None:
        body = localize_zh(body)
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str, headers: dict[str, str] | None = None, set_cookies: list[str] | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        for c in (set_cookies or []):
            self.send_header("Set-Cookie", c)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def require_login(self) -> str | None:
        rater = self.rater_id()
        if not rater:
            self.redirect("/login")
            return None
        return rater

    def read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        return parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        rater = self.rater_id()
        if path == "/":
            self.redirect("/profile" if rater else "/login")
        elif path == "/login":
            self.send_html(render_login())
        elif path == "/logout":
            self.redirect("/login", set_cookies=[
                "rater_id=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
                "current_image_id=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
            ])
        elif path == "/profile":
            if (r := self.require_login()):
                self.send_html(render_profile(r))
        elif path == "/rate":
            if (r := self.require_login()):
                query = parse_qs(urlparse(self.path).query)
                show_prev = "prev" in query
                skip_current = "skip" in query
                req_image_id = (query.get("image_id", [""])[0] or "").strip() or None
                cookie_jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
                cookie_image_id = (cookie_jar.get("current_image_id").value if cookie_jar.get("current_image_id") else None)

                # Priority: explicit image_id param > cookie (unrated only) > random next.
                # Pick once here and pass the exact image into render_rate so image, prompt,
                # and current_image_id cookie stay aligned.
                message = ""
                target_image_id = None

                if show_prev:
                    target_image_id = None
                elif skip_current:
                    item = next_item(r, exclude_image_id=cookie_image_id)
                    if item:
                        target_image_id = item["image_id"]
                elif req_image_id:
                    target_image_id = req_image_id
                    if get_item_with_score(req_image_id, r) is None:
                        message = f"图片 {req_image_id} 不存在，已切换至下一张。"
                        target_image_id = None
                elif cookie_image_id:
                    check = get_item_with_score(cookie_image_id, r)
                    if check and check["style_consistency_score"] is None:
                        target_image_id = cookie_image_id

                set_cookie = None
                if not show_prev:
                    item = None
                    if target_image_id:
                        item = get_item_with_score(target_image_id, r)
                    if item is None:
                        item = next_item(r)
                    if item:
                        target_image_id = item["image_id"]
                        c = cookies.SimpleCookie()
                        c["current_image_id"] = item["image_id"]
                        c["current_image_id"]["path"] = "/"
                        c["current_image_id"]["httponly"] = True
                        c["current_image_id"]["samesite"] = "Lax"
                        set_cookie = c.output(header="").strip()

                self.send_html(render_rate(r, message=message, show_prev=show_prev, image_id=target_image_id), set_cookie=set_cookie)
        elif path == "/admin":
            if not is_admin(rater):
                self.send_error(403, "Admin only")
                return
            self.send_html(render_admin(rater))
        elif path == "/admin/export":
            if not is_admin(rater):
                self.send_error(403, "Admin only")
                return
            export_human_scores()
            export_ratings()
            data = HUMAN_SCORES_CSV.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=human_scores.csv")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path.startswith("/image/"):
            self.serve_image(path.removeprefix("/image/"))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        form = self.read_form()
        if path == "/login":
            rater_id = (form.get("rater_id", [""])[0] or "").strip()
            password = (form.get("password", [""])[0] or "").strip()
            if not rater_id:
                self.send_html(render_login("评审者编号不能为空"), 400)
                return
            if not password:
                self.send_html(render_login("通行令牌不能为空"), 400)
                return
            with connect() as conn:
                row = conn.execute(
                    "select password_hash from raters where rater_id = ?", (rater_id,)
                ).fetchone()
                if not row:
                    self.send_html(render_login("评审者编号不存在"), 401)
                    return
                if not row["password_hash"] or hash_password(password) != row["password_hash"]:
                    self.send_html(render_login("通行令牌错误"), 401)
                    return
            cookie_jar = cookies.SimpleCookie()
            cookie_jar["rater_id"] = rater_id
            cookie_jar["rater_id"]["path"] = "/"
            cookie_jar["rater_id"]["httponly"] = True
            cookie_jar["rater_id"]["samesite"] = "Lax"
            self.redirect("/profile", set_cookies=[cookie_jar.output(header="").strip()])
        elif path == "/rate":
            if (r := self.require_login()):
                self.submit_rating(r, form)
        elif path == "/feedback":
            if (r := self.require_login()):
                content = (form.get("content", [""])[0] or "").strip()
                if content:
                    with connect() as conn:
                        conn.execute(
                            "insert into feedback (rater_id, content, created_at) values (?, ?, ?)",
                            (r, content, now_iso()),
                        )
                self.send_html(render_done(r).replace("可选反馈", "感谢您的反馈！"))
        elif path == "/admin/import":
            if not is_admin(self.rater_id()):
                self.send_error(403, "Admin only")
                return
            self.send_html(render_admin(self.rater_id(), imported=import_rating_items()))
        else:
            self.send_error(404)

    def submit_rating(self, rater_id: str, form: dict[str, list[str]]) -> None:
        image_id = (form.get("image_id", [""])[0] or "").strip()
        field_names = [
            "style_consistency_score",
            "element_accuracy_score",
            "error_control_score",
            "overall_score",
        ]
        values: dict[str, int] = {}
        for name in field_names:
            raw = (form.get(name, [""])[0] or "").strip()
            if raw not in {"1", "2", "3", "4", "5"}:
                self.send_html(render_rate(rater_id, "每个维度都需选择 1-5 分"), 400)
                return
            values[name] = int(raw)
        rating_id = f"R{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3)}"
        rated_at = now_iso()
        error_tags = "；".join(form.get("error_tags", []))
        comment = (form.get("comment", [""])[0] or "").strip()
        try:
            with connect() as conn:
                conn.execute(
                    """
                    insert into human_scores (
                        rating_id, image_id, rater_id, rated_at,
                        style_consistency_score, element_accuracy_score, error_control_score,
                        overall_score, error_tags, comment
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(image_id, rater_id) do update set
                        rated_at=excluded.rated_at,
                        style_consistency_score=excluded.style_consistency_score,
                        element_accuracy_score=excluded.element_accuracy_score,
                        error_control_score=excluded.error_control_score,
                        overall_score=excluded.overall_score,
                        error_tags=excluded.error_tags,
                        comment=excluded.comment
                    """,
                    (
                        rating_id,
                        image_id,
                        rater_id,
                        rated_at,
                        values["style_consistency_score"],
                        values["element_accuracy_score"],
                        values["error_control_score"],
                        values["overall_score"],
                        error_tags,
                        comment,
                    ),
                )
        except sqlite3.IntegrityError:
            self.send_html(render_rate(rater_id, "这张图已评分，已切换下一张。"))
            return
        export_human_scores()
        export_ratings()
        try:
            upsert_supabase_rating(
                supabase_rating_payload(
                    rating_id=rating_id,
                    image_id=image_id,
                    rater_id=rater_id,
                    rated_at=rated_at,
                    values=values,
                    error_tags=error_tags,
                    comment=comment,
                )
            )
        except Exception as exc:
            self.send_html(
                render_rate(
                    rater_id,
                    f"本地已保存，但 Supabase 同步失败：{exc}",
                    image_id=image_id,
                ),
                502,
            )
            return
        self.redirect("/rate")

    def serve_image(self, filename: str) -> None:
        image_id = filename
        if image_id.endswith(".png"):
            image_id = image_id[:-4]
        with connect() as conn:
            row = conn.execute("select blind_filename from rating_items where image_id = ?", (image_id,)).fetchone()
        if not row:
            self.send_error(404)
            return
        raw_image_path = row["blind_filename"]
        path_in_root = (PROJECT_ROOT / raw_image_path).resolve()
        path_in_blind = (BLIND_IMAGE_DIR / raw_image_path).resolve()
        
        if path_in_root.exists() and path_in_root.is_file():
            safe_path = path_in_root
        elif path_in_blind.exists() and path_in_blind.is_file():
            safe_path = path_in_blind
        else:
            safe_path = path_in_root

        if not safe_path.is_relative_to(PROJECT_ROOT):
            self.send_error(403)
            return
        if not safe_path.exists() or not safe_path.is_file():
            self.send_error(404)
            return
        data = safe_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(safe_path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), App)
    print(f"SumiRate running at http://{HOST}:{PORT}/")
    print("UI source: web/reference/stitch_traditional_t2i_style_evaluator/*/code.html")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
