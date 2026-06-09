#ifndef __UDP_TUNER_HPP
#define __UDP_TUNER_HPP

#include "../../libraries/drv/inc/lq_udp_client.hpp"
#include <string>
#include <vector>
#include <map>

/**
 * @brief 参数名称值对结构体
 */
struct ParamValue {
    std::string name;   // 参数名称
    double value;       // 参数值
};

/**
 * @brief UDP参数调试器类
 * @details 封装UDP通信功能，用于实时发送数据和接收调参指令
 *          支持动态参数名称，适用于各种PID调参场景
 */
class UdpTuner {
public:
    /**
     * @brief 构造函数
     * @param target_ip 目标IP地址（PC端IP）
     * @param port UDP端口号
     */
    UdpTuner(const std::string& target_ip, uint16_t port);
    
    /**
     * @brief 析构函数
     */
    ~UdpTuner();
    
    /**
     * @brief 初始化UDP通信
     * @return true初始化成功，false初始化失败
     */
    bool init();
    
    /**
     * @brief 发送参数数据到上位机（字符串格式）
     * @param params 参数名称值对列表
     * @return 发送成功返回true，失败返回false
     */
    bool send_data(const std::vector<ParamValue>& params);
    
    /**
     * @brief 发送数据到上位机（VOFA+ justfloat协议）
     * @param values float数据数组
     * @param count 数据个数
     * @return 发送成功返回true，失败返回false
     */
    bool send_justfloat(const float* values, size_t count);
    
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
    bool send_pid_data(double target, double actual, double output, double kp, double ki, double kd);
    
    /**
     * @brief 接收并解析上位机指令
     * @param param_map 参数映射表，用于存储接收到的参数
     * @return 接收到有效指令返回true，无数据或解析失败返回false
     */
    bool receive_command(std::map<std::string, double>& param_map);
    
    /**
     * @brief 获取UDP套接字文件描述符
     * @return 套接字文件描述符，失败返回-1
     */
    int get_socket_fd() const;
    
private:
    std::string target_ip_;     // 目标IP地址
    uint16_t port_;             // UDP端口
    lq_udp_client udp_client_;  // UDP客户端对象
    int socket_fd_;             // 套接字文件描述符
    
    /**
     * @brief 字符串分割函数
     * @param s 待分割的字符串
     * @param delimiter 分隔符
     * @return 分割后的字符串向量
     */
    std::vector<std::string> split(const std::string& s, char delimiter);
};

#endif // __UDP_TUNER_HPP