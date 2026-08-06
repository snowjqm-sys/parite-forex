@echo off
chcp 65001 >nul
title Parite - 公网分享隧道

echo ============================================
echo   Parite · 创建公网分享链接
echo ============================================
echo.

cd /d "C:\Users\snowj\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a73eba14b017102fbc7aad4\forex_website"

echo 使用说明:
echo   1. 先运行 run.bat 启动网站（保持窗口打开）
echo   2. 再运行本脚本创建公网链接
echo   3. 将公网链接分享给他人即可访问
echo.

echo 正在创建 Cloudflare 隧道...
echo 链接生成后请复制 trycloudflare.com 地址
echo 按 Ctrl+C 停止分享
echo ============================================
echo.

cloudflared.exe tunnel --url http://localhost:5000

pause
