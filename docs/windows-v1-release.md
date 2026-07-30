# Windows v1 发布与真机验收

## 支持范围

Windows v1 支持资料库、持久化任务队列、Paddle OCR 云端调用、`faster-whisper` 转写、AI 总结、本地搜索与 Obsidian 文件夹同步。桌面数据保存在 Windows 的用户应用数据目录，不与 macOS 数据目录共享。

下列能力不属于 Windows v1：

- 微信小程序视觉采集；它是 macOS 原生 ScreenCaptureKit/Vision 集成，公开版也默认关闭。
- macOS Vision OCR 辅助工具；Windows 保留 Paddle OCR 云端路径。
- 依赖 macOS Keychain 的 Telegram 与微信发布凭据流程；在引入 Windows Credential Manager 的安全存储实现前，不作为 Windows 发布承诺。

## Windows 构建

必须在 Windows 11 x64 真机或受控 Windows 构建代理上执行，不能从 macOS 交叉产出可发布包。准备 Python 3.11+、Node.js LTS、`ffmpeg` 与 `yt-dlp`，然后运行：

```powershell
cd <仓库根目录>
./scripts/verify_windows_desktop.ps1
```

脚本会安装依赖、执行核心回归测试、构建前端、打包 Python 后端，并用 electron-builder 生成 NSIS 安装包。产物位于 `frontend/dist/KnowledgeHub-<版本>-win-x64.exe`。安装器为按用户安装、可选择目录的 NSIS 包，不包含自动更新器。

仅做快速验证时可跳过依赖安装或打包：

```powershell
./scripts/verify_windows_desktop.ps1 -SkipInstall -SkipPackage
```

## 真机发布门禁

每个候选版本在干净 Windows 11 x64 用户账户完成以下检查，并保留测试记录：

1. 双击 NSIS 安装包，使用默认安装目录完成安装、启动、退出和再次启动。
2. 工作台打开后，导入一条测试来源并确认任务进入队列；取消、重试与历史记录正常。
3. 用短测试媒体完成 `faster-whisper` 转写；确认模型下载、缓存与失败提示可用。
4. 用测试凭据执行一次 Paddle OCR，确认只保存业务结果，不把令牌写进日志或遥测。
5. 配置一个临时 Obsidian vault，确认创建、更新和冲突提示均正确。
6. 搜索已导入资料，确认 Windows 文件路径、中文文件名和索引恢复正常。
7. 确认“微信小程序视觉采集”入口不存在，并直接访问其本机 API 返回未开放。
8. 设置 `ffmpeg`、`yt-dlp` 路径或采用发行包约定的可执行文件，验证下载/媒体失败时可操作的提示。
9. 在无网络、无 AI Key、Paddle Token 失效三种条件下启动，确认应用不白屏、错误不会阻塞资料库。
10. 卸载后确认用户数据保留/删除提示符合发布说明；不得静默清除资料库或 Obsidian vault。

通过上述门禁后，才能将 NSIS 产物上传到官方下载页。
