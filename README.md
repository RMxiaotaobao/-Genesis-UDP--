# ECJTU Genesis UDP 图传调试助手

<p align="center">
  <strong>让调试像看视频一样直观</strong>
</p>

---

## 📖 简介

Genesis UDP 图传调试助手是一款专为智能车队设计的调试工具，支持实时变量监视、波形显示、双向调参、MJPEG 图传和数据记录。

**开发者**：RMxiaotaobao
**团队**：华东交通大学起源 Genesis 智能车队

---

## 📚 文档

详细的使用说明和项目文档请查看 [docs 目录](docs/)：

- **[README.md](docs/README.md)** - 完整项目说明
- **[详细使用说明](docs/详细使用说明.md)** - 详细使用指南
- **[宣传海报](docs/宣传海报.md)** - 项目介绍海报
- **[下位机图传与UDP传参整体架构示例](docs/下位机图传与UDP传参整体架构示例（仅供参考）.md)** - 下位机实现详解
- **[更新日志](docs/CHANGELOG.md)** - 版本更新记录
- **[贡献指南](docs/CONTRIBUTING.md)** - 如何参与贡献

---

## 🚀 快速开始

### 下载可执行程序

从 [GitHub Releases](https://github.com/RMxiaotaobao/ECJTU-Genesis-UDP-Debug-Assistant/releases) 下载。

### 从源码运行

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

## 📁 项目结构

```
.
├── src/                            # 源码目录
├── docs/                           # 文档目录
├── tools/                          # 辅助工具
├── scripts/                        # 构建脚本
├── packaging/                      # 打包配置
├── loongson2k301/                  # 下位机参考
├── requirements.txt                # 运行依赖
└── requirements-dev.txt            # 开发依赖
```

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
