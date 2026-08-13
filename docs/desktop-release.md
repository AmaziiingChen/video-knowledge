# 桌面端发布步骤

## 构建产物

当前只发布 macOS Apple Silicon 版本，不做跨平台伪构建：

```bash
# macOS Apple Silicon
cd frontend
npm run desktop:package:mac
```

该命令生成 DMG，位于 `frontend/release/`。安装包不启用自动下载、静默安装或一键更新。
从 `0.1.3` 的发布桥接版开始，应用会在启动时读取固定的 Cloudflare
版本清单；当 GitHub Release 出现更高版本时，应用提示用户打开对应的
Release 页面自行下载并安装。关闭应用时无法接收系统级推送；下一次启动
或手动检查更新时才会显示提示。
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
- 新安装会在首次进入工作台时明确告知去标识诊断默认开启，并可在“设置 → 隐私与诊断”立即关闭。关闭会删除本机待发送数据与随机安装 ID，并保留退出偏好；手动替换 DMG 不会重新开启已退出用户。一旦遥测字段或用途变化，必须提升隐私说明版本、清除旧队列并重新告知。

## 后续版本更新

- GitHub Release 是唯一安装包来源。推送与 `frontend/package.json` 版本一致的
  `v<version>` 标签后，现有 Release 工作流会重新构建、校验并上传 DMG 与
  SHA-256。
- `knowledgehub-release-manifest` Worker 只读取仓库的公开 GitHub Latest Release
  API，并返回固定格式的版本号、官方 Release 页面和最多 500 个字符的说明；
  它不接收用户内容、凭据或遥测数据。版本清单最多缓存五分钟。
- 应用只接受编译内置的 Worker 地址，以及精确匹配
  `https://github.com/AmaziiingChen/video-knowledge/releases/tag/v<version>` 的下载页，
  不接受运行时替换的更新源或重定向。
- 当前 DMG 未使用 Developer ID 签名或 Apple 公证，因此更新采用“提示并打开
  Release 页面”的方式。若以后要做自动下载、替换和重启，必须先完成 Developer
  ID 签名、公证，并为已签名 ZIP/更新 feed 增加独立的发布验证；不要把 DMG 直接当作
  静默更新包。
