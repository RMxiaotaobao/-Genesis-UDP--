#include "udp_tuner.hpp"
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <iomanip>
#include <sstream>
#include <sys/select.h>
#include <errno.h>

/**
 * @brief 构造函数
 * @param target_ip 目标IP地址（PC端IP）
 * @param port UDP端口号
 */
UdpTuner::UdpTuner(const std::string& target_ip, uint16_t port)
    : target_ip_(target_ip), port_(port), socket_fd_(-1) {
}

/**
 * @brief 析构函数
 */
UdpTuner::~UdpTuner() {
}

/**
 * @brief 初始化UDP通信
 * @return true初始化成功，false初始化失败
 */
bool UdpTuner::init() {
    printf("Starting UDP tuner initialization...\r\n");
    
    // 初始化UDP客户端
    udp_client_.udp_client_init(target_ip_, port_);
    printf("UDP client initialized\r\n");
    
    // 获取UDP套接字文件描述符
    socket_fd_ = udp_client_.get_udp_socket_fd();
    if (socket_fd_ >= 0) {
        printf("UDP socket FD: %d\r\n", socket_fd_);
        
        // 绑定本地端口，以便接收数据
        struct sockaddr_in local_addr;
        memset(&local_addr, 0, sizeof(local_addr));
        local_addr.sin_family = AF_INET;
        local_addr.sin_port = htons(port_);  // 使用与发送相同的端口
        local_addr.sin_addr.s_addr = INADDR_ANY;  // 接收任意IP的连接
        
        if (bind(socket_fd_, (struct sockaddr*)&local_addr, sizeof(local_addr)) == 0) {
            printf("UDP socket bound to port %d\r\n", port_);
            return true;
        } else {
            printf("Failed to bind UDP socket: %s\r\n", strerror(errno));
            return false;
        }
    } else {
        printf("Failed to get UDP socket FD\r\n");
        return false;
    }
}

/**
 * @brief 发送参数数据到上位机（字符串格式）
 * @param params 参数名称值对列表
 * @return 发送成功返回true，失败返回false
 */
bool UdpTuner::send_data(const std::vector<ParamValue>& params) {
    if (socket_fd_ < 0) {
        printf("UDP send failed: socket not initialized\r\n");
        return false;
    }
    
    if (params.empty()) {
        printf("UDP send failed: no parameters to send\r\n");
        return false;
    }
    
    std::ostringstream oss;
    for (size_t i = 0; i < params.size(); ++i) {
        oss << params[i].name << ":" << std::fixed << std::setprecision(3) << params[i].value;
        if (i < params.size() - 1) {
            oss << ",";
        }
    }
    std::string send_str = oss.str();
    
    // printf("Sending: %s\r\n", send_str.c_str());
    
    ssize_t ret = udp_client_.udp_send_string(send_str);
    if (ret <= 0) {
        printf("UDP send failed: return value = %zd\r\n", ret);
        return false;
    }
    
    return true;
}

/**
 * @brief 发送数据到上位机（VOFA+ justfloat协议）
 * @param values float数据数组
 * @param count 数据个数
 * @return 发送成功返回true，失败返回false
 */
bool UdpTuner::send_justfloat(const float* values, size_t count) {
    if (socket_fd_ < 0 || values == nullptr || count == 0) {
        printf("UDP send failed: invalid parameters\r\n");
        return false;
    }
    
    // 发送float数据和VOFA+帧尾，UDP必须放在同一个报文中
    const uint8_t tail[4] = {0x00, 0x00, 0x80, 0x7f};
    std::vector<uint8_t> packet(count * sizeof(float) + sizeof(tail));
    memcpy(packet.data(), values, count * sizeof(float));
    memcpy(packet.data() + count * sizeof(float), tail, sizeof(tail));

    ssize_t ret = udp_client_.udp_send(packet.data(), packet.size());
    if (ret <= 0) {
        printf("UDP send failed: return value = %zd\r\n", ret);
        return false;
    }
    
    return true;
}

/**
 * @brief 发送PID数据到上位机（便捷版本）
 * @param target 目标值
 * @param actual 实际值
 * @param output 控制输出
 * @param kp 比例系数
 * @param ki 积分系数
 * @param kd 微分系数
 * @return 发送成功返回true，失败返回false
 */
bool UdpTuner::send_pid_data(double target, double actual, double output, double kp, double ki, double kd) {
    std::vector<ParamValue> params = {
        {"target", target},
        {"actual", actual},
        {"output", output},
        {"Kp", kp},
        {"Ki", ki},
        {"Kd", kd}
    };
    return send_data(params);
}

/**
 * @brief 接收并解析上位机指令
 * @param param_map 参数映射表，用于存储接收到的参数
 * @return 接收到有效指令返回true，无数据或解析失败返回false
 */
bool UdpTuner::receive_command(std::map<std::string, double>& param_map) {
    if (socket_fd_ < 0) {
        return false;
    }
    
    char recv_buf[256];
    
    // 使用select检查是否有数据可读
    fd_set readfds;
    FD_ZERO(&readfds);
    FD_SET(socket_fd_, &readfds);
    
    struct timeval timeout;
    timeout.tv_sec = 0;
    timeout.tv_usec = 1000; // 1ms超时
    
    int ready = select(socket_fd_ + 1, &readfds, NULL, NULL, &timeout);
    if (ready > 0 && FD_ISSET(socket_fd_, &readfds)) {
        // 创建临时地址结构用于接收，避免修改原始目标地址
        struct sockaddr_in temp_addr;
        socklen_t addr_len = sizeof(temp_addr);
        
        ssize_t recv_len = recvfrom(socket_fd_, recv_buf, sizeof(recv_buf) - 1, 0, 
                                   (struct sockaddr*)&temp_addr, &addr_len);
        if (recv_len > 0) {
            recv_buf[recv_len] = '\0';
            std::string recv_str = recv_buf;
            printf("Received: %s\r\n", recv_str.c_str());
            
            // 解析指令："param1:100.0,param2:200.0,param3:300.0"
            // 特殊处理move参数，保留逗号分隔的两个值
            std::vector<std::string> parts = split(recv_str, ',');
            bool command_received = false;
            
            printf("Parsed parameters:\r\n");
            for (size_t i = 0; i < parts.size(); ++i) {
                const auto& part = parts[i];
                size_t colon_pos = part.find(':');
                if (colon_pos != std::string::npos) {
                    std::string name = part.substr(0, colon_pos);
                    std::string value_str = part.substr(colon_pos + 1);
                    
                    // 特殊处理move参数：move:value1,value2 格式，分成move_a和move_b两个参数
                    if (name == "move" && i + 1 < parts.size()) {
                        try {
                            double move_a = std::stod(value_str);
                            double move_b = std::stod(parts[i + 1]);
                            param_map["move_a"] = move_a;
                            param_map["move_b"] = move_b;
                            printf("  move_a: %.3f\r\n", move_a);
                            printf("  move_b: %.3f\r\n", move_b);
                            command_received = true;
                            i++; // 跳过下一个元素，因为已经处理
                        } catch (...) {
                            printf("  move: Failed to parse values\r\n");
                        }
                    } else {
                        try {
                            double value = std::stod(value_str);
                            param_map[name] = value;
                            printf("  %s: %.3f\r\n", name.c_str(), value);
                            command_received = true;
                        } catch (...) {
                            printf("  %s: Failed to parse value\r\n", name.c_str());
                        }
                    }
                }
            }
            
            return command_received;
        }
    }
    
    return false;
}

/**
 * @brief 获取UDP套接字文件描述符
 * @return 套接字文件描述符，失败返回-1
 */
int UdpTuner::get_socket_fd() const {
    return socket_fd_;
}

/**
 * @brief 字符串分割函数
 * @param s 待分割的字符串
 * @param delimiter 分隔符
 * @return 分割后的字符串向量
 */
std::vector<std::string> UdpTuner::split(const std::string& s, char delimiter) {
    std::vector<std::string> tokens;
    std::string token;
    std::istringstream tokenStream(s);
    while (std::getline(tokenStream, token, delimiter)) {
        tokens.push_back(token);
    }
    return tokens;
}
