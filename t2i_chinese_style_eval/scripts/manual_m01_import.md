# M01 手动导入流程

适用场景：M01 图片由聊天界面生成，下载成本地图片后，再导入本项目账本。

## 原则

- 只导入 `model_id=M01` 且 `status=pending` 的任务。
- 不修改 Prompt，不新增 Prompt，不改变四层 Prompt 分层设计。
- 图片复制到 `images/raw/`，命名为 `J0001_manual_<timestamp>.png` 这类格式。
- 脚本只回填 `generation_jobs.csv`，不写 `metadata.csv`、`rating_items.csv`。
- 不要和 `generate_images.py --execute` 同时运行，避免两个脚本同时写同一本账本。

## 单张导入

先看 M01 待补任务：

```bash
python3 scripts/import_manual_m01.py --list-pending
```

检查一张图片是否能导入：

```bash
python3 scripts/import_manual_m01.py --dry-run --job-id J0001 --source /path/to/image.png
```

确认没问题后真实导入：

```bash
python3 scripts/import_manual_m01.py --execute --job-id J0001 --source /path/to/image.png
```

导入后校验：

```bash
python3 scripts/validate_schema.py
```

## 批量导入

复制模板：

```bash
cp data/manual_m01_import_manifest.template.csv data/manual_m01_import_manifest.csv
```

在 `source_path` 列填入每张下载图片的本地路径，然后先 dry-run：

```bash
python3 scripts/import_manual_m01.py --dry-run --manifest data/manual_m01_import_manifest.csv
```

确认 16 行映射都正确后执行：

```bash
python3 scripts/import_manual_m01.py --execute --manifest data/manual_m01_import_manifest.csv
python3 scripts/validate_schema.py
```
