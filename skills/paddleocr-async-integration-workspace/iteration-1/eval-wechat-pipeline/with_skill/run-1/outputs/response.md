# 微信公众号图片 OCR 实施计划

## 目标与落点

将 OCR 设为微信公众号文章的**规范源文本（canonical source text）**生成步骤，而不是预览功能：HTML 清理后、`article_info.body_text` 写入缓存前，按 DOM 顺序把图片 Markdown 插回正文。这样同一份完整正文会流向：

`ArticleFetchResult.body_text` → 缓存 `article_info.body_text` → `pipeline_runner` 的 `transcript` → DeepSeek `summarize()` → Markdown/搜索索引；以及 `load_content_source_text()` → 问答、结构化分析、日报和周报。

当前项目的对应边界是：抓取在 `backend/services/article_fetcher.py`，正文缓存和惰性回填在 `backend/services/content_source_text.py`，首次总结在 `backend/services/pipeline_runner.py`，报告材料在 `backend/services/wechat_reports.py`。不修改摘要来“补 OCR”，只丰富原文正文。

选择 `PaddleOCR-VL-1.5`、每篇文章最多 5 张图片并发。上线前按 [百度异步 API 官方文档](https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5) 再核对端点、模型名、字段和返回结构；当前约定为本地 multipart 上传、异步 job 轮询及下载 `markdownUrl`，下载签名结果 URL 时不携带授权头。

## 实施步骤

1. 将技能提供的 `paddle_ocr_async.py` 随后端一起纳入 `backend/services/`（或作为该目录私有模块），并由微信公众号适配层调用 `PaddleOcrAsyncClient` / `recognize_many_ordered`。避免在业务层复制提交、轮询和 Markdown 清理逻辑。

2. 在 `article_fetcher` 完成正文节点的脚本、样式、iframe、video 清理和内容过滤后，枚举 `#js_content img`：

   - 只接受 `data-src`/`src` 中的公共 `http(s)` URL；拒绝 localhost、私网/回环/链路本地 IP 字面量，以及非 HTTP(S) 地址。
   - 跳过视频 poster、emoji、二维码、跟踪像素、UI 图和宽/高小于 90px 的装饰图；保留普通内容图，即使预期文字不多。
   - 下载时只带所需的微信浏览器头和文章 URL 作为 `Referer`，不带 OCR token、cookie 或应用凭证；限制每张图片 20 MiB、超时，并在发生重定向时逐跳重新校验目标 URL。

3. 保留每个图片节点的 `position`，即使 OCR 请求按 URL 去重也保留 `url -> [position, node]` 映射。图片下载及 OCR 都使用大小为 `min(5, work_count)` 的有界池；`executor.map` / `recognize_many_ordered` 的返回列表与输入列表同序，因此完成快慢不会改变回填位置。每个成功结果紧跟对应图片节点插入稳定标记：

```text
[图片文字 3]
| 日期 | 事项 |
| --- | --- |
| 7 月 20 日 | 报到 |
[/图片文字 3]
```

对同 URL 的重复图片，复用一次网络 OCR 结果、但在每个原始图片位置插入对应位置的标记；这样源文本的结构和 DOM 一致。

4. 由插入后的 DOM 生成 `body_html` 和 `body_text`，并一起持久化。`image_ocr` 元数据只存非敏感状态，例如：

```json
{
  "attempted": true,
  "model": "PaddleOCR-VL-1.5",
  "image_count": 6,
  "unique_image_count": 4,
  "recognized_count": 5,
  "failed_count": 1
}
```

不存 job ID、签名 `markdownUrl`、上传内容或 token。单图失败保留原图、继续文章，仅记录受限错误类别（如 `timeout`、`network_error`、`job_failed`、`invalid_image`），绝不写请求头、multipart 数据或异常原文。

5. 使用现有本机 Settings 流程保存 token：仅通过密码输入 PUT 写入 `data/paddle_ocr_settings.json`，尽可能 `0600`；启动时读入内存。GET 只返回 `configured`、固定模型名和固定并发数。token 不进入环境导出、缓存 metadata、日志、响应、测试 fixture、Markdown、搜索索引或日报。表单保存后清空输入框。

6. 明确缓存回填规则。无 token 时按既有方式抓取，并保存 `attempted: false`；token 配置后，`pipeline_runner` 和 `load_content_source_text()` 在缓存文章“有图片且从未 OCR attempted”时重新抓取一次。只要该次产生 `attempted: true`（即使部分图片失败），后续读取不再反复抓取；用户显式刷新才允许重新执行。这样旧缓存会在下一次总结、问答或报告使用时惰性补齐，不会产生无限重试。

7. 保证下游始终读完整的 enriched body：

   - `pipeline_runner` 将缓存的 `body_text` 赋给 `transcript` 后再调用 DeepSeek，且用同一文本写 Markdown 和搜索索引；不能在调用前替换为摘要或短摘录。
   - `content_source_text` 返回同一缓存正文并以此更新搜索；问答和内容分析沿用该入口。
   - `wechat_reports._source_material()` 优先 `load_content_source_text(content_item_id)`，把完整 `article.text`（含 `[图片文字 n]`）放入日报/周报提示词；草稿读取只作源文本不可用时的回退，绝不能以 summary 代替正文。

## 核心伪代码

```python
def enrich_wechat_body(content_node, article_url, token):
    nodes = collect_meaningful_images_in_dom_order(content_node)
    if not nodes:
        return ocr_meta(attempted=False, image_count=0)
    if not token:
        return ocr_meta(attempted=False, image_count=len(nodes))

    # unique_jobs preserves first DOM occurrence; positions retains all nodes.
    unique_jobs, positions = dedupe_urls_with_positions(nodes)
    with ThreadPoolExecutor(max_workers=min(5, len(unique_jobs))) as pool:
        local_files = list(pool.map(download_public_image_with_referer, unique_jobs))

    client = PaddleOcrAsyncClient(access_token=token, model="PaddleOCR-VL-1.5")
    results = recognize_many_ordered(client, local_files, max_workers=5)
    by_url = {result.label: result for result in results}

    # Mutate in source order, never completion order.
    for position, image_node, url in nodes:
        result = by_url[url]
        if result.ok:
            image_node.insert_after(markdown_annotation(position, result.markdown))
        else:
            record_safe_per_image_failure(result.error)
    return build_nonsecret_ocr_metadata(nodes, unique_jobs, results)

def fetch_and_persist_wechat_article(url):
    content = clean_noncontent_nodes(parse_html(fetch_wechat_page(url)))
    meta = enrich_wechat_body(content, url, local_paddle_token())
    return ArticleFetchResult(body_html=str(content),
                              body_text=clean_text(content.get_text("\n")),
                              image_ocr=meta)

def cached_article_needs_ocr_backfill(article_info):
    return (ocr_is_configured() and article_info["images"]
            and not article_info.get("image_ocr", {}).get("attempted", False))
```

`PaddleOcrAsyncClient` handles: `POST` local bytes as `file`, `model=PaddleOCR-VL-1.5`, finite job polling (120 s/image), and unauthenticated fetch of the signed Markdown artifact. All remote failures convert to a bounded result rather than raising through the article.

## 验收测试

使用 `pytest` 和确定性 HTTP/mock OCR，不接触真实服务或真实 token：

1. **并发与顺序**：三张图的 mock 完成顺序为 3、1、2；断言生成的 `body_text` 仍为“段落 1 → 图片文字 1 → 段落 2 → 图片文字 2 → 图片文字 3”的 DOM 顺序，并断言最大同时任务数不超过 5。
2. **表格进入规范正文与 DeepSeek**：mock OCR 返回 Markdown 表；断言缓存 `article_info.body_text`、`pipeline_runner.summarize()` 的输入、搜索写入内容均含表格与标记。
3. **报告使用全文**：分别参数化日报和周报，mock `load_content_source_text()` 返回含 OCR 表格的长文；断言发送给 LLM 的 prompt 含全文和表格，而非 summary 或固定长度 excerpt。
4. **降级**：一张图提交/轮询超时、另两张成功；文章仍成功持久化，原图仍在 HTML，正文含两段 OCR，元数据显示一次 attempt 和正确失败数。
5. **本机 token 边界**：PUT 使用虚拟 token 后，检查权限为 owner-only（平台支持时）；GET、`/api/config`、日志捕获、缓存 JSON、导出 Markdown 均不含该字符串；认证头只用于 Paddle job submit/poll，绝不用于结果 URL/图片下载。
6. **SSRF/大小限制**：拒绝 `file:`、localhost、私网 IP、重定向至私网、非图片响应和超过限制的流；这些失败不得中止整篇文章。
7. **缓存回填一次**：准备带图片但无 `image_ocr.attempted` 的旧缓存；配置 token 后首次读取触发一次抓取并写 `attempted: true`；再次读取不抓取，即使第一次有单图失败。无 token 时不触发 OCR。

完成条件：所有测试通过；表格截图文字在首次总结、后续问答/搜索及日报/周报中都能原样找到；无真实 token 出现在仓库、输出、日志或 HTTP GET 响应中。
