# 图传与 UDP 传参系统说明文档

> **适用平台**：龙芯 2K0300 / 2K0301  
> **作者**：RMxiaotaobao  
> **最后更新**：2026-06-10

本文档说明项目中的图像传输、UDP 传参、统一发送线程和断网保护模块，适合用于功能移植、上位机对接、联调排错和后续维护。

## 快速索引

| 目标 | 推荐阅读 |
|------|----------|
| 了解整体工作方式 | [1. 系统概述](#1-系统概述)、[2. 架构总览](#2-架构总览) |
| 只移植 UDP 调参 | [5. UDP 传参实现详解](#5-udp-传参实现详解)、[8. 移植指南](#8-移植指南) |
| 做浏览器图传 | [4.2 HTTP MJPEG 推流](#42-方案二http-mjpeg-推流) |
| 对接 LoongHost / VOFA+ | [10. 上位机对接说明](#10-上位机对接说明) |
| 排查网络或端口问题 | [11. 常见问题](#11-常见问题) |

---

## 目录

1. [系统概述](#1-系统概述)
2. [架构总览](#2-架构总览)
3. [模块清单与依赖关系](#3-模块清单与依赖关系)
4. [图传实现详解](#4-图传实现详解)
   - 4.1 [方案一：UDP 直传图像](#41-方案一udp-直传图像)
   - 4.2 [方案二：HTTP MJPEG 推流](#42-方案二http-mjpeg-推流)
5. [UDP 传参实现详解](#5-udp-传参实现详解)
   - 5.1 [底层 UDP 客户端](#51-底层-udp-客户端)
   - 5.2 [上层 UdpTuner 调参器](#52-上层-udptuner-调参器)
   - 5.3 [数据协议格式](#53-数据协议格式)
6. [UdpSendThread 统一发送线程](#6-udpsendthread-统一发送线程)
7. [断网保护模块](#7-断网保护模块)
8. [移植指南](#8-移植指南)
   - 8.1 [编译依赖](#81-编译依赖)
   - 8.2 [文件拷贝清单](#82-文件拷贝清单)
   - 8.3 [编译宏配置](#83-编译宏配置)
   - 8.4 [网络配置](#84-网络配置)
9. [完整使用示例](#9-完整使用示例)
   - 9.1 [示例1：UDP 直传图像](#91-示例1udp-直传图像)
   - 9.2 [示例2：HTTP MJPEG 图传](#92-示例2http-mjpeg-图传)
   - 9.3 [示例3：UDP 双向调参](#93-示例3udp-双向调参)
   - 9.4 [示例4：VOFA+ 波形显示](#94-示例4vofa-波形显示)
   - 9.5 [示例5：图传+调参+断网保护集成](#95-示例5图传调参断网保护集成)
10. [上位机对接说明](#10-上位机对接说明)
11. [常见问题](#11-常见问题)

---

## 1. 系统概述

本系统实现了两套独立的网络通信功能：

| 功能 | 用途 | 协议 | 典型场景 |
|------|------|------|----------|
| **图传** | 将摄像头画面实时传送到 PC | UDP 直传 / HTTP MJPEG | 调试画面查看、自动驾驶视觉监控 |
| **UDP 传参** | 双向传输参数数据 | UDP 文本 / VOFA+ JustFloat | PID 调参、实时变量监控、远程指令下发 |

两套系统可以独立使用，也可以通过 `UdpSendThread` 统一管理，实现图传 + 遥测数据的并发发送。

---

## 2. 架构总览

```text
┌──────────────────────┐
│  生产者 / Producer   │
├──────────────────────┤
│ 摄像头采集、图像处理 │
│ PID 控制、电机驱动   │
└──────────┬───────────┘
           │
           │ push_image()
           │ push_telemetry()
           ▼
┌──────────────────────────────────────────────┐
│          UdpSendThread，1ms 轮询              │
├──────────────┬──────────────┬────────────────┤
│ 图像 30fps   │ 遥测 100Hz   │ Debug 遥测 30fps │
└──────┬───────┴──────┬───────┴────────┬───────┘
       │              │                │
       ▼              ▼                ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│ HTTP MJPEG │  │ UDP 文本   │  │ UDP 文本   │
│ :8080      │  │ 遥测发送   │  │ Debug 发送 │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      ▼               ▼               ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│ 浏览器     │  │ LoongHost  │  │ LoongHost  │
│ 查看画面   │  │ 波形显示   │  │ 变量监视   │
└────────────┘  └────────────┘  └────────────┘

PC 上位机 ── UDP 指令 ──▶ UdpTuner::receive_command()
                         └─ 参数更新到控制回路
```

---

## 3. 模块清单与依赖关系

### 3.1 核心库层

位置：`libraries/drv/`

| 文件 | 类 / 功能 | 依赖 |
|------|---------|------|
| `inc/lq_udp_client.hpp` | `lq_udp_client`，UDP socket 封装 | POSIX socket，可选 OpenCV |
| `src/lq_udp_client.cpp` | UDP 客户端实现 | - |
| `inc/lq_net_image_trans.hpp` | `lq_http_image_server`，HTTP MJPEG 服务器 | POSIX socket、OpenCV、pthread |
| `src/lq_net_image_trans.cpp` | HTTP 服务器实现 | - |

### 3.2 应用层

位置：`user_app/`

| 文件 | 类 / 功能 | 依赖 |
|------|---------|------|
| `inc/udp_tuner.hpp` | `UdpTuner`，双向调参器 | `lq_udp_client` |
| `src/udp_tuner.cpp` | 调参器实现 | - |
| `inc/udp_send_thread.hpp` | `UdpSendThread`，统一发送线程 | `UdpTuner`、`lq_http_image_server` |
| `src/udp_send_thread.cpp` | 发送线程实现 | - |
| `inc/network_protect.hpp` | 断网保护接口 | system ping |
| `src/network_protect.cpp` | 断网保护实现 | `Control.hpp` |

### 3.3 依赖关系

```text
lq_udp_client
├── UdpTuner
└── lq_http_image_server
    └── UdpSendThread
        └── network_protect
```

---

## 4. 图传实现详解

### 4.1 方案一：UDP 直传图像

**原理**：将图像 JPEG 编码后，通过 UDP 数据报直接发送。协议格式为 `4字节长度头 + JPEG数据`。

**适用场景**：低延迟、简单调试、配合专用上位机（LoongHost.exe）。

**协议格式**：

```
┌──────────────┬──────────────────────────────┐
│  4 字节长度   │     JPEG 数据 (变长)          │
│  (小端序)     │                              │
└──────────────┴──────────────────────────────┘
```

- 长度字段为 `uint32_t`，小端序（little-endian），表示后续 JPEG 数据的字节数
- JPEG 数据为 `cv::imencode(".jpg", ...)` 的直接输出

**核心函数**：

```cpp
// lq_udp_client 成员函数
ssize_t udp_send_image(const cv::Mat& _img, int _quality = 80);
```

**实现流程**：

```
cv::Mat → cv::imencode(".jpg") → [4字节长度] + [JPEG数据] → sendto()
```

**注意事项**：
- 160x120 分辨率 + quality=30 时，JPEG 约 2~5KB，单个 UDP 数据报可承载
- 分辨率或质量提高后，JPEG 可能超过 UDP 的 ~64KB 实际限制，需改用 HTTP 方案
- UDP 不保证可靠性，网络拥塞时会丢帧，但延迟最低

---

### 4.2 方案二：HTTP MJPEG 推流

**原理**：实现一个轻量级 HTTP 服务器，使用 MJPEG（`multipart/x-mixed-replace`）协议持续推送 JPEG 帧到浏览器。

**适用场景**：多客户端查看、无需安装上位机、浏览器直接访问。

**访问方式**：浏览器打开 `http://<板卡IP>:8080` 即可看到实时画面。

**核心类**：`lq_http_image_server`

```cpp
class lq_http_image_server {
public:
    bool start(uint16_t port = 8080);              // 启动服务器
    void stop() noexcept;                           // 停止服务器
    bool push_frame(const cv::Mat& img, int quality = 50);  // 推送一帧
    bool is_running() const noexcept;               // 是否运行中
    uint16_t get_port() const noexcept;             // 获取端口
};
```

**实现细节**：

| 项目 | 说明 |
|------|------|
| 监听方式 | TCP 端口，默认 `8080`，非阻塞 `accept` + 1ms 轮询 |
| 客户端处理 | 每个客户端连接在独立 `detached thread` 中处理 |
| 页面入口 | `GET /` 返回带样式的 HTML 查看页面 |
| 视频流入口 | `GET /stream` 返回 MJPEG 持续流 |
| 性能优化 | 相同帧自动跳过；无客户端连接时跳过 JPEG 编码 |
| 超时策略 | 45 秒空闲自动断开客户端 |
| 跨域支持 | `Access-Control-Allow-Origin: *` |

**HTTP 响应头**：

```
HTTP/1.1 200 OK
Content-Type: multipart/x-mixed-replace; boundary=frame
Connection: keep-alive
Cache-Control: no-cache, no-store, must-revalidate
Access-Control-Allow-Origin: *
```

**MJPEG 帧格式**：

```
--frame\r\n
Content-Type: image/jpeg\r\n
Content-Length: <JPEG字节数>\r\n
\r\n
<JPEG二进制数据>
\r\n
```

---

## 5. UDP 传参实现详解

### 5.1 底层 UDP 客户端

**核心类**：`lq_udp_client`

```cpp
class lq_udp_client {
public:
    lq_udp_client() noexcept;
    lq_udp_client(const std::string _ip, uint16_t _port);
    ~lq_udp_client();

    void    udp_client_init(const std::string _ip, uint16_t _port);
    ssize_t udp_send(const void* _buf, size_t _len);     // 发送原始数据
    ssize_t udp_recv(void* _buf, size_t _len);            // 接收原始数据
    ssize_t udp_send_string(const std::string& _str);     // 发送字符串
    ssize_t udp_send_image(const cv::Mat& _img, int _quality = 80);  // 发送图像
    int     get_udp_socket_fd() const noexcept;
    void    udp_close() noexcept;
};
```

**Socket 配置**：
- `AF_INET` + `SOCK_DGRAM`（IPv4 UDP）
- `SO_REUSEADDR` 端口复用
- `sendto()` 使用 `MSG_DONTWAIT` 非阻塞标志
- 所有操作通过 `std::mutex` 保护线程安全

---

### 5.2 上层 UdpTuner 调参器

**核心类**：`UdpTuner`，封装了双向调参协议。

```cpp
class UdpTuner {
public:
    UdpTuner(const std::string& target_ip, uint16_t port);
    bool init();    // 初始化（创建socket + 绑定本地端口用于接收）

    // 发送方向：设备 → PC
    bool send_data(const std::vector<ParamValue>& params);  // 字符串协议
    bool send_justfloat(const float* values, size_t count);  // VOFA+ JustFloat 协议
    bool send_pid_data(double target, double actual, double output,
                       double kp, double ki, double kd);    // PID 便捷接口

    // 接收方向：PC → 设备
    bool receive_command(std::map<std::string, double>& param_map);
};
```

**参数结构体**：

```cpp
struct ParamValue {
    std::string name;   // 参数名称（任意字符串）
    double value;       // 参数值
};
```

**初始化流程**：

```
1. 创建 UDP socket (SOCK_DGRAM)
2. 配置目标地址 (PC的IP和端口)
3. bind 到本地端口 (INADDR_ANY) 以接收数据
4. 同一端口同时用于发送和接收
```

---

### 5.3 数据协议格式

#### 协议 A：文本键值对（默认协议）

**发送格式**（设备 → PC）：

```
name1:value1,name2:value2,name3:value3
```

- 逗号 `,` 分隔不同参数
- 冒号 `:` 分隔参数名和值
- 值为浮点数，`%.3f` 格式（3位小数）

**示例**：

```
speed_L:12.345,speed_R:11.234,err:-3.000,pos_out:45.678
```

**接收格式**（PC → 设备）：

```
param1:100.0,param2:200.0
```

- 格式与发送相同
- 特殊格式 `move:value1,value2` 会被解析为 `move_a` 和 `move_b` 两个参数

**兼容上位机**：原创智能车变量监视器、LoongHost.exe

---

#### 协议 B：VOFA+ JustFloat 二进制协议

**帧格式**：

```
┌──────────────────────┬──────────────────────┐
│  N 个 float (小端序)  │  帧尾 4字节           │
│  每个 4 字节          │  0x00 0x00 0x80 0x7f │
└──────────────────────┴──────────────────────┘
```

- float 数据为小端序（little-endian）原生内存布局
- 帧尾固定为 `{0x00, 0x00, 0x80, 0x7f}`

**发送代码**：

```cpp
float values[] = {1.0f, 2.5f, -3.7f};
udp_tuner.send_justfloat(values, 3);
```

**兼容上位机**：VOFA+（选择 JustFloat 协议，UDP 模式）

---

## 6. UdpSendThread 统一发送线程

`UdpSendThread` 是生产者-消费者模式的消费者线程，统一管理图传和遥测数据的发送频率。

```cpp
class UdpSendThread {
public:
    UdpSendThread(lq_http_image_server* http_server, UdpTuner* tuner);

    // 生产者接口（非阻塞，可从任意线程调用）
    void push_image(const cv::Mat& img);                    // 推送图像
    void push_telemetry(std::vector<ParamValue> params);    // 推送控制遥测
    void push_telemetry_debug(std::vector<ParamValue> params);  // 推送Debug遥测
};
```

**频率控制**（通过宏定义配置）：

| 通道 | 宏定义 | 默认频率 | 发送方式 |
|------|--------|----------|----------|
| 图像 | `UDP_SEND_IMAGE` | 30fps (33ms) | HTTP MJPEG |
| 控制遥测 | `UDP_SEND_TELEMETRY` | 100Hz (10ms) | UDP 文本 |
| Debug遥测 | `UDP_SEND_TELEMETRY_DEBUG` | 30fps (33ms) | UDP 文本 |

**线程安全机制**：

- 每个通道独立的 `std::mutex` + `std::atomic<bool> ready`
- 生产者：`lock_guard` 写入 buffer，设置 `ready = true`
- 消费者：检查 `ready`，加锁取出 buffer，设置 `ready = false`
- 1ms 轮询间隔，有新数据且达到发送间隔时才发送

**开关控制**：注释掉对应的宏即可关闭该通道

```cpp
#define UDP_SEND_IMAGE              // 开启图传
#define UDP_SEND_TELEMETRY          // 开启控制遥测
#define UDP_SEND_TELEMETRY_DEBUG    // 开启Debug遥测
```

---

## 7. 断网保护模块

远程控制场景下，网络断开可能导致失控。断网保护模块通过后台 ping 检测网关连通性，连续失败超过阈值时触发紧急停车。

```cpp
// 配置
void NP_netSetGateway(const char* ip);     // 设置网关IP
void NP_netSetInterval(uint32_t ms);       // ping间隔（默认500ms）
void NP_netSetTimeout(uint32_t ms);        // ping超时（默认300ms）
void NP_netSetFailCount(uint32_t count);   // 失败阈值（默认3次）

// 控制
bool NP_netProtectStart(void);             // 启动保护
bool NP_netProtectStop(void);              // 停止保护
void NP_netProtectReset(void);             // 解除停车状态

// 查询
bool NP_netIsAlive(void);                  // 网络是否正常
bool NP_netIsStopped(void);                // 是否处于断网停车
uint32_t NP_netGetFailCount(void);         // 当前连续失败次数
```

**停车范围**：电机停转 + 负压风扇停转

**工作流程**：

```
后台线程 (500ms间隔)
    │
    ├─ ping -c 1 -W 1 <网关IP>
    │
    ├─ 成功 → 重置失败计数
    │
    └─ 失败 → 计数+1
              │
              └─ 达到阈值 → 触发紧急停车
```

---

## 8. 移植指南

### 8.1 编译依赖

| 依赖 | 必需 | 说明 |
|------|------|------|
| POSIX socket | 是 | `<sys/socket.h>`, `<arpa/inet.h>` |
| pthread | 是 | `<thread>`, `<mutex>`, `<atomic>` |
| OpenCV | 图传必需 | `cv::Mat`, `cv::imencode` |
| C++17 | 是 | `std::lock_guard`, structured bindings |

**编译选项**：

```bash
# 如果使用图传功能，需要定义 LQ_HAVE_OPENCV
g++ -std=c++17 -DLQ_HAVE_OPENCV ... `pkg-config --cflags --libs opencv4`

# 如果只使用 UDP 传参（不需要图传），可以不依赖 OpenCV
g++ -std=c++17 ...
```

### 8.2 文件拷贝清单

**最小移植（仅 UDP 传参）**：

```
libraries/drv/inc/lq_udp_client.hpp
libraries/drv/src/lq_udp_client.cpp
user_app/inc/udp_tuner.hpp
user_app/src/udp_tuner.cpp
```

**完整移植（图传 + 传参）**：

```
libraries/drv/inc/lq_udp_client.hpp
libraries/drv/src/lq_udp_client.cpp
libraries/drv/inc/lq_net_image_trans.hpp
libraries/drv/src/lq_net_image_trans.cpp
user_app/inc/udp_tuner.hpp
user_app/src/udp_tuner.cpp
user_app/inc/udp_send_thread.hpp
user_app/src/udp_send_thread.cpp
user_app/inc/network_protect.hpp        # 可选：断网保护
user_app/src/network_protect.cpp        # 可选：断网保护
```

**还需要的头文件**（来自项目公共库）：

```
libraries/drv/inc/lq_common.hpp         # lq_auto_cleanup 基类
libraries/drv/inc/lq_signal_handle.hpp  # ls_system_running 全局退出标志
libraries/drv/inc/lq_assert.hpp         # lq_log_info/error/warn 日志宏
libraries/drv/inc/lq_camera_ex.hpp      # 摄像头封装（图传时需要）
```

### 8.3 编译宏配置

在 `udp_send_thread.hpp` 中配置发送通道开关：

```cpp
// 开启/关闭功能（注释掉即关闭）
#define UDP_SEND_IMAGE              // HTTP 图传
#define UDP_SEND_TELEMETRY          // 控制遥测（100Hz）
#define UDP_SEND_TELEMETRY_DEBUG    // Debug 遥测（30fps）

// 频率调整
#define UDP_IMG_INTERVAL_MS       33   // 图传间隔 (ms)
#define UDP_TELEM_INTERVAL_MS     10   // 控制遥测间隔 (ms)
#define UDP_TELEM_DBG_INTERVAL_MS 33   // Debug遥测间隔 (ms)
```

### 8.4 网络配置

**板卡端**：确保板卡有有效的网络连接（以太网或 WiFi）。

**PC 端**：确保 PC 与板卡在同一网段。

**IP 配置**：

```cpp
// 在 main.hpp 或你的配置头文件中定义
#define TARGET_IP  "192.168.101.101"   // PC 端 IP 地址

// 或在代码中直接指定
const std::string TARGET_IP = "192.168.101.101";
const uint16_t    TARGET_PORT = 8080;
```

---

## 9. 完整使用示例

### 9.1 示例1：UDP 直传图像

最简方案，使用专用上位机（LoongHost.exe）接收。

```cpp
#include "lq_udp_client.hpp"
#include "lq_camera_ex.hpp"
#include "lq_signal_handle.hpp"

void demo_udp_image()
{
    // 1. 配置参数
    const std::string TARGET_IP   = "192.168.101.101";  // PC 端 IP
    const uint16_t    TARGET_PORT = 8080;
    const int         JPEG_QUALITY = 30;  // JPEG 质量 (1-100)

    // 2. 初始化 UDP 客户端
    lq_udp_client udp_client(TARGET_IP, TARGET_PORT);

    // 3. 初始化摄像头 (160x120, 120fps, MJPEG模式)
    lq_camera_ex cam(160, 120, 120, LQ_CAMERA_0CPU_MJPG);
    if (!cam.is_cam_opened()) {
        printf("ERROR: 摄像头打开失败!\n");
        return;
    }

    // 4. 主循环：采集并发送
    printf("图传开始，按 Ctrl+C 停止\n");
    while (ls_system_running.load()) {
        cv::Mat frame = cam.get_frame_raw();
        if (frame.empty()) continue;

        // 发送 JPEG 压缩图像
        udp_client.udp_send_image(frame, JPEG_QUALITY);
    }
}
```

**上位机端**：运行 LoongHost.exe，监听 UDP 8080 端口即可接收图像。

---

### 9.2 示例2：HTTP MJPEG 图传

浏览器直接查看，无需专用上位机。

```cpp
#include "lq_net_image_trans.hpp"
#include "lq_camera_ex.hpp"
#include "lq_signal_handle.hpp"

void demo_http_image()
{
    // 1. 启动 HTTP 服务器（端口 8080）
    lq_http_image_server server(8080);

    // 2. 初始化摄像头
    lq_camera_ex cam(320, 240, 120, LQ_CAMERA_0CPU_MJPG);
    if (!cam.is_cam_opened()) {
        printf("ERROR: 摄像头打开失败!\n");
        return;
    }

    // 3. 主循环：采集并推送
    printf("HTTP 图传启动，浏览器访问 http://<板卡IP>:8080\n");
    while (ls_system_running.load()) {
        cv::Mat frame = cam.get_frame_raw();
        if (frame.empty()) continue;

        // 推送帧到 HTTP 服务器（quality=50）
        server.push_frame(frame, 50);
    }
}
```

**使用方式**：

1. 运行程序
2. 在 PC 浏览器中打开 `http://<板卡IP>:8080`
3. 即可看到实时画面，支持多个浏览器同时查看

---

### 9.3 示例3：UDP 双向调参

PC 端发送参数到设备，设备回传实时数据。

```cpp
#include "udp_tuner.hpp"
#include "lq_signal_handle.hpp"
#include <map>

void demo_udp_tuner()
{
    const std::string TARGET_IP = "192.168.101.101";
    const uint16_t    TARGET_PORT = 8080;

    // 1. 创建并初始化调参器
    UdpTuner tuner(TARGET_IP, TARGET_PORT);
    if (!tuner.init()) {
        printf("ERROR: UDP 初始化失败!\n");
        return;
    }

    // 2. 模拟变量
    double kp = 1.0, ki = 0.1, kd = 0.05;
    double speed = 0.0, error = 0.0;

    printf("调参示例启动\n");
    printf("PC 端发送格式: kp:2.0,ki:0.5,kd:0.1\n");

    while (ls_system_running.load()) {
        // 3. 模拟业务逻辑
        speed += 0.1;
        error = sin(speed * 0.1) * 10.0;

        // 4. 发送数据到 PC（字符串格式）
        std::vector<ParamValue> params = {
            {"speed", speed},
            {"error", error},
            {"kp", kp},
            {"ki", ki},
            {"kd", kd}
        };
        tuner.send_data(params);

        // 5. 接收 PC 下发的参数
        std::map<std::string, double> recv;
        if (tuner.receive_command(recv)) {
            auto it = recv.find("kp");
            if (it != recv.end()) {
                kp = it->second;
                printf("kp 更新为: %.3f\n", kp);
            }
            it = recv.find("ki");
            if (it != recv.end()) {
                ki = it->second;
                printf("ki 更新为: %.3f\n", ki);
            }
            it = recv.find("kd");
            if (it != recv.end()) {
                kd = it->second;
                printf("kd 更新为: %.3f\n", kd);
            }
        }

        usleep(10000);  // 10ms 间隔
    }
}
```

**PC 端操作**：
- 使用 LoongHost.exe 或网络调试助手，向板卡 IP:8080 发送 UDP 数据
- 发送 `kp:2.0,ki:0.5,kd:0.1` 即可修改参数

---

### 9.4 示例4：VOFA+ 波形显示

使用 VOFA+ 上位机显示实时波形。

```cpp
#include "udp_tuner.hpp"
#include "lq_signal_handle.hpp"
#include <cmath>

void demo_vofa_waveform()
{
    const std::string TARGET_IP = "192.168.101.101";
    const uint16_t    TARGET_PORT = 8080;

    // 1. 初始化调参器（不需要接收功能时可不 bind）
    UdpTuner tuner(TARGET_IP, TARGET_PORT);
    tuner.init();

    printf("VOFA+ 波形示例启动\n");
    printf("VOFA+ 设置: 协议=JustFloat, 传输=UDP, 端口=%d\n", TARGET_PORT);

    float t = 0.0f;

    while (ls_system_running.load()) {
        // 2. 准备 float 数据（VOFA+ 会为每个 float 显示一条曲线）
        float values[] = {
            sinf(t) * 100.0f,          // 通道0: 正弦波
            cosf(t) * 50.0f,           // 通道1: 余弦波
            fmodf(t * 10.0f, 200.0f)   // 通道2: 锯齿波
        };

        // 3. 发送 JustFloat 帧
        tuner.send_justfloat(values, 3);

        t += 0.05f;
        usleep(10000);  // 10ms 间隔 → 100Hz 刷新率
    }
}
```

**VOFA+ 配置步骤**：

1. 打开 VOFA+，选择 `JustFloat` 协议
2. 传输方式选择 `UDP`，监听端口填 `8080`
3. 点击连接，即可看到 3 条实时波形

---

### 9.5 示例5：图传+调参+断网保护集成

完整集成示例，适用于远程控制小车场景。

```cpp
#include "lq_net_image_trans.hpp"
#include "lq_udp_client.hpp"
#include "udp_tuner.hpp"
#include "udp_send_thread.hpp"
#include "network_protect.hpp"
#include "lq_camera_ex.hpp"
#include "lq_signal_handle.hpp"

void demo_full_integration()
{
    const std::string TARGET_IP = "192.168.101.101";
    const uint16_t    TARGET_PORT = 8080;

    // ========== 1. 初始化各模块 ==========

    // HTTP 图传服务器
    lq_http_image_server http_server(8080);

    // UDP 调参器
    UdpTuner tuner(TARGET_IP, TARGET_PORT);
    if (!tuner.init()) {
        printf("ERROR: UDP 初始化失败!\n");
        return;
    }

    // 统一发送线程（管理图传+遥测频率）
    UdpSendThread sender(&http_server, &tuner);

    // 断网保护
    NP_netSetGateway("192.168.101.1");   // 网关 IP
    NP_netSetFailCount(3);               // 3次失败触发停车
    NP_netProtectStart();

    // 摄像头
    lq_camera_ex cam(160, 120, 120, LQ_CAMERA_0CPU_MJPG);

    // ========== 2. 主循环 ==========

    printf("集成示例启动\n");
    printf("图传: http://%s:8080\n", TARGET_IP.c_str());
    printf("遥测: UDP %s:%d\n", TARGET_IP.c_str(), TARGET_PORT);

    double kp = 1.0, ki = 0.0, kd = 0.0;
    double speed_L = 0, speed_R = 0;

    while (ls_system_running.load()) {
        // ---- 采集图像 ----
        cv::Mat frame = cam.get_frame_raw();
        if (!frame.empty()) {
            // 在图像上画一些处理结果（示例）
            cv::line(frame, {0, 60}, {160, 60}, {0, 255, 0}, 1);

            // 推送到发送线程（非阻塞）
            sender.push_image(frame);
        }

        // ---- 模拟控制逻辑 ----
        speed_L += 0.1;
        speed_R += 0.12;

        // ---- 推送控制遥测 ----
        std::vector<ParamValue> telemetry = {
            {"speed_L", speed_L},
            {"speed_R", speed_R},
            {"kp", kp}, {"ki", ki}, {"kd", kd}
        };
        sender.push_telemetry(telemetry);

        // ---- 接收 PC 指令 ----
        std::map<std::string, double> cmd;
        if (tuner.receive_command(cmd)) {
            auto it = cmd.find("kp");
            if (it != cmd.end()) kp = it->second;
            it = cmd.find("ki");
            if (it != cmd.end()) ki = it->second;
            it = cmd.find("kd");
            if (it != cmd.end()) kd = it->second;
        }

        // ---- 检查断网状态 ----
        if (NP_netIsStopped()) {
            printf("WARN: 断网停车已触发!\n");
            // 可在此等待网络恢复或执行其他安全逻辑
        }

        usleep(10000);  // 10ms
    }

    // ========== 3. 清理 ==========
    NP_netProtectStop();
    // http_server 和 tuner 析构时自动清理
}
```

---

## 10. 上位机对接说明

### 10.1 LoongHost.exe（原创智能车上位机）

| 功能 | 对接方式 |
|------|----------|
| 图传 | 监听 UDP `8080` 端口，自动解析 `4字节长度 + JPEG` |
| 波形 | 接收 `name:value` 文本格式，按名称显示曲线 |
| 调参 | 发送 `name:value` 文本格式，设备端自动解析 |

### 10.2 VOFA+

| 项目 | 配置 |
|------|------|
| 协议 | `JustFloat` |
| 传输方式 | `UDP` |
| 监听端口 | `8080` |
| 数据格式 | 每个 `float` 占 4 字节，小端序 |
| 帧尾 | `0x00 0x00 0x80 0x7f` |
| 曲线命名 | 每个 float 对应一条曲线，自动命名 `channel0`、`channel1` 等 |

### 10.3 浏览器（HTTP 图传）

- 直接访问 `http://<板卡IP>:8080`
- 支持 Chrome、Firefox、Edge 等现代浏览器
- 支持多客户端同时查看
- 无需安装任何软件

### 10.4 网络调试助手（通用 UDP 测试）

- **发送**：向 `<板卡IP>:8080` 发送文本 `param1:100.0,param2:200.0`
- **接收**：监听本地 UDP 8080 端口，接收设备回传的键值对数据

---

## 11. 常见问题

### Q1：图传画面卡顿或延迟高？

- 降低 JPEG 质量（`quality` 参数从 50 降到 30）
- 降低分辨率（如从 320x240 改为 160x120）
- 使用 UDP 直传方案替代 HTTP（延迟更低）
- 检查网络带宽是否足够

### Q2：UDP 数据收不到？

1. 确认板卡和 PC 在同一网段
2. 确认 PC 防火墙允许 UDP 8080 端口
3. 确认 `TARGET_IP` 是 PC 的 IP（不是板卡的）
4. 使用 `ping` 测试网络连通性

### Q3：如何同时使用 VOFA+ 和 LoongHost？

- VOFA+ 使用 `send_justfloat()` 发送二进制数据
- LoongHost 使用 `send_data()` 发送文本数据
- 两者可以同时使用，发送到不同端口，或交替发送到同一端口
- 建议使用 `UdpSendThread` 管理不同通道

### Q4：HTTP 图传服务器端口被占用？

```cpp
// 更换端口号
lq_http_image_server server(9090);  // 使用 9090 端口
// 浏览器访问 http://<IP>:9090
```

### Q5：如何自定义遥测数据？

在你的控制逻辑中构造 `ParamValue` 列表即可：

```cpp
std::vector<ParamValue> my_params = {
    {"my_variable_1", value1},
    {"my_variable_2", value2},
    // 任意数量，任意名称
};
sender.push_telemetry(my_params);  // 或 tuner.send_data(my_params)
```

参数名可以是任意字符串，上位机会按名称显示。

### Q6：断网保护误触发怎么办？

- 增大失败阈值：`NP_netSetFailCount(5)` （默认3次）
- 增大 ping 间隔：`NP_netSetInterval(1000)` （默认500ms）
- 检查网关 IP 是否正确：`NP_netSetGateway("192.168.101.1")`
