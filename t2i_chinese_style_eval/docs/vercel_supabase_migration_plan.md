# SumiRate Vercel + Supabase 迁移方案

## 目标

把当前 SumiRate 从“Python 常驻服务 + 本地 SQLite/CSV + 本地图片目录”的形态，迁移为：

- Vercel 负责网页、登录、评分界面、管理界面和后端接口。
- Supabase 负责结构化数据、评分结果持久化和盲评图片存储。

迁移完成后，正式评审不再依赖 `web/app.db`、`data/human_scores.csv`、`data/ratings.csv` 或本地 `/image/...` 路由。

## 当前状态

当前可运行版本仍是：

- 入口：`web/app.py`
- 本地数据库：`web/app.db`
- 本地导出：`data/human_scores.csv`、`data/ratings.csv`
- 本地图片：`images/blind/`
- Supabase 已有表：`prompts`、`models`、`generation_jobs`、`rating_items`、`reviewers`、`ratings`、`feedback`

当前版本已经能把评分同步到 Supabase，但仍然先写本地 SQLite/CSV，再同步 Supabase。这个模式不适合 Vercel 作为正式运行环境。

## 迁移原则

1. 不直接拆掉当前 Python 版本。
2. 新增一个 Vercel 版本目录，例如 `vercel-app/` 或 `app/`。
3. Supabase 成为正式数据源。
4. Vercel 不保存评分文件，不写 SQLite。
5. 图片只上传盲评图片，不上传 raw 原图。
6. 前端和 API 都不能暴露 `SUPABASE_SERVICE_ROLE_KEY`。

## 推荐项目结构

建议新增：

```text
t2i_chinese_style_eval/
  vercel-app/
    package.json
    next.config.js
    src/
      app/
        login/
        profile/
        rate/
        admin/
        api/
          login/
          logout/
          session/
          rating-items/
          ratings/
          feedback/
      lib/
        supabaseAdmin.ts
        auth.ts
        rating.ts
      components/
        RatingForm.tsx
        PromptBox.tsx
        ImagePanel.tsx
```

推荐使用 Next.js App Router。原因是 Vercel 对 Next.js 支持最稳定，页面和 API 路由可以放在同一个项目里。

## Supabase Storage

新建 Storage bucket：

```text
rating-images
```

建议路径：

```text
mvp_2026_06/blind/img_0001.jpg
mvp_2026_06/blind/img_0002.png
...
```

只上传 `images/blind/` 里的 48 张盲评图，不上传 `images/raw/`。

图片访问方式建议先用 public bucket，降低部署复杂度。后期如果要更严格控制访问，再改成 signed URL。

## 表结构补充

当前 `rating_items` 已有：

- `blind_filename`
- `blind_image_path`

建议新增一个字段，明确记录 Supabase Storage 路径：

```sql
alter table rating_items
add column if not exists storage_path text;
```

也可以复用 `blind_image_path`，但长期看单独加 `storage_path` 更清楚。

建议 `storage_path` 示例：

```text
mvp_2026_06/blind/img_0001.jpg
```

前端拿到 `storage_path` 后，由 Vercel API 生成 public URL 或 signed URL。

## 登录与权限

当前 reviewers 表已经包含：

- `reviewer_id`
- `display_name`
- `password_hash`
- `role`
- `active`

Vercel 版本登录流程：

1. 用户输入 `reviewer_id` 和密码。
2. Vercel API 用 service role 查询 `reviewers`。
3. 后端校验 SHA-256 密码 hash。
4. 成功后写入 httpOnly session cookie。
5. 页面根据 session 判断是否能访问 `/rate`、`/profile`、`/admin`。

注意：

- 不使用 Supabase Auth，先沿用现有账号体系。
- `LYNN` 是管理员账号。
- `reviewer01` 到 `reviewer10` 继续作为正式评审账号。

## 评分流程

Vercel 版本评分流程：

1. `/api/rating-items/next` 查询当前 reviewer 尚未评分的图片。
2. 返回图片信息、提示词、目标风格、四个评分维度文案和图片 URL。
3. 用户提交评分。
4. `/api/ratings` 直接 upsert 到 Supabase `ratings` 表。
5. 不写 SQLite。
6. 不写 CSV。

写入规则：

```text
unique key: evaluation_set_id + image_id + reviewer_id
```

如果用户修改已评分图片，仍然 upsert 同一条记录。

## 盲评保护

前端只允许显示：

- `Model_A`
- `Model_B`
- `Model_C`

前端不得显示：

- `M01`
- `M02`
- `M03`
- 真实模型名称
- provider 名称

`generation_jobs.model_id` 只能在服务端用于生成 `blind_model_label`，不能返回给普通评审页面。

## 环境变量

Vercel 需要配置：

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_STORAGE_BUCKET=rating-images
EVALUATION_SET_ID=mvp_2026_06
ADMIN_IDS=LYNN
SESSION_SECRET
```

不要配置到前端公开变量里。不要使用 `NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY`。

如果需要浏览器直接访问 Supabase Storage public URL，可以只暴露 public image URL，不暴露 service role key。

## 数据保留

`LYNN` 当前 48 条评分保留为有效管理员评测数据。

迁移后需要确认：

- Supabase `ratings` 中 `LYNN = 48`
- `reviewer01` 到 `reviewer10` 仍可继续评测
- 后续评分继续写入同一张 `ratings` 表

## 上线前验收

临时 Vercel 链接出来后，必须检查：

- 登录正常
- `LYNN` 能进管理页
- 普通 reviewer 不能进管理页
- 图片能显示
- 提示词与图片对应
- 四个评分维度固定
- 1-5 分按钮可点击
- 备注可输入
- 提交评分后 Supabase `ratings` 增加或更新
- `reviewer_id` 记录正确
- `blind_model_label` 只出现 `Model_A / Model_B / Model_C`
- 页面源代码和接口返回不暴露 `M01/M02/M03` 或真实模型名
- 刷新页面、重新登录、重新部署后评分数据不丢失

## 推荐实施顺序

1. 新建 Vercel/Next.js 项目目录，但保留当前 Python 版本。
2. 写 Supabase Storage 上传脚本，上传 `images/blind/`。
3. 给 `rating_items` 补 `storage_path`。
4. 写 Vercel API：登录、session、取下一张图、提交评分。
5. 迁移现有评分页面 UI。
6. 做手机、平板、电脑响应式检查。
7. 部署 Vercel preview。
8. 用 preview 链接做完整验收。
9. 验收通过后绑定正式域名。

## 不建议现在做的事

- 不建议把当前 `web/app.py` 原样部署到 Vercel。
- 不建议在 Vercel 上继续写 `web/app.db`。
- 不建议把 raw 原图上传到公开 Storage。
- 不建议把 `SUPABASE_SERVICE_ROLE_KEY` 写进前端代码。
- 不建议还没验收 preview 就直接绑定正式域名。
