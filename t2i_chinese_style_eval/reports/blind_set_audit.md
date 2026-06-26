# 盲评图片集审计报告

- 生成时间：2026-06-26T05:38:14+00:00
- rating_items.csv 行数：32
- metadata.csv 行数：32
- images/blind 文件数：32
- generation_jobs success 数：32
- ERROR：0
- WARN：0

## 分布检查

### 模型分布（仅 metadata，可解密，网站不可读）

- M01: 16
- M02: 16

### 目标风格分布（rating_items）

- 京剧脸谱: 8
- 敦煌图像: 8
- 民间年画: 8
- 水墨山水: 8

### Prompt Level 分布（rating_items）

- L1: 16
- L2: 16

### 图片尺寸分布（metadata）

- 1254x1254: 16
- 2048x2048: 16

## 每个 Prompt × Model 数量

| prompt_id | M01 | M02 |
|---|---:|---:|
| DH_L1_001 | 2 | 2 |
| DH_L2_001 | 2 | 2 |
| JP_L1_001 | 2 | 2 |
| JP_L2_001 | 2 | 2 |
| NH_L1_001 | 2 | 2 |
| NH_L2_001 | 2 | 2 |
| SS_L1_001 | 2 | 2 |
| SS_L2_001 | 2 | 2 |

## 问题列表

未发现问题。

## 结论

若 ERROR=0，则当前盲评图片集可用于主观评分和客观评价。rating_items.csv 不包含模型来源、job_id、seed 或 auto_scores 字段。
