#!/bin/bash
# ============================================================
# parite.top 香港 VPS 一键部署脚本
# 环境: Ubuntu 20.04+ / Debian 11+
# 架构: Nginx 反向代理 → Vercel 源站
#
# 使用方式（在 VPS 上执行）:
#   wget -O setup.sh https://raw.githubusercontent.com/snowjqm-sys/parite-forex/main/deploy/setup-hk-vps.sh
#   sudo bash setup.sh
# ============================================================

set -euo pipefail

DOMAIN="www.parite.top"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  parite.top 香港 VPS 部署脚本"
echo "============================================"
echo ""

# 1. 安装 Nginx
install_nginx() {
    if command -v nginx &>/dev/null; then
        echo "[OK] Nginx 已安装"
        return 0
    fi
    echo "[1/5] 安装 Nginx..."
    apt-get update -qq
    apt-get install -y -qq nginx
    echo "[OK] Nginx 安装完成"
}

# 2. 部署 Nginx 配置
deploy_config() {
    echo "[2/5] 部署 Nginx 配置..."
    local conf_src="$SCRIPT_DIR/nginx-parite-top.conf"
    local conf_dst="/etc/nginx/conf.d/parite-top.conf"

    if [ ! -f "$conf_src" ]; then
        echo "[ERROR] 找不到 nginx-parite-top.conf，请确保与本脚本在同一目录"
        exit 1
    fi

    cp "$conf_src" "$conf_dst"

    # 创建 certbot 验证目录
    mkdir -p /var/www/certbot
    chown -R www-data:www-data /var/www/certbot

    # 测试配置
    nginx -t 2>&1
    if [ $? -ne 0 ]; then
        echo "[ERROR] Nginx 配置检测失败，请检查 $conf_dst"
        exit 1
    fi
    echo "[OK] Nginx 配置已部署"
}

# 3. 启动 Nginx
start_nginx() {
    echo "[3/5] 启动 Nginx..."
    systemctl enable nginx
    systemctl restart nginx
    echo "[OK] Nginx 已启动"

    # 验证 80 端口
    sleep 1
    if curl -s -o /dev/null -w "%{http_code}" http://localhost | grep -q "301\|200"; then
        echo "[OK] Nginx 80 端口正常"
    else
        echo "[WARN] Nginx 80 端口响应异常，请检查"
    fi
}

# 4. 获取 SSL 证书
setup_ssl() {
    echo "[4/5] 获取 SSL 证书..."
    local ssl_script="$SCRIPT_DIR/ssl-auto-renew.sh"
    if [ ! -f "$ssl_script" ]; then
        echo "[ERROR] 找不到 ssl-auto-renew.sh"
        exit 1
    fi
    chmod +x "$ssl_script"
    bash "$ssl_script" init
}

# 5. 验证
verify() {
    echo "[5/5] 验证部署..."
    sleep 2

    echo ""
    echo "--- 验证 HTTPS ---"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" https://www.parite.top/health 2>/dev/null || echo "000")
    if [ "$http_code" = "200" ]; then
        echo "[OK] HTTPS 健康检查通过 (200)"
    else
        echo "[WARN] HTTPS 健康检查返回: $http_code（可能 Vercel 尚未部署 /health 路由）"
    fi

    echo ""
    echo "--- 验证页面加载 ---"
    http_code=$(curl -s -o /dev/null -w "%{http_code}" https://www.parite.top/ 2>/dev/null || echo "000")
    echo "  首页: $http_code"
    http_code=$(curl -s -o /dev/null -w "%{http_code}" https://www.parite.top/basics 2>/dev/null || echo "000")
    echo "  基础页: $http_code"

    echo ""
    echo "--- SSL 证书信息 ---"
    echo | openssl s_client -connect www.parite.top:443 -servername www.parite.top 2>/dev/null \
        | openssl x509 -noout -subject -dates 2>/dev/null || echo "  (无法获取证书信息)"

    echo ""
    echo "============================================"
    echo "  部署完成！"
    echo "============================================"
    echo ""
    echo "  访问地址: https://www.parite.top"
    echo "  Nginx 配置: /etc/nginx/conf.d/parite-top.conf"
    echo "  SSL 证书: /etc/letsencrypt/live/www.parite.top/"
    echo "  续签日志: /var/log/ssl-renew.log"
    echo "  cron 任务: crontab -l"
    echo ""
    echo "  常用命令:"
    echo "    nginx -t              # 检查配置"
    echo "    systemctl reload nginx # 重载配置"
    echo "    certbot certificates   # 查看证书状态"
    echo "    crontab -l             # 查看定时任务"
    echo ""
}

# --- 主流程 ---
install_nginx
deploy_config
start_nginx
setup_ssl
verify
