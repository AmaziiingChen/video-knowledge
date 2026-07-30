# OCR 旧缓存回填：一次性、可恢复、下游一致

将 OCR 视为规范源文本的回填，而不是每次读取时的临时装饰。旧缓存可以惰性回填（下次被读取时）或由本地后台队列批量回填；两种入口必须共用同一个原子 `claim_ocr_backfill`，不能各自直接调用 OCR。

## 缓存模型

每个文章快照保存原始正文和一个供所有消费者使用的规范正文：

```json
{
  "article_id": "...",
  "image_count": 3,
  "image_set_hash": "sha256(...)",
  "raw_source_text": "抓取到的原始正文",
  "canonical_source_text": "正文 ... [图片文字 1]...[/图片文字 1]",
  "source_text_revision": "sha256(canonical_source_text)",
  "image_ocr": {
    "schema_version": 1,
    "state": "deferred_no_token",
    "attempted": false,
    "attempted_at": null,
    "model": null,
    "attempt_image_set_hash": null,
    "recognized_count": 0,
    "failed_count": 0,
    "safe_failure_categories": [],
    "lease_id": null,
    "lease_expires_at": null
  }
}
```

`state` 只能为 `not_applicable`（无图片）、`deferred_no_token`、`not_attempted`、`in_progress` 或 `completed`。这明确区分“因未配置 token 而递延”、“尚未尝试”和“一次尝试已完成”。`completed` 不表示每张图都成功；因此部分失败也要写入 `completed` 和 `attempted: true`。`safe_failure_categories` 仅可含 `download_failed`、`invalid_image`、`timeout`、`job_failed` 等受限类别，不能存 token、请求头、原始异常、job/result URL 或上传内容。

老记录没有 `image_ocr` 时按 `not_attempted` 解释；无 token 读取时持久化为 `deferred_no_token`。更新文章且 `image_set_hash` 改变时，创建新的缓存快照或将上述 OCR 字段重置为 `not_attempted`；这不是对同一快照的隐式重试。人工“重新 OCR”也必须是显式操作，建立新尝试/快照。

## 刷新判定与原子认领

token 配置变化本身不必扫描或重抓所有文章。它只使旧的 `deferred_no_token` / 缺失元数据记录变得可认领；它们在下一次读取（或后台扫描）时各回填一次。

```python
def eligible_for_ocr(entry, ocr_configured, now):
    meta = entry.image_ocr_or_legacy_default()  # legacy -> not_attempted, attempted=False
    return (
        ocr_configured
        and entry.image_count > 0
        and meta.state in {"not_attempted", "deferred_no_token"}
        and meta.attempted is False
    )

def claim_ocr_backfill(article_id, now):
    # 单个数据库 UPDATE/事务：只有一个读者能从 eligible 状态转为 in_progress。
    # in_progress 且租约未过期时返回 None；过期租约可重新认领（进程崩溃恢复）。
    return atomic_compare_and_set(
        article_id,
        allowed_states={"not_attempted", "deferred_no_token"},
        required_attempted=False,
        set={"state": "in_progress", "lease_id": new_uuid(),
             "lease_expires_at": now + LEASE_TTL},
    )

def read_or_backfill(entry, now):
    if not eligible_for_ocr(entry, settings.ocr_configured, now):
        return entry.canonical_source_text
    claim = claim_ocr_backfill(entry.article_id, now)
    if claim is None:
        return load_cached(entry.article_id).canonical_source_text  # 不重复 OCR
    result = run_ocr_once_in_dom_order(entry, token=settings.token)
    # finally 中由 lease_id 条件写回；成功、零识别、部分失败均完成一次尝试。
    finalize_if_lease_matches(
        claim.lease_id,
        state="completed", attempted=True, attempted_at=now,
        model="PaddleOCR-VL-1.5", attempt_image_set_hash=entry.image_set_hash,
        recognized_count=result.recognized_count, failed_count=result.failed_count,
        safe_failure_categories=result.safe_categories,
        canonical_source_text=result.enriched_text,
        source_text_revision=sha256(result.enriched_text),
        lease_id=None, lease_expires_at=None,
    )
    return result.enriched_text
```

无 token 时不得发起 OCR；仅记录 `deferred_no_token`。正常返回（包括单图失败）后 `completed` 永远不再满足谓词，所以随后的读取不会重新 OCR。仅在工作进程在 `finalize` 前死亡时，租约过期后允许一次恢复性尝试。多图任务可并发（上限 5），但依图片 DOM 位置插入 `[图片文字 N]` 标记，不能依完成先后插入。

## 下游文本约束

`canonical_source_text` 是唯一传给首次摘要、后续问答/RAG 索引、Markdown 导出、日报和周报的文章文本。OCR Markdown（尤其表格）必须紧跟原图位置保留在其中；`raw_source_text` 仅用于溯源/重建，摘要绝不能反向覆盖 `canonical_source_text`。有上下文预算时，只能对这份规范文本作有记录的截断，不能在 OCR 回填前改用摘要或短摘录。

## 确定性测试（本地 fake OCR，无网络/真实 token）

1. **旧缓存一次回填**：构造 `image_count=2`、无 `image_ocr` 的记录和已配置的虚拟 token。第一次读取断言 fake OCR 调用一次、文本含两段标记、状态为 `completed/attempted=true`；第二次读取断言调用数仍为一次。
2. **未配置与有图的区分**：无 token 读取有图记录，断言零 OCR 调用和 `deferred_no_token/attempted=false`；无图记录为 `not_applicable`，配置 token 后也不可认领。
3. **部分失败不重试**：fake OCR 依次给出成功、`timeout`、成功。断言文章仍持久化、两段 OCR 在规范文本中、`recognized_count=2`、`failed_count=1`、状态 `completed`；任意后续读取不再调用 fake OCR。
4. **顺序独立于完成顺序**：用可控 future 令三张图片按 3、1、2 完成，断言 `canonical_source_text` 的标记仍为 1、2、3，且表格 Markdown 原样保留。
5. **并发读防重**：两个线程在同一 `not_attempted` 记录上同步开始；断言仅一个拿到租约、fake OCR 仅调用一次，另一线程返回旧/最终缓存而不发请求。再模拟持有者在完成前崩溃和时钟越过 TTL，断言只允许恢复性认领一次。
6. **下游一致性**：以含 OCR 表格的 `canonical_source_text` 调用摘要、Q&A、索引和日报/周报构造器；断言每个输入都包含相同表格和 `[图片文字 1]`，且没有用 `raw_source_text` 或摘要替代。
7. **秘密不泄露**：使用固定虚拟 token sentinel；断言设置 GET、缓存序列化、日志捕获、异常、导出文本和 fake 图片/结果请求均不含该 sentinel，且 token 只传给 fake OCR 客户端的认证接口。
