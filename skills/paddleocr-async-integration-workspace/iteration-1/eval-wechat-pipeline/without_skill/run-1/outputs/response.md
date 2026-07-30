# 微信公众号图片 OCR 接入计划

目标是把正文图片（尤其是表格截图）的识别结果作为文章正文的一部分保存；图片可并发处理，但结果必须按 HTML 中的原始位置插回，因此 DeepSeek 总结、搜索索引和日报/周报读取到的是同一份富集后的正文。

## 实施顺序

1. **配置与凭证**：新增 `PADDLE_OCR_IMAGE_CONCURRENCY`（默认 4--5）、单图大小上限、提交/轮询/总超时与模型名配置。Token 仅由后端写入本机凭证库（macOS Keychain 优先；不能使用时为本机数据目录中 `0600` 的私有配置文件），数据库只保存凭证引用或 `configured` 状态。设置 API 的 `GET` 只返回 `configured/model/concurrency`，日志、异常、导出、同步和响应体一律不回显 token。
2. **OCR 服务层**：在 `backend/services/paddle_ocr.py` 实现一个与 HTTP 路由解耦的 `recognize_wechat_images`。每张图先用公众号文章 URL 作 Referer 下载到内存，再上传给 PaddleOCR、轮询任务并下载 Markdown 结果。只允许公网 `http(s)` 图片、拒绝内网/回环地址，校验 `image/*`、限制流式下载大小和所有网络超时。单图失败返回结构化失败结果，不使整篇文章失败。
3. **保持正文顺序地并发**：抓取器在清洗后的 `#js_content` 中按 DOM 顺序收集有效 `img`，为每个节点分配 `position`。对相同 URL 仅 OCR 一次，但保留每个节点的位置；受限并发执行任务，按输入索引收集结果（`asyncio.gather` 或 `executor.map`），而不是按完成时间追加。
4. **回填与持久化**：在每个图片节点后插入确定的文本块，例如 `[图片文字 3]…[/图片文字 3]`；随后由现有 DOM 转文本流程生成 `body_text`。将该 `body_text` 写入文章的 source-text/草稿缓存，并记录不含敏感信息的 OCR 元数据（图片数、成功/空结果/失败数、耗时、模型）。OCR 未配置时仍保留原来的纯文本流程，并标记为未尝试。
5. **下游接线**：文章处理任务调用 DeepSeek 时必须传入富集后的 `body_text`，不能回退到抓取前的纯文本字段。日报/周报按 `content_item_id` 读取完整 source text；仅在缓存缺失时才读取 Markdown 草稿，并从“原文正文”区段读取。这样表格内容会同时进入总结、检索和报告。
6. **发布与观测**：先以低并发、可开关配置上线；为文章处理日志增加 `ocr_attempted/recognized/failed/elapsed_ms`。不要记录图片二进制、鉴权头、服务商原始错误或 token。监测失败率、超时率、每篇 OCR 延迟和 OCR 文本进入总结的覆盖率；异常时关闭 OCR 即可安全降级。

## 关键伪代码

```python
@dataclass
class OcrResult:
    url: str
    text: str = ""
    status: Literal["succeeded", "empty", "failed", "not_configured"] = "empty"
    error_code: str | None = None

async def recognize_wechat_images(urls: list[str], article_url: str) -> list[OcrResult]:
    # urls 的顺序就是 DOM 顺序；不可用 token 时不发网络请求。
    if not local_secret_store.has("paddle_ocr_token"):
        return [OcrResult(url=u, status="not_configured") for u in urls]

    semaphore = asyncio.Semaphore(settings.ocr_image_concurrency)
    async def one(url: str) -> OcrResult:
        try:
            async with semaphore:
                assert_public_http_url(url)       # 防 SSRF
                blob, mime, name = await download_limited_image(
                    url, referer=article_url, max_bytes=settings.ocr_max_image_bytes
                )
                job_id = await paddle.submit(blob, mime, name, token=local_secret_store.get(...))
                markdown = await paddle.poll_result(job_id, deadline=settings.ocr_deadline)
                return OcrResult(url, clean_markdown(markdown), "succeeded")
        except TimeoutError:
            return OcrResult(url, status="failed", error_code="timeout")
        except Exception:
            return OcrResult(url, status="failed", error_code="request_failed")

    # gather returns in task creation order even when task completion order differs.
    return await asyncio.gather(*(one(url) for url in urls))

def enrich_article_dom(content, article_url):
    nodes = [(index, img, resolved_url(img)) for index, img in enumerate(valid_images(content), 1)]
    unique_urls = list(dict.fromkeys(url for _, _, url in nodes))
    result_by_url = {r.url: r for r in await_or_threaded(recognize_wechat_images(unique_urls, article_url))}
    for position, img, url in nodes:              # explicitly DOM order
        result = result_by_url[url]
        if result.status == "succeeded" and result.text:
            img.insert_after(make_paragraph(f"[图片文字 {position}]\n{result.text}\n[/图片文字 {position}]"))
    return normalize_text(content.get_text("\n", strip=True))

article = fetch_wechat_article(url)               # article.body_text is now enriched
save_source_text(item.id, article.body_text)
summary = deepseek.summarize(article.body_text, article.title)
report_material = load_content_source_text(item.id).text
```

在当前同步抓取路径中，可用受限 `ThreadPoolExecutor.map` 替代协程；同样必须以输入列表为结果顺序，且不能在 worker 内直接写 DOM 或数据库。

## 验收测试

| 层级 | 场景与断言 |
| --- | --- |
| OCR 单元测试 | mock 三张图以乱序完成；结果数组和回填块仍为 1、2、3 顺序。验证并发数不超过配置、去重 URL 只调用一次、空结果/超时/HTTP 失败不会中断其它图片。 |
| 抓取集成测试 | HTML 为“段落 A → 表格图片 → 段落 B”；断言 `body_text` 中 A < 图片文字 < B，表格 Markdown 完整出现，`body_html` 中图片后紧邻标记块。 |
| 安全与配置测试 | token 保存后权限为仅当前用户；`GET` 设置、错误、日志和导出均不包含 token。拒绝 `file:`、localhost、私网 IP、非图片类型、超限图片和重定向到私网地址。 |
| 下游回归测试 | mock DeepSeek，断言其输入含 `[图片文字]` 与表格单元格；生成日报/周报时断言 prompt 使用完整 source text 而非摘要片段。 |
| 端到端与降级 | 使用本地 fixture 页面和 mock Paddle 服务跑 FastAPI 处理任务，确认 OCR 文本被保存、摘要与日报可见；未配置或关闭 OCR 时文章仍成功入库且状态明确。 |

完成条件：一篇含表格截图的公众号文章，从抓取、保存、DeepSeek 总结到日报的每一段都能追踪到同一段 OCR 文本；任一图片或 OCR 服务失败只降低该图片覆盖率，不阻塞文章处理。
