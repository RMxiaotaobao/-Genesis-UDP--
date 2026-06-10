# 贡献指南

感谢关注本项目。提交代码前请先确认：

- 代码可以通过 `python -m py_compile variable_monitor_v3.py tools/lan_scanner.py`
- 默认配置 `config.json` 可以被 Python JSON 解析
- 新增运行产物、日志、截图、打包输出不要提交到 Git
- 涉及界面文字或协议格式的变更，请同步更新 `README.md`

## 开发流程

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m py_compile variable_monitor_v3.py tools/lan_scanner.py
```

## 提交建议

提交信息建议使用简短动词开头，例如：

- `Fix UDP parsing for empty packets`
- `Add stream reconnect option`
- `Document PyInstaller packaging`

