# AGENTS.md — Daily Paper Digest

实现每日论文推送。用户主要在中国内地 / 香港阅读。单个数据源或单篇论文失败不得让整次运行失败。密钥只来自环境变量。模型名、篇数、主题、RSS、推送开关只放在 `config/`。

## 运行

```bash
python -m digest run [--dry-run] [--date YYYY-MM-DD]
```

`--dry-run` 使用 `tests/fixtures/dry_run.json`，把邮件和网页写到 `out/`，不发送、不部署、不修改 `data/`。

## 流水线

1. 候选：alphaXiv For You → Hot → Hugging Face Daily Papers → 三者都没有新论文时才用 arXiv 分类列表。
2. arXiv API 补元数据（每批最多 50 个 id，间隔至少 3 秒）。
3. 用 `data/seen.json` 去掉已推送 id，多源合并并保留热度。
4. 邮件分只用 `default: true` 的主题；网页保存每个主题的 0–10 分。`score = 0.65 * 相关度/10 + 0.25 * 来源信号 + 0.10 * 新近度`。
5. 正文：alphaXiv `get_paper_content` → arXiv HTML → 摘要。
6. 图：arXiv HTML `<figure>` → LaTeX 源码 → PDF 裁剪 Figure 1 → 不放图。多模态选图失败则退回 caption。
7. 写稿只输出 JSON，校验失败重试 1 次，再失败则标题 + 摘要简版。
8. 期刊 RSS 取 48 小时内、最多 `journal_items_max` 篇。
9. 渲染邮件（无 JS、CID 内嵌图）和静态网页（主题复选框）。
10. 邮件、微信、网页部署互相独立。
11. 把邮件篇目写入 `seen.json` 和 `data/archive/YYYY-MM-DD.json`。

alphaXiv MCP：`https://api.alphaxiv.org/mcp/v1`，Bearer token。先 `list_tools()`，按 `inputSchema` 填参数。官方 SDK 2.3 的入口是 `streamable_http_client`，鉴权头放在 `httpx2.AsyncClient` 上，同一次运行复用一个 session。

只有所有候选源都失败或最终 0 篇时才以非零状态退出，并尝试发送微信「今日推送失败，请查看 Actions 日志」。

## 不要做的事

- 不要把密钥写进仓库。
- 不要在测试里访问网络。
- 不要硬编码 MCP 工具的参数名。
- 不要在结果数字缺失时编造数字；写「论文未给出具体数字」。
