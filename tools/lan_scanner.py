#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
局域网设备扫描器 - 发现同一热点下的设备
By RMxiaotaobao
"""
import subprocess
import platform
import socket
import sys
import os
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_all_local_ips():
    """获取本机所有网卡的IP地址和子网掩码，返回 [(ip, netmask, network_prefix), ...]"""
    results = []

    # 方法1: 通过 ipconfig 获取所有适配器信息（Windows）
    if platform.system().lower() == 'windows':
        try:
            result = subprocess.run(['ipconfig', '/all'], capture_output=True, text=True, timeout=10)
            lines = result.stdout.splitlines()
            adapter_name = ""
            current_ip = None
            current_mask = None
            for line in lines:
                stripped = line.strip()
                # 检测适配器名称
                if '适配器' in stripped or 'adapter' in stripped.lower():
                    # 先保存上一个适配器的结果
                    if current_ip and current_mask:
                        prefix = '.'.join(current_ip.split('.')[:-1])
                        results.append((current_ip, current_mask, prefix, adapter_name))
                        current_ip = None
                        current_mask = None
                    adapter_name = stripped.rstrip(':')
                # 检测 IPv4 地址
                elif ('IPv4' in stripped or 'IP Address' in stripped) and ':' in stripped:
                    ip_part = stripped.split(':')[-1].strip()
                    # 去掉可能的 % 后缀
                    if '%' in ip_part:
                        ip_part = ip_part.split('%')[0]
                    if ip_part.count('.') == 3:
                        current_ip = ip_part
                # 检测子网掩码
                elif ('子网掩码' in stripped or 'Subnet Mask' in stripped) and ':' in stripped:
                    mask_part = stripped.split(':')[-1].strip()
                    if mask_part.count('.') == 3:
                        current_mask = mask_part
            # 保存最后一个适配器
            if current_ip and current_mask:
                prefix = '.'.join(current_ip.split('.')[:-1])
                results.append((current_ip, current_mask, prefix, adapter_name))
        except Exception:
            pass

    # 方法2: 通过 socket 遍历所有接口（兜底方案）
    if not results:
        try:
            # 通过 UDP socket 绑定到所有接口
            hostname = socket.gethostname()
            for ip in socket.gethostbyname_ex(hostname)[2]:
                if not ip.startswith('127.'):
                    prefix = '.'.join(ip.split('.')[:-1])
                    results.append((ip, '255.255.255.0', prefix, '未知适配器'))
        except Exception:
            pass

    # 方法3: 最终兜底 - 连接外部地址获取默认接口
    if not results:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            prefix = '.'.join(local_ip.split('.')[:-1])
            results.append((local_ip, '255.255.255.0', prefix, '默认接口'))
        except Exception:
            pass

    # 去重（按 IP）
    seen = set()
    unique = []
    for item in results:
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique

def get_subnet_cidr(ip, netmask):
    """计算子网 CIDR，返回如 '192.168.1.0/24'"""
    try:
        network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
        return str(network)
    except Exception:
        prefix = '.'.join(ip.split('.')[:-1])
        return f"{prefix}.0/24"

def ping_host(ip):
    """Ping指定IP地址"""
    try:
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
        command = ['ping', param, '1', timeout_param, '1', str(ip)]
        result = subprocess.run(command, 
                              stdout=subprocess.DEVNULL, 
                              stderr=subprocess.DEVNULL,
                              timeout=2)
        return result.returncode == 0
    except:
        return False

def get_arp_table():
    """读取系统 ARP 表，返回 {ip: mac} 字典"""
    arp = {}
    try:
        result = subprocess.run(['arp', '-a'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0].count('.') == 3:
                ip = parts[0]
                mac = parts[1].replace('-', ':').lower()
                if mac != 'ff:ff:ff:ff:ff:ff':
                    arp[ip] = mac
    except Exception:
        pass
    return arp

def lookup_vendor(mac):
    """通过 MAC 前 6 位查厂商"""
    if not mac or mac == "未知":
        return "未知厂商"
    oui = mac.replace(':', '').replace('-', '').upper()[:6]
    vendors = {
        '001C42': 'Parallels', '000C29': 'VMware', '005056': 'VMware',
        '080027': 'VirtualBox', '525400': 'QEMU/KVM',
        '00155D': 'Hyper-V', '001DD8': 'Microsoft',
        '3CECEF': 'Apple', 'ACBC32': 'Apple', 'F0D1A9': 'Apple',
        'A483E7': 'Apple', 'DC2B2A': 'Apple', 'F45C89': 'Apple',
        'B827EB': 'Raspberry Pi', 'DCA632': 'Raspberry Pi',
        'E45F01': 'Raspberry Pi',
        'FCAA14': '小米', '7811DC': '小米', '286C07': '小米',
        '50642B': '小米', '742344': '小米',
        'C09727': 'Samsung', '001A8A': 'Samsung', '5001BB': 'Samsung',
        'FCF136': 'Samsung', '183A2D': 'Samsung',
        '404E36': 'HTC', 'B4CEF6': 'HTC',
        '00E0FC': 'Huawei', '4846FB': 'Huawei',
        '04F938': 'Huawei', '78D752': 'Huawei', '8828B3': 'Huawei',
        '20A680': 'Honor',
        'D4A148': 'HuaWei', '001E10': 'HuaWei',
        'B0BE76': 'TP-Link', '001FE2': 'TP-Link', '14CC20': 'TP-Link',
        '50C7BF': 'TP-Link', '60E327': 'TP-Link',
        'C0A0BB': 'D-Link', '001B11': 'D-Link', '1CBDB9': 'D-Link',
        'E091F5': 'Netgear', 'C40415': 'Netgear',
        'D017C2': 'ASUS', '60A44C': 'ASUS', '04D9F5': 'ASUS',
        '001B21': 'Intel', '001E65': 'Intel', '3C970E': 'Intel',
        'A4C494': 'Intel', 'B46921': 'Intel', 'E8B1FC': 'Intel',
        '7085C2': 'ASRock', '309C23': 'MSI', '00D861': 'MSI',
        '74D435': 'GIGABYTE', 'B42E99': 'GIGABYTE',
    }
    return vendors.get(oui, f"未知厂商({oui})")

def scan_network(network_prefix):
    """扫描整个网络"""
    print(f"正在扫描网络: {network_prefix}.0/24")
    print("正在 ping 所有地址...\n")

    active_ips = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        ip_list = [f"{network_prefix}.{i}" for i in range(1, 255)]
        future_to_ip = {executor.submit(ping_host, ip): ip for ip in ip_list}

        for i, future in enumerate(as_completed(future_to_ip)):
            ip = future_to_ip[future]
            try:
                if future.result():
                    active_ips.append(ip)
                    print(f"✓ 发现活跃设备: {ip}")
            except Exception:
                pass
            if (i + 1) % 50 == 0:
                print(f"进度: {i+1}/254")

    # Ping 完成后读取 ARP 表获取 MAC 和厂商
    print("\n正在读取 ARP 表获取设备信息...")
    arp_table = get_arp_table()
    results = []
    for ip in active_ips:
        mac = arp_table.get(ip, "未知")
        vendor = lookup_vendor(mac)
        results.append((ip, mac, vendor))
    return results

def save_results_multi(save_lines):
    """保存多网段扫描结果，按子网分类"""
    with open("network_scan_results.txt", "w", encoding="utf-8") as f:
        f.write("局域网设备扫描结果（多网卡）\n")
        f.write("=" * 60 + "\n")

        # 按子网分组（Python 3.7+ dict 保持插入顺序）
        grouped = {}
        for ip, mac, vendor, subnet_label in save_lines:
            grouped.setdefault(subnet_label, []).append((ip, mac, vendor))

        idx = 0
        for subnet_label, hosts in grouped.items():
            f.write(f"\n【{subnet_label}】 设备数: {len(hosts)}\n")
            f.write("-" * 60 + "\n")
            for ip, mac, vendor in hosts:
                idx += 1
                f.write(f"  {idx:2d}. IP: {ip:15s} | MAC: {mac:17s} | 厂商: {vendor}\n")

        f.write("\n" + "=" * 60 + "\n")
        f.write(f"总计: {len(save_lines)} 个活跃设备\n")

    print(f"\n结果已保存到 network_scan_results.txt")

def main():
    print("=" * 50)
    print("局域网设备扫描器 v1.5  by RMxiaotaobao")
    print("=" * 50)

    interfaces = get_all_local_ips()
    if not interfaces:
        print("❌ 无法获取本机IP地址，请检查网络连接")
        sys.exit(1)

    print(f"\n检测到 {len(interfaces)} 个网络接口:")
    for i, (ip, mask, prefix, name) in enumerate(interfaces, 1):
        cidr = get_subnet_cidr(ip, mask)
        print(f"  {i}. {name}")
        print(f"     IP: {ip}  掩码: {mask}  子网: {cidr}")

    # 按网段分别扫描
    all_results = {}  # {子网描述: [(ip, mac, vendor), ...]}
    for idx, (ip, mask, prefix, name) in enumerate(interfaces, 1):
        cidr = get_subnet_cidr(ip, mask)
        print(f"\n{'=' * 50}")
        print(f"[{idx}/{len(interfaces)}] 扫描接口: {name}")
        print(f"    IP: {ip}  子网: {cidr}")
        print("=" * 50)

        results = scan_network(prefix)
        label = f"{name} ({cidr})"
        all_results[label] = results

    # 汇总输出
    total_devices = sum(len(v) for v in all_results.values())
    print("\n" + "=" * 50)
    print(f"全部扫描完成！共发现 {total_devices} 个活跃设备")
    print("=" * 50)

    # 保存结果的总列表
    save_lines = []
    global_idx = 0

    for subnet_label, hosts in all_results.items():
        print(f"\n┌─ {subnet_label} ─ 设备数: {len(hosts)}")
        if hosts:
            for ip, mac, vendor in hosts:
                global_idx += 1
                print(f"│  {global_idx:2d}. IP: {ip:15s} | MAC: {mac:17s} | 厂商: {vendor}")
                save_lines.append((ip, mac, vendor, subnet_label))
        else:
            print("│  (无其他活跃设备)")
        print("└" + "─" * 48)

    if save_lines:
        save_results_multi(save_lines)
    else:
        print("\n未发现其他活跃设备")

    input("\n按回车键退出...")

if __name__ == "__main__":
    main()