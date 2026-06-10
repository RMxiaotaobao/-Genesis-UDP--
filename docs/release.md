# 发布流程

本项目源码通过 Git 管理，Windows 可执行程序通过 GitHub Releases 分发。

- 工作室/团队：华东交通大学起源 Genesis 智能车队
- 开发者：RMxiaotaobao

## 发布前检查

```powershell
git status --short
python -m pip install -r requirements-dev.txt
.\scripts\build.ps1
```

确认 `dist/` 目录生成以下文件：

- `genesis-udp-video-debug-assistant-windows.zip`
- `genesis-udp-video-debug-assistant.exe`
- `lan-scanner.exe`

## 创建版本标签

示例：

```powershell
git tag v3.0.0
git push origin main
git push origin v3.0.0
```

## GitHub Release

在 GitHub 仓库页面创建 Release：

- Tag: `v3.0.0`
- Title: `Genesis 智能车队 UDP 图传调试助手 v3.0.0`
- Assets: 推荐上传 `dist/genesis-udp-video-debug-assistant-windows.zip`
- Description: 建议写明团队、开发者、主要功能和本次变更

可执行程序不要提交到 Git 仓库，保持 `dist/` 只作为本地构建输出。
