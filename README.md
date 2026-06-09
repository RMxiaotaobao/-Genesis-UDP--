# 智能车变量监视器 v3

一个用于智能车调试的 UDP 上位机工具，支持实时变量监视、波形显示、双向调参、CSV 记录、变量名称/值映射，以及内嵌 MJPEG 图传预览。

## 功能

- 通过 UDP 接收下位机发送的 `name:value,name:value` 格式遥测数据
- 表格实时显示变量当前值、上次值、变化量、最小值、最大值和平均值
- 支持单曲线、叠加图和仪表盘视图
- 支持向下位机发送单参数或批量调参命令
- 支持变量显示名、枚举值映射和数值格式配置
- 支持 CSV 数据记录
- 支持内嵌 MJPEG 图传预览

## 运行环境

- Python 3.8+
- Windows/Linux/macOS 均可运行 Tkinter 主程序，图传功能需要 OpenCV 和 Pillow

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

运行：

```powershell
python .\variable_monitor_v3.py
```

## 下位机数据格式

上位机默认接收 UTF-8 文本 UDP 报文：

```text
speed_L:12.3,speed_R:12.1,err:-3.4,state:0
```

下位机侧可参考：

- `loongson2k301/user/udp_tuner.hpp`
- `loongson2k301/user/udp_tuner.cpp`

## 配置

配置文件为 `config.json`。常用字段：

- `udp_port`: 上位机监听端口
- `stream_url`: MJPEG 图传地址
- `name_map`: 变量原始名到显示名的映射
- `value_map`: 枚举/状态变量的值映射
- `var_types`: 变量显示格式，例如 `int`、`float1`、`float2`、`float3`、`enum`

## 打包

项目包含 PyInstaller 配置：

```powershell
pyinstaller ".\智能车变量监视器v3.spec"
```

## 许可证

本项目使用 MIT License。
