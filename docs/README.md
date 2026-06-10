# Genesis 智能车队 UDP 图传调试助手

<p align="center">
  <img src="https://img.shields.io/badge/version-v3.0-blue" alt="version">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license">
  <img src="https://img.shields.io/badge/python-3.8+-yellow" alt="python">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey" alt="platform">
</p>

<p align="center">
  <strong>让调试像看视频一样直观</strong>
</p>

---

## 📖 简介

Genesis UDP 图传调试助手是一款专为智能车队设计的调试工具，支持实时变量监视、波形显示、双向调参、MJPEG 图传和数据记录。

**开发者**：RMxiaotaobao
**团队**：华东交通大学起源 Genesis 智能车队

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 📊 **实时变量监视** | 表格化显示变量当前值、变化量、统计值 |
| 📈 **波形可视化** | 单曲线、叠加图、仪表盘多种视图 |
| 🎯 **双向调参** | PC 端实时修改下位机参数，无需重新烧录 |
| 📹 **MJPEG 图传** | 浏览器实时查看摄像头画面 |
| 💾 **CSV 记录** | 数据自动保存，赛后分析有据可依 |
| 🔄 **变量重映射** | 自定义变量显示名称和枚举值 |
| 🌙 **深色模式** | 保护眼睛，适合长时间调试 |

---

## 🚀 快速开始

### 方式一：下载可执行程序（推荐）

从 [GitHub Releases](https://github.com/RMxiaotaobao/ECJTU-Genesis-UDP-Debug-Assistant/releases) 下载：

- `genesis-udp-video-debug-assistant-windows.zip` - 完整包
- `genesis-udp-video-debug-assistant.exe` - 仅主程序
- `lan-scanner.exe` - 局域网扫描工具

### 方式二：从源码运行

```bash
# 克隆仓库
git clone git@github.com:RMxiaotaobao/ECJTU-Genesis-UDP-Debug-Assistant.git
cd ECJTU-Genesis-UDP-Debug-Assistant

# 安装依赖
pip install -r requirements.txt

# 运行程序
python src/variable_monitor_v3.py
```

---

## 📋 系统要求

- **操作系统**：Windows 10/11、Linux、macOS
- **Python 版本**：3.8+（源码运行时）
- **网络**：与下位机在同一局域网
- **依赖库**：tkinter、socket、csv、json（标准库）

---

## 🔧 下位机配置

### 数据发送格式

```
name1:value1,name2:value2,name3:value3
```

**示例**：
```
speed_L:12.345,speed_R:11.234,err:-3.000,kp:1.000
```

### 代码示例

```cpp
#include "udp_tuner.hpp"

int main() {
    // 创建调参器（PC 的 IP 和端口）
    UdpTuner tuner("192.168.101.101", 8080);
    if (!tuner.init()) {
        printf("UDP 初始化失败!\n");
        return -1;
    }

    double speed = 0.0;
    while (true) {
        speed += 0.1;

        // 构造参数列表
        std::vector<ParamValue> params = {
            {"speed", speed},
            {"error", 0.0},
            {"kp", 1.0}
        };

        // 发送
        tuner.send_data(params);

        usleep(10000);  // 10ms 间隔
    }

    return 0;
}
```

### 图传配置

```cpp
#include "lq_net_image_trans.hpp"
#include "lq_camera_ex.hpp"

int main() {
    // 启动 HTTP 服务器
    lq_http_image_server server(8080);

    // 初始化摄像头
    lq_camera_ex cam(160, 120, 120, LQ_CAMERA_0CPU_MJPG);

    // 主循环
    while (true) {
        cv::Mat frame = cam.get_frame_raw();
        if (!frame.empty()) {
            server.push_frame(frame, 50);
        }
    }

    return 0;
}
```

**访问方式**：浏览器打开 `http://<板卡IP>:8080`

---

## 📁 项目结构

```
.
├── src/                            # 源码目录
│   ├── variable_monitor_v3.py      # 主程序
│   └── config.json                 # 默认配置
├── docs/                           # 文档目录
│   ├── README.md                   # 项目说明
│   ├── CHANGELOG.md                # 更新日志
│   ├── CONTRIBUTING.md             # 贡献指南
│   ├── LICENSE                     # 开源协议
│   ├── 使用说明.md                  # 详细使用说明
│   ├── 宣传海报.md                  # 项目宣传海报
│   └── 图传与UDP传参说明文档.md      # 下位机实现详解
├── tools/                          # 辅助工具
│   └── lan_scanner.py              # 局域网扫描工具
├── scripts/                        # 构建脚本
├── packaging/                      # PyInstaller 打包配置
├── loongson2k301/user/             # 下位机参考代码
│   ├── udp_tuner.hpp               # 调参器头文件
│   └── udp_tuner.cpp               # 调参器实现
├── requirements.txt                # 运行依赖
└── requirements-dev.txt            # 开发/打包依赖
```

---

## ⚙️ 配置说明

配置文件为 `config.json`，常用配置项：

```json
{
  "udp_port": 8080,
  "stream_url": "http://192.168.101.101:8080/stream",
  "show_splash": true,
  "dark_mode": false,
  "name_map": {
    "speed_L": "左轮速度",
    "speed_R": "右轮速度",
    "err": "误差"
  },
  "value_map": {
    "state": {
      "0": "停止",
      "1": "运行",
      "2": "调试"
    }
  },
  "var_types": {
    "speed_L": "float2",
    "state": "enum"
  }
}
```

---

## 📚 文档

- **[详细使用说明](详细使用说明.md)** - 详细使用指南
- **[宣传海报](宣传海报.md)** - 项目介绍海报
- **[下位机图传与UDP传参整体架构示例](下位机图传与UDP传参整体架构示例（仅供参考）.md)** - 下位机实现详解
- **[更新日志](CHANGELOG.md)** - 版本更新记录
- **[贡献指南](CONTRIBUTING.md)** - 如何参与贡献

---

## 🤝 参与贡献

我们欢迎所有形式的贡献！

### 如何贡献

1. **使用** - 用起来，发现问题
2. **反馈** - [Issues](https://github.com/RMxiaotaobao/ECJTU-Genesis-UDP-Debug-Assistant/issues) 提交 Bug 或建议
3. **代码** - Fork → Branch → PR

### 贡献流程

```bash
# 1. Fork 仓库
# 2. 创建功能分支
git checkout -b feature/your-feature

# 3. 提交更改
git commit -m "Add your feature"

# 4. 推送分支
git push origin feature/your-feature

# 5. 创建 Pull Request
```

---

## 🐛 常见问题

### Q: 上位机收不到数据？

1. 检查网络连通性：`ping <板卡IP>`
2. 确认 IP 地址正确：`TARGET_IP` 必须是 **PC 的 IP**
3. 确认端口一致
4. 检查防火墙设置

### Q: 波形显示卡顿？

1. 降低发送频率（从 100Hz 降到 50Hz）
2. 减少变量数量
3. 关闭不需要的视图模式

### Q: 图传画面延迟高？

1. 降低 JPEG 质量（从 50 降到 30）
2. 降低分辨率（从 320x240 改为 160x120）
3. 使用 UDP 直传替代 HTTP

---

## 📄 许可证

本项目使用 [MIT License](LICENSE)。

---

## 🙏 致谢

感谢华东交通大学起源 Genesis 智能车队的所有成员！

---

## 🙏 致谢

感谢华东交通大学起源 Genesis 智能车队的所有成员！

---

<p align="center">
  <strong>调试无阻，开发无忧</strong>
  <br>
  <em>—— RMxiaotaobao</em>
</p>

---

<p align="center">
  <strong>Genesis 智能车队 · 内部开源</strong>
</p>
