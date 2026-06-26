# SumiRate 数据库化迁移方案

## 当前建议

短期继续保留现有网站界面和本地运行方式，但把长期数据底座迁到 Supabase Postgres。

迁移分三步走：

1. 建立 Supabase/Postgres 表结构。
2. 把当前 CSV/SQLite 中已有数据导入数据库。
3. 确认无误后，再把网站的评分提交逻辑改为写入数据库。

这样不会破坏当前本地评审网站，也方便回退。

## 新增文件

- `db/001_supabase_schema.sql`
  - Supabase/Postgres 建表脚本。
  - 包含 prompts、models、generation_jobs、rating_items、reviewers、ratings 等核心表。

- `scripts/build_supabase_seed_sql.py`
  - 从当前 CSV 生成数据库导入 SQL。
  - 不连接数据库，只生成 `db/002_seed_current_data.sql`。

- `db/002_seed_current_data.sql`
  - 当前 48 张图片、提示词、生成任务、评审账号和已有评分的导入脚本。

## 推荐表结构

核心表：

- `prompts`：提示词题库。
- `models`：真实生成模型信息，只供后台和分析使用。
- `evaluation_sets`：评测批次，例如 `mvp_2026_06`。
- `model_blind_labels`：每个评测批次内的模型盲化映射。
- `generation_jobs`：生成任务账本。
- `rating_items`：盲评图片项。
- `reviewers`：评审者账号。
- `ratings`：主观评分结果。
- `feedback`：问题反馈。

当前盲化映射：

```text
M01 -> Model_A
M02 -> Model_B
M03 -> Model_C
```

前端评审页面不应显示 `model_id`、真实模型名或 raw 图片路径。

## Supabase 操作顺序

1. 新建 Supabase 项目。
2. 打开 SQL Editor。
3. 执行 `db/001_supabase_schema.sql`。
4. 执行 `db/002_seed_current_data.sql`。
5. 在 Supabase Table Editor 中检查：
   - `rating_items` 是否为 48 条；
   - `generation_jobs` 是否为 48 条；
   - `ratings` 是否为当前已有评分条数；
   - `ratings.blind_model_label` 是否只出现 `Model_A / Model_B / Model_C`。

## 网站切换建议

第一阶段只把评分结果写入 Supabase：

```text
读取评审图片：继续使用本地 rating_items.csv / images/blind
写入评分结果：写入 Supabase ratings 表
```

当前网站已按这个方式预留配置：

```text
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
EVALUATION_SET_ID=mvp_2026_06
```

运行逻辑：

- 未配置 Supabase 时：继续只写本地 `web/app.db` 和 CSV。
- 配置 Supabase 后：评分先写本地，再同步 upsert 到 Supabase `ratings` 表。
- 如果 Supabase 同步失败：页面会提示云端同步失败，避免静默丢数据。

第二阶段再把读取也改为 Supabase：

```text
读取评审图片、提示词、评分进度：Supabase
图片文件：Supabase Storage / Cloudflare R2 / 其他对象存储
```

## 部署注意

如果使用 Vercel、Netlify 等 serverless 平台，不要把 `web/app.db` 或本地 CSV 当作正式评分数据源。

长期正式数据应保存到 Supabase/Postgres。图片数量继续增长后，建议把 `images/blind` 迁到对象存储，并在 `rating_items.blind_image_path` 或新增 `blind_image_url` 中保存访问地址。
