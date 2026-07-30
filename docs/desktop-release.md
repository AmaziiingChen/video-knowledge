# 桌面端发布步骤

## 构建产物

在对应操作系统构建，不做跨平台伪构建：

```bash
# macOS Apple Silicon
cd frontend
npm run desktop:package:mac
```

```powershell
# Windows 11 x64
cd frontend
npm run desktop:package:win
```

前者生成 DMG，后者生成 NSIS 安装程序，均在 `frontend/dist/`。它们是可下载的安装包，不启用自动下载、静默安装或一键更新。

## 下载页与手动更新

1. 上传本次 DMG、NSIS 文件、`release/download/index.html` 和从 `release/manifest.template.json` 填写的版本清单到同一官方 HTTPS 域名。
2. 将下载页中的两个链接替换为本次的实际文件链接，并写入版本号与 SHA-256 校验值。
3. 在发行包的 `settings.env` 或受控运行环境中配置 `RELEASE_MANIFEST_URL=https://<官方域名>/manifest.json`；可选配置 `DOWNLOAD_PAGE_URL` 作为清单中的下载页回退地址。
4. 启动应用确认“有可用更新”只显示提示，用户点击“打开下载页”后才调用系统浏览器；应用本身不下载、不替换任何文件。

## 发布前清单

- macOS：在干净账户安装 DMG、启动并复启；未签名/未公证的系统提示必须在下载页明确告知。
- Windows：执行 [Windows v1 真机验收](windows-v1-release.md)，并确认未签名安装器的系统提示已在下载页告知。
- 上传前核对版本清单的版本、下载页链接、文件哈希与安装包实际名称一致。
- 公开版保持 `MINIPROGRAM_FORUM_CAPTURE_ENABLED=false`；不发布微信小程序视觉采集。
- 若启用封闭测试遥测，必须由测试者在“设置 → 隐私与诊断”主动开启；不配置收集端时只保留受限本机队列。
