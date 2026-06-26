# 数据结构说明（schema.md）

本项目所有数据以 CSV 为账本，分为三类：

| 类别 | 文件 | 谁可以读 |
|---|---|---|
| **输入定义表** | `prompts.csv`、`models.csv`、`evaluator_models.csv` | 所有脚本 |
| **解密账本** | `generation_jobs.csv`、`metadata.csv` | 仅生成 / 离线分析脚本 |
| **盲评任务表** | `rating_items.csv` | 主观评分网站（**严格隔离**）|
| **评分结果表** | `auto_scores.csv`、`human_scores.csv` | 分别由 auto_evaluate.py / 评分网站写入；仅离线分析脚本合并 |

> **盲评隔离硬约束**：主观评分网站**绝对不能**读取 `metadata.csv`、`model_id`、`model_name`、`seed`、`auto_scores.csv`。匿名隐藏的是**模型来源**，不是 Prompt。

---

## 1. prompts.csv —— Prompt 库

| 字段 | 类型 | 说明 |
|---|---|---|
| `prompt_id` | string | 主键。格式 `<STYLE>_L<LEVEL>_<NNN>`，例：`SS_L1_001`。风格代号：SS=水墨山水, DH=敦煌图像, NH=民间年画, JP=京剧脸谱 |
| `target_style` | string | 目标风格中文名 |
| `prompt_level` | enum | 四层分层，每层对应一个独立评测维度（详见下文 §Prompt 分层定义）。MVP 仅含 L1/L2 |
| `prompt_text` | string | Prompt 原文（中文） |
| `expected_elements` | string | 期望出现元素，分号 `；` 分隔 |
| `forbidden_elements` | string | 禁止出现元素，分号 `；` 分隔 |

### Prompt 分层定义

四层 prompt_level 是**正交评测维度**，不是"提示繁简度"：

| Level | 名称 | 结构 | 测什么 |
|---|---|---|---|
| **L1** | 基础风格层 | 目标风格 + 基本对象 | 模型是否知道这个传统视觉门类长什么样（风格识别能力） |
| **L2** | 风格—对象复合层 | 目标风格 + 具体对象 + 关键元素 | 模型能不能在目标风格里生成指定文化对象（对象生成能力） |
| **L3** | 风格—语境层 | 目标风格 + 文化场景 + 气质/寓意/身份 | 模型是否理解文化场景、历史气质和门类语境（语境理解能力） |
| **L4** | 文化边界测试层 | 目标风格 + 基本任务 + 明确排除项 | 模型会不会跑偏、混搭、现代化、游戏化（边界控制能力） |

**关键约束**：L2 prompt 只描述**视觉对象/元素**（飘带、琵琶、对称构图、勾脸纹样），不写**语境/气质/寓意**（"清淡疏朗""节庆装饰感""守护寓意""谱式规范"）。后者属于 L3。

**生成约束**：MVP prompt 不统一追加印章、落款、签名等排除句，避免把额外约束混入风格/对象测试。若图像出现伪文字或不合适题款，后续可在主观评分备注、错误标签或 L4 文化边界测试中记录。

**MVP 用 L1/L2 共 8 条**；正式版按每风格 L1×2 + L2×2 + L3×2 + L4×2 = 8 条扩到 32 条。

---

## 2. models.csv —— 生成模型表

| 字段 | 类型 | 说明 |
|---|---|---|
| `model_id` | string | 主键，例 `M01` |
| `model_name` | string | 模型展示名 |
| `provider` | string | 服务商 |
| `api_endpoint` | string | API 地址 |
| `model_version` | string | 模型版本标识 |
| `default_params` | json | 默认调用参数 |
| `notes` | string | 备注 |

---

## 3. evaluator_models.csv —— 评价模型表

| 字段 | 类型 | 说明 |
|---|---|---|
| `evaluator_id` | string | 主键，例 `E01` |
| `evaluator_name` | string | 评价模型名 |
| `provider` | string | 服务商 |
| `api_endpoint` | string | API 地址 |
| `model_version` | string | 模型版本 |
| `role` | enum | `primary` / `reserved_for_v1` / `reserved_cultural_supplement` |
| `notes` | string | 备注 |

---

## 4. generation_jobs.csv —— 生成任务队列（解密账本）

由 `generate_images.py` 写入。**评分网站不可读。**

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | string | 主键，例 `J0001` |
| `prompt_id` | fk → prompts | |
| `model_id` | fk → models | |
| `replicate_idx` | int | 同 (prompt, model) 下的副本序号，从 1 开始 |
| `seed` | int / null | 模型支持时记录；否则为空 |
| `status` | enum | `pending` / `running` / `success` / `failed` / `timeout` / `safety_blocked` |
| `attempts` | int | 已尝试次数（含重试）|
| `original_prompt` | string | 原始 Prompt（与 prompts.csv 一致）|
| `revised_prompt` | string | API 改写后的 Prompt（若有）|
| `revision_reason` | string | 改写原因（API 返回或推断；safety/policy）|
| `raw_image_path` | string | 原始图片保存路径 |
| `error_code` | string | 失败错误码 |
| `error_message` | string | 失败原因 |
| `timeout_sec` | int | 实际等待秒数 |
| `safety_blocked` | bool | 是否被安全策略拦截 |
| `created_at` / `started_at` / `finished_at` | ISO8601 | |

**重要约定**：Prompt 被安全策略拦截时，**不能偷偷改写后重发**。必须如实记录 `original_prompt` / `revised_prompt` / `revision_reason`，且 `safety_blocked=true`。

---

## 5. metadata.csv —— 图片解密账本

由 `blind_images.py` 写入。**评分网站不可读。**

| 字段 | 类型 | 说明 |
|---|---|---|
| `image_id` | string | 主键，例 `img_0001` |
| `blind_filename` | string | 匿名后文件名，例 `img_0001.png` |
| `job_id` | fk → generation_jobs | |
| `prompt_id` | fk → prompts | |
| `model_id` | fk → models | **敏感**：评分网站绝不可读 |
| `replicate_idx` | int | |
| `seed` | int / null | |
| `original_prompt` | string | |
| `revised_prompt` | string | |
| `revision_reason` | string | |
| `raw_image_path` | string | 匿名前路径 |
| `blind_image_path` | string | 匿名后路径（如 `images/blind/img_0001.png`）|
| `image_width` / `image_height` | int | |
| `generated_at` | ISO8601 | |

---

## 6. rating_items.csv —— 盲评任务表

由 `blind_images.py` 在匿名完成后**仅从允许字段生成**。**评分网站读取的唯一数据源。**

| 字段 | 类型 | 说明 |
|---|---|---|
| `image_id` | string | 与 metadata 对齐，但网站不读 metadata |
| `blind_filename` | string | 用于展示图片 |
| `target_style` | string | 目标风格（展示给评审者）|
| `prompt_level` | enum | L1/L2/L3/L4（详见 §Prompt 分层定义） |
| `prompt_text` | string | Prompt 原文（**展示**，匿名仅隐藏模型来源，不隐藏 Prompt）|
| `expected_elements` | string | 期望元素 |
| `forbidden_elements` | string | 禁止元素 |

**不包含**：`model_id`、`model_name`、`seed`、`job_id`、任何 `auto_scores` 字段。

---

## 7. auto_scores.csv —— 客观评价结果

由 `auto_evaluate.py` 写入。

| 字段 | 类型 | 说明 |
|---|---|---|
| `score_id` | string | 主键 |
| `image_id` | fk | |
| `evaluator_id` | fk → evaluator_models | |
| `evaluated_at` | ISO8601 | |
| `style_fidelity` | int 1-5 | 风格保真度 |
| `element_accuracy` | int 1-5 | 期望元素准确性 |
| `context_appropriateness` | int 1-5 | MVP 阶段仅表示明显语境错误/风格漂移控制，不解释为深层文化理解 |
| `forbidden_compliance` | int 1-5 | 禁止元素合规度（**反向语义**：5=无违反，1=严重违反）。固定语义在 `auto_evaluate.py` 和 `analyze_results.py` 中遵守 |
| `overall_score` | float | 综合分（计算公式在 analyze_results.py 中定义）|
| `expected_hits` | string | 命中的 expected 元素列表（分号分隔）|
| `forbidden_hits` | string | 出现的 forbidden 元素列表 |
| `raw_response_json` | string | 评价模型原始 JSON 响应（审计用）|
| `error_message` | string | 评价失败原因 |

**客观评价硬约束**：不能开放式问"这是什么风格"或"是否符合中国传统文化语境"。必须输入 `target_style`、`prompt_text`、`expected_elements`、`forbidden_elements`，做结构化判断。MVP 自动评价主要关注 `style_fidelity`、`element_accuracy`、`forbidden_compliance`，综合分固定为 `0.40 × style_fidelity + 0.40 × element_accuracy + 0.20 × forbidden_compliance`；`context_appropriateness` 暂作为明显语境错误/风格漂移控制的兼容字段。

---

## 8. human_scores.csv —— 主观评分结果

由主观评分网站写入。

| 字段 | 类型 | 说明 |
|---|---|---|
| `rating_id` | string | 主键 |
| `image_id` | fk | |
| `rater_id` | string | 评审者匿名 ID |
| `rated_at` | ISO8601 | |
| `style_fidelity` | int 1-5 | |
| `element_accuracy` | int 1-5 | |
| `context_appropriateness` | int 1-5 | |
| `overall_score` | int 1-5 | |
| `error_tags` | string | 错误类型多选标签，分号分隔。候选：`现代插画化`；`对象错误`；`门类混搭`；`写实摄影化`；`西式元素混入`；`色彩失真`；`构图失范`；`其他` |
| `comment` | string | 可选评语 |

---

## 数据流总览

```
prompts.csv + models.csv
        │
        ▼
generate_images.py ──► generation_jobs.csv ──► images/raw/
        │
        ▼
blind_images.py ──► metadata.csv (解密) + rating_items.csv (盲评) + images/blind/
        │
        ├──► auto_evaluate.py (读 rating_items + images/blind) ──► auto_scores.csv
        │
        └──► 评分网站 (仅读 rating_items + images/blind) ──► human_scores.csv
                                                                │
                                                                ▼
                                                analyze_results.py
                                                (合并 metadata + auto_scores + human_scores)
                                                                │
                                                                ▼
                                                        reports/
```

## MVP 规模

- 4 风格 × 2 Prompt = 8 条 Prompt
- 2 模型（M01 GPT Image 2, M02 Qwen Image 2.0 Pro）
- 每 (prompt, model) 生成 2 张副本
- 总计 **8 × 2 × 2 = 32 张图**

## 评审者一致性

优先用 **ICC** 或 **Krippendorff's alpha**，不优先用 Cronbach's alpha。
