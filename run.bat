@echo off
chcp 65001 >nul
title Parite - 多货币研究平台

echo ============================================
echo   Parite · 多货币研究平台 — 启动脚本
echo ============================================
echo.

cd /d "C:\Users\snowj\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a73eba14b017102fbc7aad4\forex_website"

echo [1/3] 检查 Python 环境...
python --version
if errorlevel 1 (
    echo [X] 未找到 Python，请先安装 Python 3.8+ 并添加到 PATH
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python 已安装
echo.

echo [2/3] 检查 Flask 依赖...
python -c "import flask" 2>nul
if errorlevel 1 (
    echo 正在安装 Flask...
    pip install flask
    if errorlevel 1 (
        echo [X] Flask 安装失败，请手动运行: pip install flask
        pause
        exit /b 1
    )
) else (
    echo [OK] Flask 已安装
)
echo.

echo [3/3] 启动网站...
echo ============================================
echo   本地访问: http://127.0.0.1:5000
echo   分享给他人: 运行 share.bat 创建公网链接
echo   按 Ctrl+C 停止
echo ============================================
echo.

python app.py

pause
