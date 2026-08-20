#!/bin/bash
# ============================================================
# parite.top SSL 证书自动获取 + 续签脚本
# 运行环境: 香港 VPS (Ubuntu/Debian)
# 使用方式:
#   首次获取证书:  sudo bash ssl-auto-renew.sh init
#   手动续签测试:  sudo bash ssl-auto-renew.sh test
#   安装定时任务:  sudo bash ssl-auto-renew.sh cron
# ============================================================

set -euo pipefail

DOMAIN="www.parite.top"
EMAIL="snowjqm@163.com"
CERT_DIR="/var/www/certbot"
NGINX_CONF="/etc/nginx/conf.d/parite-top.conf"
LOG_FILE="/var/log/ssl-renew.log"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 检查并安装 certbot
install_certbot() {
    if command -v certbot &>/dev/null; then
        log "certbot 已安装，跳过"
        return 0
    fi
    log "正在安装 certbot..."
    apt-get update -qq
    apt-get install -y -qq certbot python3-certbot-nginx
    log "certbot 安装完成"
}

# 确保 certbot 验证目录存在
ensure_webroot() {
    mkdir -p "$CERT_DIR"
    chown -R www-data:www-data "$CERT_DIR" 2>/dev/null || true
}

# --- 首次获取证书 ---
init_cert() {
    log "===== 开始获取 SSL 证书 ====="

    install_certbot
    ensure_webroot

    # 先确保 Nginx 已启动且 80 端口可访问
    if ! systemctl is-active --quiet nginx; then
        log "Nginx 未运行，请先部署 Nginx 配置并启动"
        log "  1. 复制 nginx-parite-top.conf 到 /etc/nginx/conf.d/"
        log "  2. nginx -t && systemctl start nginx"
        exit 1
    fi

    # 确认 DNS 已指向本机
    local current_ip
    current_ip=$(curl -s ifconfig.me 2>/dev/null || curl -s ip.sb 2>/dev/null)
    log "本机公网 IP: $current_ip"
    log "请确认 www.parite.top 的 DNS A 记录已指向此 IP"
    log "  验证: nslookup www.parite.top"
    echo ""
    read -p "确认 DNS 已指向本机？(y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log "用户取消，请先配置 DNS 后重试"
        exit 0
    fi

    # 用 webroot 方式获取证书（不影响 Nginx 运行）
    log "正在向 Let's Encrypt 申请证书..."
    certbot certonly \
        --webroot \
        --webroot-path "$CERT_DIR" \
        -d "$DOMAIN" \
        -d "parite.top" \
        --email "$EMAIL" \
        --agree-tos \
        --no-eff-email \
        --non-interactive

    log "证书获取成功！"
    log "  证书路径: /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    log "  私钥路径: /etc/letsencrypt/live/$DOMAIN/privkey.pem"

    # 重载 Nginx 使 SSL 生效
    nginx -t && systemctl reload nginx
    log "Nginx 已重载，HTTPS 应已生效"

    # 自动安装定时续签
    setup_cron
    log "===== SSL 证书获取完成 ====="
}

# --- 续签证书 ---
renew_cert() {
    log "===== 开始检查/续签 SSL 证书 ====="

    # 只续签剩余不足 30 天的证书
    certbot renew --quiet --no-random-sleep-on-renew 2>&1 | tee -a "$LOG_FILE"

    # 检查是否实际续签了（certbot renew 只在需要时才续）
    local renewed
    renewed=$(certbot certificates 2>/dev/null | grep -c "VALID" || true)

    if [ "$renewed" -gt 0 ]; then
        log "证书状态正常，重载 Nginx 以确保最新证书生效"
        nginx -t 2>&1 | tee -a "$LOG_FILE"
        if [ $? -eq 0 ]; then
            systemctl reload nginx
            log "Nginx 重载成功"
        else
            log "ERROR: Nginx 配置检测失败，未重载"
        fi
    else
        log "ERROR: 证书状态异常，请手动检查 certbot certificates"
    fi

    log "===== 续签检查完成 ====="
}

# --- 测试续签（不实际执行）---
test_renew() {
    log "===== 测试续签流程（dry-run）====="
    certbot renew --dry-run --webroot --webroot-path "$CERT_DIR"
    log "测试完成，如无报误则定时续签可正常工作"
}

# --- 安装 cron 定时任务 ---
setup_cron() {
    local cron_job="0 3 * * * /bin/bash $(cd "$(dirname "$0")" && pwd)/ssl-auto-renew.sh renew >> $LOG_FILE 2>&1"

    # 检查是否已存在
    if crontab -l 2>/dev/null | grep -q "ssl-auto-renew.sh"; then
        log "cron 定时任务已存在，跳过"
        return 0
    fi

    (crontab -l 2>/dev/null; echo "$cron_job") | crontab -
    log "已安装 cron 定时任务: 每天凌晨 3:00 检查续签"
    log "  查看任务: crontab -l"
    log "  日志文件: $LOG_FILE"
}

# --- 主入口 ---
case "${1:-renew}" in
    init)
        init_cert
        ;;
    renew)
        renew_cert
        ;;
    test)
        test_renew
        ;;
    cron)
        setup_cron
        ;;
    *)
        echo "用法: $0 {init|renew|test|cron}"
        echo ""
        echo "  init  - 首次获取 SSL 证书（交互式，需确认 DNS）"
        echo "  renew - 检查并续签证书（由 cron 调用）"
        echo "  test  - 干运行测试续签流程"
        echo "  cron  - 安装 cron 定时任务"
        exit 1
        ;;
esac
