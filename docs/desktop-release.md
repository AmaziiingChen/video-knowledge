# 桌面端发布步骤

## 构建产物

当前只发布 macOS Apple Silicon 版本，不做跨平台伪构建：

```bash
# macOS Apple Silicon
cd frontend
npm run desktop:package:mac
```

该命令生成 DMG，位于 `frontend/release/`。安装包不启用自动下载、静默安装或一键更新。
标签 `v<package.json 版本>` 推送后，GitHub Actions 会在 Apple Silicon macOS
运行器上重新构建，校验 DMG 完整性、应用版本、Bundle ID、可执行文件架构、
后端体积上限、运行数据泄露和误内置模型，并将 DMG 与对应 SHA-256 上传到
正常 GitHub Release。手动运行同一工作流时只生成可下载的 CI 产物，不创建 Release。

语音模型不随安装包分发。用户在“设置 → 本机处理”中按需下载所选模型；模型保存在用户本机数据目录，不进入应用包或 GitHub Release。

安装包内的同一后端可执行文件也提供 `--mcp-stdio` 入口，不复制第二套
Python/模型运行时。KnowledgeHub 不会自动改写 OpenClaw 配置；本机 bridge
命令、短期 capability 文件路径和撤销语义见
[OpenClaw 接入说明](openclaw-ingest.md#local-mcp-bridge-configuration)。

## 无 Developer ID 签名的 macOS 分发

KnowledgeHub 当前以不使用 Developer ID 签名或 Apple 公证的 Apple Silicon DMG 正常发布。每个 GitHub Release 都会提供对应的 SHA-256 校验值；下载后请先核对校验值，再安装和打开应用。

首次打开时，macOS 可能显示“无法验证开发者”的安全提示。请先尝试打开应用，然后前往“系统设置 → 隐私与安全性”，在安全提示旁选择“仍要打开”。这只为该应用创建本机例外，不会关闭系统的整体安全保护。

如果已核对 Release 中的 SHA-256、且系统界面仍无法打开，可对安装后的这一份应用执行：

```bash
xattr -dr com.apple.quarantine "/Applications/KnowledgeHub.app"
```

不要使用 `sudo`，也不要关闭 Gatekeeper 或对整个下载目录执行隔离属性清除命令。

## 发布前清单

完整的本地候选版本门禁、证据格式、安装包冒烟和待机资源记录见
[发布候选验证](release-candidate-verification.md)。

- macOS：发布不使用 Developer ID 签名或 Apple 公证的 Apple Silicon DMG，并在干净账户完成安装、首次打开、复启验证后再上传；随 Release 提供实际文件的 SHA-256。
- 发布标签必须与 `frontend/package.json` 的版本严格一致；不要复用或覆盖已经公开的版本标签。
- 上传前核对 GitHub Release 的版本、DMG 文件名与 SHA-256 校验值一致。
- 运行 `python scripts/check_public_release_tree.py`，确认没有本机资料、报告或常见凭据进入公开树和将要发布的分支/标签历史。
- 使用明确的分支和标签推送；不要使用 `git push --mirror`。本机的恢复与开发工具引用不属于发布面。
- 公开版保持 `MINIPROGRAM_FORUM_CAPTURE_ENABLED=false`；不发布微信小程序视觉采集。
- 若启用封闭测试遥测，必须由测试者在“设置 → 隐私与诊断”主动开启；不配置收集端时只保留受限本机队列。
