# 旧缓存的 OCR 回填设计

Token 保存成功后发布一个 `ocr_backfill_requested` 事件（携带非敏感的 `ocr_config_revision`，不携带 token）。后台扫描旧文章的图片并入队；文章读取路径只做一次轻量的“是否需要入队”判断，绝不在请求线程中调用 OCR。队列和数据库唯一键共同保证多次读取、多个 worker 或重复事件不会产生重复 OCR。

## 数据模型

`article`

| 字段 | 用途 |
| --- | --- |
| `id` | 文章 ID |
| `body_text` | 原始文章正文；永不被 OCR 回填直接改写 |
| `source_text` | 面向检索/下游的派生文本 |
| `source_text_hash` | `source_text` 的 SHA-256，用于避免重复索引 |
| `source_text_revision` | 派生文本版本 |

`article_image`

| 字段 | 用途 |
| --- | --- |
| `id`, `article_id`, `ordinal` | 图片身份及在文章中的稳定顺序 |
| `canonical_url` | 规范化后的来源 URL（仅作定位，不作缓存键） |
| `content_sha256` | 已下载图片字节的哈希；内容改变时自然失效 |
| `fetch_status` | `available` / `unavailable`，避免为不可得图片反复排队 |

`image_ocr_cache`

| 字段 | 用途 |
| --- | --- |
| `image_id`, `provider`, `request_fingerprint` | 缓存身份；唯一约束 `UNIQUE(image_id, provider, request_fingerprint)` |
| `model_version`, `options_json` | OCR 模型及语言、方向等会影响结果的选项 |
| `status` | `queued`、`running`、`succeeded`、`no_text`、`retryable_failed`、`terminal_failed` |
| `text`, `blocks_json`, `result_hash` | 规范化文字、坐标/置信度，以及结果去重哈希 |
| `attempt_count`, `last_attempt_at`, `completed_at` | 审计与重试控制 |
| `next_retry_at`, `failure_code` | 仅暂时性失败可在到期后重试 |
| `ocr_config_revision` | 非机密配置修订号，便于审计；不要存 token 或 token 哈希 |

`request_fingerprint = sha256(content_sha256 + provider + model_version + canonical_json(options_json))`。模型或选项升级会产生新行；同一图片内容、模型和选项永远命中同一行。队列再以 `image_id + provider + request_fingerprint` 作为幂等键（或使用支持去重的 job ID）。

## 回填与读取判定

Token 配置完成后，由后台分页查询 `article_image.fetch_status = 'available'` 的历史图片，按下列谓词原子地创建/领取缓存行并提交幂等 job。可限制并发、分批和限速；token 缺失时不扫描、不入队。

```text
needs_ocr(image, cfg, now):
  if not cfg.token_configured or image.fetch_status != "available":
      return false
  key = fingerprint(image.content_sha256, cfg.provider, cfg.model_version, cfg.options)
  row = cache.get(image.id, cfg.provider, key)
  return row is absent
      or (row.status == "retryable_failed" and row.next_retry_at <= now)

ensure_ocr_job(image, cfg, now):                 # transaction / compare-and-set
  if not needs_ocr(image, cfg, now): return
  upsert cache(key, status="queued") only if absent
      or (status="retryable_failed" and next_retry_at <= now)
  enqueue_once(job_id = "ocr:" + image.id + ":" + key)

on_article_read(article):
  return article plus current source_text
  asynchronously call ensure_ocr_job for its images # optional lazy safety net
  # never wait for, or perform, OCR here

worker(job):
  atomically claim only a matching queued row
  OCR once; persist succeeded/no_text or retryable_failed(next_retry_at=backoff)
  if normalized OCR result changed source_text: rebuild source_text and reindex
```

`terminal_failed` is intentionally not retried by reads. 其重新处理应是人工“强制刷新”操作（创建新的 fingerprint/显式 override），避免永久错误或坏图导致热循环。对于停留过久的 `running` job，可由超时回收任务改为 `retryable_failed`；读取本身不抢救它。

## 下游 source text

不要把识别结果覆盖 `body_text`。按 `article_image.ordinal` 将成功的非空结果稳定拼入派生文本，例如：

```text
<正文>

[图片 2 OCR | image_id=im_42]
图中的可检索文字
```

只纳入 `succeeded` 且规范化后非空的 `text`；`no_text`、失败和排队状态不产生占位文字。保留 `image_id`、块坐标和置信度可让搜索命中回跳到图片并标注来源。每次重建使用相同排序和规范化规则，比较 `source_text_hash`：未变则不更新 revision、不重新建索引/embedding；变了才发布 `article_source_text_changed`。这使 OCR 的迟到结果可见，同时不会把 OCR 内容伪装成作者正文。

## 确定性测试

测试使用固定时钟 `2026-07-15T00:00:00Z`、固定 SHA 和 fake queue/OCR client；断言 cache 行、job ID、调用次数和 `source_text_hash`，不依赖真实 token 或网络。

| 用例 | 初始条件 / 操作 | 断言 |
| --- | --- | --- |
| 1. 回填候选 | 旧文章图片可用、无 cache；token 从缺失变为已配置 | 发布事件后恰入队 1 个确定 job；读取不直接调 OCR |
| 2. 重复读取 | 用例 1 的 row 已 `queued`，连续读取 3 次 | 仍只有 1 条 cache/job，OCR 调用数为 0 |
| 3. 已成功命中 | 相同 fingerprint 为 `succeeded` | 回填扫描和读取均不入队、不调用 OCR |
| 4. 无文字命中 | 相同 fingerprint 为 `no_text` | 不再入队；`source_text` 不含该图片段 |
| 5. 暂时错误退避 | `retryable_failed`, `next_retry_at` 在固定时钟之后 | 不入队；时钟推进到该时刻后只入队 1 次 |
| 6. 永久错误 | `terminal_failed` | 读取、扫描均不入队；仅显式 force refresh 可创建新请求 |
| 7. 图片内容变更 | 同一 `image_id` 的 `content_sha256` 改变 | fingerprint 改变，入队一次新 job；旧成功记录不被误用 |
| 8. 并发竞争 | 两个 `ensure_ocr_job` 同时处理缺失 row | 唯一键/条件更新后只有一个 `queued` row 和一个 job |
| 9. 模型升级 | 内容相同但 `model_version` 改变 | 产生新 fingerprint、恰 OCR 一次；旧结果仍可审计 |
| 10. 下游稳定性 | OCR 结果按不同完成顺序返回，图片 ordinal 为 2、5 | `source_text` 总按 ordinal 排列；相同规范化结果不改变 hash、不触发再索引 |
| 11. 下游更新 | 首次成功返回文字后，worker 重复投递相同结果 | 首次触发一次 `article_source_text_changed`；第二次不递增 revision、不重新建索引 |

此外应做一次迁移测试：已有文章没有 `article_image` 的 `content_sha256` 时先补抓取/哈希；拿不到字节则标记 `unavailable`，而不是以 URL 反复 OCR。这样旧缓存能逐步回填，也保持每个确定输入最多一次正常 OCR 尝试（重试/显式刷新除外）。
