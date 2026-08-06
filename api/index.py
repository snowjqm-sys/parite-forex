# -*- coding: utf-8 -*-
"""
Vercel Serverless 入口文件
将 Flask app 导出为 WSGI application，供 Vercel Python runtime 调用。

Vercel 会把所有路由（除 /static/* 外）转发到这个 handler。
Flask app 实例必须命名为 `app`，Vercel 会自动识别 WSGI 接口。
"""

import sys
import os

# 把项目根目录加入 sys.path，这样 `import app` 和 `import data` 才能正常工作
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 设置模板和静态文件目录为项目根目录
os.environ.setdefault("FLASK_TEMPLATE_FOLDER", os.path.join(_project_root, "templates"))
os.environ.setdefault("FLASK_STATIC_FOLDER", os.path.join(_project_root, "static"))

from app import app  # noqa: E402

# Vercel Python runtime 会查找名为 `app` 的 WSGI callable
# Flask 的 app 实例本身就是 WSGI 兼容的
