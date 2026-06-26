"""SumiRate subjective rating app, using the provided reference UI verbatim.

The pages are rendered from web/reference/.../code.html and only receive small
server-side substitutions for data, form actions, and navigation. The app reads
only rating_items.csv and images/blind/, and writes human_scores.csv/app.db.
"""

from __future__ import annotations

import csv
import html
import mimetypes
import secrets
import sqlite3
from datetime import datetime, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"
DATA_DIR = PROJECT_ROOT / "data"
BLIND_IMAGE_DIR = PROJECT_ROOT / "images" / "blind"
REF_DIR = WEB_DIR / "reference" / "stitch_traditional_t2i_style_evaluator"
RATING_ITEMS_CSV = DATA_DIR / "rating_items.csv"
HUMAN_SCORES_CSV = DATA_DIR / "human_scores.csv"
DB_PATH = WEB_DIR / "app.db"

HOST = "127.0.0.1"
PORT = 8063

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
        "Judge by consistency, not preference | 随物婉转，与心徘徊": "请根据目标风格与提示语评价，不按个人偏好打分",
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
    dimension_hints = {
        '<span class="font-body-md font-semibold">形式风格一致性</span>':
            '<span><span class="font-body-md font-semibold">形式风格一致性</span><span class="block text-xs text-secondary mt-1 font-normal">看图像整体是否符合目标传统视觉风格的形式特征。</span></span>',
        '<span class="font-body-md font-semibold">文化元素准确性</span>':
            '<span><span class="font-body-md font-semibold">文化元素准确性</span><span class="block text-xs text-secondary mt-1 font-normal">看人物、器物、纹样、场景等是否符合提示语要求。</span></span>',
        '<span class="font-body-md font-semibold">文化语境得体性</span>':
            '<span><span class="font-body-md font-semibold">文化语境得体性</span><span class="block text-xs text-secondary mt-1 font-normal">看是否存在现代化漂移、时代错配或文化混搭。</span></span>',
        '<span class="font-body-md font-semibold">整体评分</span>':
            '<span><span class="font-body-md font-semibold">整体评分</span><span class="block text-xs text-secondary mt-1 font-normal">综合前三项判断，不只是评价图片是否好看。</span></span>',
    }
    for old, new in dimension_hints.items():
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
            create table if not exists human_scores (
                rating_id text primary key,
                image_id text not null,
                rater_id text not null,
                rated_at text not null,
                style_fidelity integer not null,
                element_accuracy integer not null,
                context_appropriateness integer not null,
                overall_score integer not null,
                error_tags text,
                comment text,
                unique(image_id, rater_id)
            );
            """
        )
    import_rating_items()
    export_human_scores()


def import_rating_items() -> int:
    if not RATING_ITEMS_CSV.exists():
        return 0
    allowed = {
        "image_id",
        "blind_filename",
        "target_style",
        "prompt_level",
        "prompt_text",
        "expected_elements",
        "forbidden_elements",
    }
    count = 0
    with RATING_ITEMS_CSV.open(newline="", encoding="utf-8") as f, connect() as conn:
        for row in csv.DictReader(f):
            if not row.get("image_id") or not row.get("blind_filename"):
                continue
            clean = {k: row.get(k, "") for k in allowed}
            conn.execute(
                """
                insert into rating_items (
                    image_id, blind_filename, target_style, prompt_level,
                    prompt_text, expected_elements, forbidden_elements
                ) values (
                    :image_id, :blind_filename, :target_style, :prompt_level,
                    :prompt_text, :expected_elements, :forbidden_elements
                )
                on conflict(image_id) do update set
                    blind_filename=excluded.blind_filename,
                    target_style=excluded.target_style,
                    prompt_level=excluded.prompt_level,
                    prompt_text=excluded.prompt_text,
                    expected_elements=excluded.expected_elements,
                    forbidden_elements=excluded.forbidden_elements
                """,
                clean,
            )
            count += 1
    return count


def export_human_scores() -> None:
    with connect() as conn:
        rows = conn.execute(
            """
            select rating_id, image_id, rater_id, rated_at,
                   style_fidelity, element_accuracy, context_appropriateness,
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
                "style_fidelity",
                "element_accuracy",
                "context_appropriateness",
                "overall_score",
                "error_tags",
                "comment",
            ]
        )
        for row in rows:
            writer.writerow([row[k] for k in row.keys()])


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


def next_item(rater_id: str) -> sqlite3.Row | None:
    with connect() as conn:
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


def render_login(error: str = "") -> str:
    page = ref_page("login")
    page = page.replace(
        '<form action="#" class="space-y-8" onsubmit="return false;">',
        '<form method="post" action="/login" class="space-y-8">',
    )
    page = page.replace('id="reviewer-id" placeholder="请输入审查者编号" type="text"', 'id="reviewer-id" name="rater_id" placeholder="请输入审查者编号" type="text" required')
    page = page.replace('id="access-token" placeholder="••••••••" type="password"', 'id="access-token" name="password" placeholder="••••••••" type="password"')
    page = page.replace('href="#">申请权限</a>', 'href="/profile">申请权限</a>')
    page = page.replace('href="#">故障申报</a>', 'href="/admin">故障申报</a>')
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
    page = page.replace("<button", "<button onclick=\"location.href='/rate'\"", 1)
    page = page.replace("Logout</button>", "Logout</button>")
    page = page.replace('href="#">', 'href="/profile">', 1)
    page = page.replace('href="#">Gallery</a>', 'href="/rate">Gallery</a>')
    page = page.replace('href="#">Archive</a>', 'href="/admin">Archive</a>')
    page = page.replace("</body>", f"""
<script>
document.querySelectorAll('button').forEach((button) => {{
  const text = button.innerText || '';
  if (text.includes('开始') || text.includes('Start')) button.onclick = () => location.href = '/rate';
  if (text.includes('Logout')) button.onclick = () => location.href = '/logout';
}});
</script>
<div style="position:fixed;right:24px;bottom:24px;background:#f4f4ef;border:1px solid #c4c7c7;padding:12px 16px;font-family:JetBrains Mono,monospace;font-size:12px;z-index:80;">
{p['done']} / {p['total']} completed · {pct}%
</div>
</body>""")
    return page


def render_done() -> str:
    page = ref_page("rate")
    page = page.replace("High-Dynasty Ink Landscape (宋代水墨山水)", "评分已完成")
    page = page.replace('"Mountains shrouded in mist, lone pine on the ridge, distant boats on silent water, expressive brushwork."', "当前没有未评分图像。")
    page = page.replace("Apply Seal / 落款评定", "Return / 返回主页")
    page = page.replace("</body>", "<script>document.getElementById('ratingForm').onsubmit=(e)=>{e.preventDefault();location.href='/profile';}</script></body>")
    return page


def replace_radio_names(page: str) -> str:
    mapping = {
        "style": "style_fidelity",
        "accuracy": "element_accuracy",
        "propriety": "context_appropriateness",
        "overall": "overall_score",
    }
    page = page.replace(" checked=\"\"", "")
    for old, new in mapping.items():
        for score in range(1, 6):
            page = page.replace(
                f'id="{old[0]}{score}" name="{old}" type="radio"',
                f'id="{old[0]}{score}" name="{new}" value="{score}" type="radio" required',
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


def render_rate(rater_id: str, message: str = "") -> str:
    item = next_item(rater_id)
    if item is None:
        return render_done()

    page = ref_page("rate")
    image_src = f"/image/{esc(item['blind_filename'])}"
    page = page.replace("Inspector 01", esc(rater_id))
    page = page.replace("High-Dynasty Ink Landscape (宋代水墨山水)", f"{esc(item['target_style'])} · {esc(item['prompt_level'])} · {esc(item['image_id'])}")
    prompt_context = (
        f'{esc(item["prompt_text"])}'
        f'<br><br><span class="font-label-sm text-label-sm text-secondary uppercase tracking-widest">应出现元素</span><br>'
        f'{esc(item["expected_elements"])}'
        f'<br><br><span class="font-label-sm text-label-sm text-secondary uppercase tracking-widest">应避免元素</span><br>'
        f'{esc(item["forbidden_elements"])}'
    )
    page = page.replace('"Mountains shrouded in mist, lone pine on the ridge, distant boats on silent water, expressive brushwork."', prompt_context)
    page = page.replace(
        'src="https://lh3.googleusercontent.com/aida-public/AB6AXuBleeff-Ofj14uKDDtSIqCjnAZkHlxT8cOPI1ueeJOIbGN_5tVFatJMwRytlB_MADW3S6NQrpxyDtbu9dBogXaLm_coFnle7UMkC14J_JJwzEq-kWv2jdlq6uY2V1UyqbTH1p_0qJJN-mc34w213OwossAsFOAZH6F0rNtGuzVWWjX7PrPKwx6a3Q5TOipMht_B3xDEKUeTKo-I9qW-yPjMd0WkGJItT-Ws71DQ3UurW81ejjeI4FItVOTTKmOGJUSeq6oFQvmYI4Y"',
        f'src="{image_src}" onerror="this.alt=\'Image not available: {esc(item["blind_filename"])}\'"',
    )
    page = page.replace('<form class="flex flex-col gap-12" id="ratingForm">', f'<form class="flex flex-col gap-12" id="ratingForm" method="post" action="/rate"><input type="hidden" name="image_id" value="{esc(item["image_id"])}">')
    page = replace_radio_names(page)
    page = page.replace("Accuracy / 意境准确性", "Accuracy / 元素准确性")
    page = page.replace("Propriety / 笔墨得体", "Propriety / 语境得体")
    page = page.replace("Overall / 综合感官", "Overall / 整体评分")
    start = page.find('<div class="grid grid-cols-1 gap-4">')
    end = page.find("</div>\n</div>\n<!-- Final Action -->", start)
    if start != -1 and end != -1:
        page = page[:start] + '<div class="grid grid-cols-1 gap-4">\n' + render_error_checklist() + page[end:]
    page = page.replace(
        '<button class="px-8 py-3 text-on-surface-variant hover:text-error transition-colors border-b border-transparent hover:border-error">Skip / 跳过</button>',
        '<button class="px-8 py-3 text-on-surface-variant opacity-50 cursor-not-allowed border-b border-transparent" type="button" title="MVP 阶段暂不支持跳过，避免样本缺失">暂不支持跳过</button>',
    )
    page = page.replace(
        '<!-- Final Action -->',
        """<!-- Comment Box -->
<div class="pt-8 border-t border-outline-variant/30">
<h4 class="font-label-sm text-secondary uppercase tracking-widest mb-4">可选评语</h4>
<textarea class="w-full min-h-24 bg-transparent border border-outline-variant rounded-sm p-3 font-body-md text-body-md focus:ring-0 focus:border-primary" name="comment" placeholder="可选：说明主要问题，例如对象错误、风格混搭、现代插画化等"></textarea>
</div>
<!-- Final Action -->""",
    )
    if message:
        page = page.replace(
            '<div class="max-w-3xl mx-auto mb-12 flex items-center justify-center gap-3 py-2 px-6 bg-surface-container-high rounded-full">',
            f'<div class="max-w-3xl mx-auto mb-4 flex items-center justify-center gap-3 py-2 px-6 bg-surface-container-high rounded-full"><span class="font-label-sm text-label-sm">{esc(message)}</span></div><div class="max-w-3xl mx-auto mb-12 flex items-center justify-center gap-3 py-2 px-6 bg-surface-container-high rounded-full">',
        )
    page = page.replace(
        "document.getElementById('ratingForm').addEventListener('submit', (e) => {",
        "document.getElementById('ratingForm').addEventListener('submit', (e) => {\n            return true;\n        });\n        document.getElementById('ratingForm_unused')?.addEventListener('submit', (e) => {",
    )
    page = page.replace('href="#">Dashboard</a>', 'href="/profile">Dashboard</a>')
    page = page.replace('href="#">Gallery</a>', 'href="/rate">Gallery</a>')
    page = page.replace('href="#">Archive</a>', 'href="/admin">Archive</a>')
    page = page.replace("Return to Studio / 返回工作室", "Return to Studio / 返回工作室")
    page = page.replace("</body>", "<script>document.querySelectorAll('button').forEach(b=>{if((b.innerText||'').includes('Logout')) b.onclick=()=>location.href='/logout';});</script></body>")
    return page


def render_admin(rater_id: str | None, imported: int | None = None) -> str:
    p = progress_for()
    page = ref_page("admin")
    page = page.replace("Inspector 01", esc(rater_id or "Admin"))
    page = page.replace("监控当前评分进程，分析评审质量与进度，管理核心数据流转。", f"监控当前评分进程。Items {p['total']} · Scores {p['done']} · Raters {p['raters']}。")
    if imported is not None:
        page = page.replace("评分管理概览", f"评分管理概览 · Imported {imported}")
    page = page.replace('href="#">Dashboard</a>', 'href="/profile">Dashboard</a>')
    page = page.replace('href="#">Gallery</a>', 'href="/rate">Gallery</a>')
    page = page.replace('href="#">Archive</a>', 'href="/admin">Archive</a>')
    page = page.replace("</body>", """
<script>
document.querySelectorAll('button').forEach((button) => {
  const text = button.innerText || '';
  if (text.includes('Logout')) button.onclick = () => location.href = '/logout';
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

    def send_html(self, body: str, status: int = 200, headers: dict[str, str] | None = None) -> None:
        body = localize_zh(body)
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
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
            self.redirect("/login", {"Set-Cookie": "rater_id=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})
        elif path == "/profile":
            if (r := self.require_login()):
                self.send_html(render_profile(r))
        elif path == "/rate":
            if (r := self.require_login()):
                self.send_html(render_rate(r))
        elif path == "/admin":
            self.send_html(render_admin(rater))
        elif path == "/admin/export":
            export_human_scores()
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
            if not rater_id:
                self.send_html(render_login("Reviewer ID 不能为空"), 400)
                return
            with connect() as conn:
                conn.execute(
                    "insert or ignore into raters (rater_id, display_name, created_at) values (?, ?, ?)",
                    (rater_id, rater_id, now_iso()),
                )
            jar = cookies.SimpleCookie()
            jar["rater_id"] = rater_id
            jar["rater_id"]["path"] = "/"
            jar["rater_id"]["httponly"] = True
            jar["rater_id"]["samesite"] = "Lax"
            self.redirect("/profile", {"Set-Cookie": jar.output(header="").strip()})
        elif path == "/rate":
            if (r := self.require_login()):
                self.submit_rating(r, form)
        elif path == "/admin/import":
            self.send_html(render_admin(self.rater_id(), imported=import_rating_items()))
        else:
            self.send_error(404)

    def submit_rating(self, rater_id: str, form: dict[str, list[str]]) -> None:
        image_id = (form.get("image_id", [""])[0] or "").strip()
        fields = ["style_fidelity", "element_accuracy", "context_appropriateness", "overall_score"]
        values: dict[str, int] = {}
        for field in fields:
            raw = (form.get(field, [""])[0] or "").strip()
            if raw not in {"1", "2", "3", "4", "5"}:
                self.send_html(render_rate(rater_id, "四项评分均需选择 1-5 分"), 400)
                return
            values[field] = int(raw)
        rating_id = f"R{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3)}"
        try:
            with connect() as conn:
                conn.execute(
                    """
                    insert into human_scores (
                        rating_id, image_id, rater_id, rated_at,
                        style_fidelity, element_accuracy, context_appropriateness,
                        overall_score, error_tags, comment
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rating_id,
                        image_id,
                        rater_id,
                        now_iso(),
                        values["style_fidelity"],
                        values["element_accuracy"],
                        values["context_appropriateness"],
                        values["overall_score"],
                        "；".join(form.get("error_tags", [])),
                        (form.get("comment", [""])[0] or "").strip(),
                    ),
                )
        except sqlite3.IntegrityError:
            self.send_html(render_rate(rater_id, "这张图已评分，已切换下一张。"))
            return
        export_human_scores()
        self.redirect("/rate")

    def serve_image(self, filename: str) -> None:
        path = BLIND_IMAGE_DIR / Path(filename).name
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
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
