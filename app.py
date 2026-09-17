# -*- coding: utf-8 -*-
"""
Parité · 多货币研究平台 — Flask 应用主程序

路由结构：
  /                       首页（市场总览）
  /basics                 外汇基础概念
  /currency/<code>        货币研究页（jpy/cny/eur/gbp/aud/chf/usd）
  /comparison             对比与自由思考
  /explorer               数据探索
  /api/...                数据 API（含实时汇率代理）
"""

import math
import os
import re
import time
import json as _json
import smtplib
import urllib.request
import urllib.error
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formataddr
from flask import Flask, render_template, jsonify, request, abort, session, redirect, url_for

import data as DATA
import cme_history as CME_HISTORY

# 显式指定模板和静态文件目录，确保 Vercel serverless 环境也能正确找到
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(_BASE_DIR, "templates"),
    static_folder=os.path.join(_BASE_DIR, "static"),
)
app.secret_key = "parite-admin-secret-2026"  # 用于 session 加密


# ============================================================
# 缓存控制：让 Cloudflare / Vercel 边缘节点缓存 HTML + 静态数据
# 同时保证：实时汇率 API / 所有 POST / 管理后台 永不被缓存
#
# Vercel 缓存头优先级（官方文档）：
#   Vercel-CDN-Cache-Control > CDN-Cache-Control > Cache-Control
# Function 返回的头 > vercel.json 配置的头（同名时）
#
# 未来新增路由默认规则：
#   · 纯只读展示页面 → 走 after_request 默认策略（自动缓存 5min）
#   · 实时数据 API   → 默认 no-cache（不在白名单里就自动不缓存）
#   · 静态数据 API   → 加到 _STATIC_API_PREFIXES 白名单
#   · 任何 POST/PUT  → 统一走 after_request，强制 no-store
# ============================================================

# ---- 明确「实时 / 永不缓存」的 API 前缀清单（以后新增实时路由加这里）----
_NO_CACHE_API_PREFIXES = (
    "/api/ticker",          # 滚动横条实时汇率
    "/api/live",            # 实时汇率详情
    "/api/feedback",        # 反馈（含 POST 提交 + GET 查看，都不想缓存）
    "/api/ai",              # AI 问答 / AI 配置
    "/api/admin",           # 管理员配置 / 发信测试
)

# 静态数据 API（允许缓存 10 分钟，数据一天顶多变几次）
_STATIC_API_PREFIXES = (
    "/api/snapshot",            # 市场总览快照（和 data.py 同步更新）
    "/api/rates",               # 利率序列（data.py 静态）
    "/api/currencies",          # 货币元信息
    "/api/regression",          # OLS 回归结果（同上）
)
# 注意：/api/currency/<code>/history|monthly|daily 已改为实时获取 Frankfurter 数据，
# 不再走静态缓存，归入默认 /api/* 的 no-cache 策略。


def _apply_cache(resp, vercel_cdn, cdn_cache, client_cache):
    """统一设置三层缓存头。

    vercel_cdn: Vercel-CDN-Cache-Control 值（Vercel 边缘缓存，最高优先级，不透传给客户端）
    cdn_cache:  CDN-Cache-Control 值（Cloudflare 等中间 CDN 缓存）
    client_cache: Cache-Control 值（浏览器缓存，透传给客户端）
    """
    resp.headers["Vercel-CDN-Cache-Control"] = vercel_cdn
    resp.headers["CDN-Cache-Control"] = cdn_cache
    resp.headers["Cache-Control"] = client_cache
    return resp


@app.after_request
def _set_cache_headers(resp):
    # 1) 非 GET/HEAD 的请求（POST/PUT/PATCH/DELETE）一律不缓存
    if request.method not in ("GET", "HEAD"):
        return _apply_cache(resp, "no-store", "no-store",
                            "no-store, no-cache, must-revalidate, max-age=0")

    # 2) 非 2xx/3xx 的响应一律不缓存
    if resp.status_code >= 400:
        return _apply_cache(resp, "no-store", "no-store", "no-store, no-cache")

    path = request.path

    # 3) 管理员 / 配置相关：永不缓存
    if path.startswith("/admin") or path.startswith("/ai-config"):
        return _apply_cache(resp, "no-store", "no-store",
                            "no-store, no-cache, must-revalidate, max-age=0")

    # 4) 实时 / 写入类 API：明确 no-cache（浏览器不存，Vercel 不存，Cloudflare 不存）
    for prefix in _NO_CACHE_API_PREFIXES:
        if path.startswith(prefix):
            return _apply_cache(resp, "no-store", "no-store",
                                "no-store, no-cache, must-revalidate, max-age=0")

    # 5) 静态数据 API（历史 / 利率 / 回归等）：边缘 10 分钟 + stale-while
    for prefix in _STATIC_API_PREFIXES:
        if path.startswith(prefix):
            return _apply_cache(resp,
                                "s-maxage=600, stale-while-revalidate=3600",
                                "s-maxage=600, stale-while-revalidate=3600",
                                "public, max-age=300, s-maxage=600, stale-while-revalidate=3600")

    # 6) 剩下的 /api/* 路径（以后新增的 API，默认保守 no-cache，避免误缓存实时数据）
    if path.startswith("/api/"):
        return _apply_cache(resp, "no-store", "no-store",
                            "no-store, no-cache, must-revalidate, max-age=0")

    # 7) 其他所有路径（HTML 页面）：边缘 5 分钟 + stale-while 1 天
    return _apply_cache(resp,
                        "s-maxage=300, stale-while-revalidate=86400",
                        "s-maxage=300, stale-while-revalidate=86400",
                        "public, max-age=120, s-maxage=300, stale-while-revalidate=86400")


# ============================================================
# 实时汇率多源 fallback + 重试 + 缓存 工具层
# 优先级：Frankfurter (主) → exchangerate.host (备) → data.py 静态数据 (兜底)
# ============================================================

_LIVE_CACHE = {}  # key -> (timestamp, payload)
_CACHE_TTL_SEC = 60  # 缓存 60 秒，避免频繁打外部 API


def _cache_get(key):
    item = _LIVE_CACHE.get(key)
    if not item:
        return None
    ts, payload = item
    if time.time() - ts > _CACHE_TTL_SEC:
        _LIVE_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key, payload):
    _LIVE_CACHE[key] = (time.time(), payload)


def _http_get_json(url, timeout=12):
    """带 UA 头的简单 HTTP GET + JSON 解析。不做重试，只做一次尝试。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "PariteForex/1.1 (+https://parite.local)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return _json.loads(body)


def _http_get_json_with_retry(url, timeout=12, max_retries=2):
    """指数退避重试：失败后等待 0.5s → 1s，最多再试 max_retries 次。"""
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return _http_get_json(url, timeout=timeout), None
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** attempt))  # 0.5s, 1.0s
    return None, last_err


def _build_static_fallback_latest(base, targets):
    """当所有外部源都失败时，用 data.py 中的静态 current 数据兜底。

    构造与 Frankfurter latest 响应兼容的结构：
    {"amount":1,"base":"USD","date":"2026-08-05","rates":{"EUR":1.09,...}}
    """
    base = base.upper()
    rates = {}
    static_date = None
    # 遍历所有货币，通过 current.rate / pair 信息尝试反推交叉汇率
    # 简单策略：所有货币都有 data.CURRENCIES[code]["current"]
    for code, cur in DATA.CURRENCIES.items():
        cur_code_upper = code.upper()
        if not cur.get("current"):
            continue
        static_date = cur["current"].get("date", static_date)
        pair = cur.get("pair", "")  # e.g. "USD/JPY"
        rate_val = float(cur["current"]["rate"])
        # 对每个货币，推导 1 base = X code_upper
        if pair == "USD/" + cur_code_upper:  # 直接标价：1 USD = rate JPY/CNY/...
            rates[cur_code_upper] = rate_val
        elif pair == cur_code_upper + "/USD":  # 间接标价：1 EUR = rate USD
            # 1 EUR = rate USD → 1 USD = 1/rate EUR
            if rate_val:
                rates[cur_code_upper] = round(1.0 / rate_val, 6)
        elif pair == "DXY":  # 美元指数特殊处理
            rates["DXY"] = rate_val
    # 始终确保 USD 有值
    rates.setdefault("USD", 1.0)

    # 如果 base != USD，通过 USD 作为中间货币换算所有 targets
    usd_per_base = 1.0
    if base != "USD":
        if base in rates:
            # rates[base] 当前表示的是 1 USD = X base。我们要的是 1 base = ? USD → 1/X
            if rates.get(base):
                usd_per_base = 1.0 / rates[base]
        else:
            # 尝试反向：是否是间接标价法
            for code, cur in DATA.CURRENCIES.items():
                if code.upper() == base and cur.get("pair") == base + "/USD":
                    usd_per_base = float(cur["current"]["rate"])
                    break
    out_rates = {}
    for t in targets:
        t = t.upper()
        if t == base:
            out_rates[t] = 1.0
            continue
        # usd_per_t = ?
        usd_per_t = None
        if t in rates:
            # rates[t] = 1 USD = X t → 1 t = 1/X USD
            if rates[t]:
                usd_per_t = 1.0 / rates[t]
        if usd_per_t is None:
            # 尝试反向
            for code, cur in DATA.CURRENCIES.items():
                if code.upper() == t and cur.get("pair") == t + "/USD":
                    usd_per_t = float(cur["current"]["rate"])
                    break
        if usd_per_t is None and t == "USD":
            usd_per_t = 1.0
        if usd_per_t is None:
            continue
        # 1 base = usd_per_base USD = usd_per_base * (1 / usd_per_t) t = usd_per_base / usd_per_t t
        out_rates[t] = round(usd_per_base / usd_per_t, 6)

    return {
        "amount": 1,
        "base": base,
        "date": static_date or time.strftime("%Y-%m-%d", time.localtime()),
        "rates": out_rates,
        "_fallback": True,
        "_fallbackSource": "data.py (static)",
    }


def _fetch_latest_rates(base, targets):
    """多源 latest 汇率：Frankfurter → exchangerate.host → 静态兜底。"""
    base = base.upper()
    targets = [t.upper() for t in targets]
    cache_key = ("LIVE", base, tuple(sorted(targets)))
    cached = _cache_get(cache_key)
    if cached:
        return cached, None

    symbols = ",".join(targets)
    sources_used = []

    # 源 1: Frankfurter
    url1 = f"https://api.frankfurter.app/latest?from={base}&to={symbols}"
    data, err = _http_get_json_with_retry(url1, timeout=10, max_retries=2)
    sources_used.append(("frankfurter", err is None))
    if data and "rates" in data:
        _cache_set(cache_key, data)
        return data, None

    # 源 2: exchangerate.host (免费，镜像 ECB 数据)
    try:
        url2 = f"https://api.exchangerate.host/latest?base={base}&symbols={symbols}"
        data2, err2 = _http_get_json_with_retry(url2, timeout=10, max_retries=2)
        sources_used.append(("exchangerate.host", err2 is None))
        if data2 and data2.get("success") and "rates" in data2:
            # 归一化成 Frankfurter 兼容结构
            normalized = {
                "amount": 1,
                "base": data2.get("base", base),
                "date": data2.get("date", time.strftime("%Y-%m-%d")),
                "rates": data2["rates"],
                "_source": "exchangerate.host",
            }
            _cache_set(cache_key, normalized)
            return normalized, None
    except Exception:
        pass

    # 源 3: 静态兜底
    fallback = _build_static_fallback_latest(base, targets)
    fallback["_sources"] = sources_used
    _cache_set(cache_key, fallback)
    return fallback, None


def _build_static_fallback_range(from_ccy, to_ccy, start_date, end_date):
    """历史范围 API 失败时，返回一个极简的单点静态兜底（仅一个当前值，避免图表空窗）。"""
    from_ccy = from_ccy.upper()
    to_ccy = to_ccy.upper()
    cur_date = None
    cur_rate = None
    # 从 DATA.CURRENCIES 找 pair == from/to 或 to/from
    for code, cur in DATA.CURRENCIES.items():
        if not cur.get("current"):
            continue
        pair = cur.get("pair", "")
        rate_val = float(cur["current"]["rate"])
        if pair == f"{from_ccy}/{to_ccy}":
            cur_rate = rate_val
            cur_date = cur["current"].get("date")
            break
        elif pair == f"{to_ccy}/{from_ccy}" and rate_val:
            cur_rate = round(1.0 / rate_val, 6)
            cur_date = cur["current"].get("date")
            break
    if cur_rate is None:
        # 通过 USD 中转：1 from = x USD; 1 to = y USD → 1 from = x/y to
        def _usd_per(ccy):
            for code, cur in DATA.CURRENCIES.items():
                if code.upper() != ccy or not cur.get("current"):
                    continue
                pair = cur.get("pair", "")
                r = float(cur["current"]["rate"])
                if pair == f"USD/{ccy}":
                    return 1.0 / r if r else None
                if pair == f"{ccy}/USD":
                    return r
            return 1.0 if ccy == "USD" else None
        u_from = _usd_per(from_ccy)
        u_to = _usd_per(to_ccy)
        if u_from and u_to:
            cur_rate = round(u_from / u_to, 6)
        else:
            cur_rate = 1.0
    cur_date = cur_date or end_date
    return {
        "amount": 1,
        "base": from_ccy,
        "start_date": start_date,
        "end_date": end_date,
        "rates": {cur_date: {to_ccy: cur_rate}},
        "_fallback": True,
        "_fallbackSource": "data.py (static, single point)",
    }


def _fetch_range_rates(from_ccy, to_ccy, start_date, end_date):
    """多源历史范围汇率：Frankfurter → exchangerate.host → 静态单点兜底。"""
    from_ccy = from_ccy.upper()
    to_ccy = to_ccy.upper()
    cache_key = ("RANGE", from_ccy, to_ccy, start_date, end_date)
    cached = _cache_get(cache_key)
    if cached:
        return cached, None

    sources_used = []

    # 源 1: Frankfurter 范围
    url1 = f"https://api.frankfurter.app/{start_date}..{end_date}?from={from_ccy}&to={to_ccy}"
    data, err = _http_get_json_with_retry(url1, timeout=15, max_retries=2)
    sources_used.append(("frankfurter", err is None))
    if data and "rates" in data:
        _cache_set(cache_key, data)
        return data, None

    # 源 2: exchangerate.host timeseries
    try:
        url2 = (f"https://api.exchangerate.host/timeseries"
                f"?start_date={start_date}&end_date={end_date}&base={from_ccy}&symbols={to_ccy}")
        data2, err2 = _http_get_json_with_retry(url2, timeout=15, max_retries=2)
        sources_used.append(("exchangerate.host", err2 is None))
        if data2 and data2.get("success") and "rates" in data2:
            normalized = {
                "amount": 1,
                "base": data2.get("base", from_ccy),
                "start_date": data2.get("start_date", start_date),
                "end_date": data2.get("end_date", end_date),
                "rates": data2["rates"],
                "_source": "exchangerate.host",
            }
            _cache_set(cache_key, normalized)
            return normalized, None
    except Exception:
        pass

    # 源 3: 静态单点兜底
    fallback = _build_static_fallback_range(from_ccy, to_ccy, start_date, end_date)
    fallback["_sources"] = sources_used
    _cache_set(cache_key, fallback)
    return fallback, None


# ============================================================
# 文件存储路径适配（本地开发用源码目录，Vercel serverless 用 /tmp）
# ============================================================
def _data_dir():
    """返回可读写的数据目录。Vercel serverless 文件系统只读，降级到 /tmp。"""
    _dir = os.path.dirname(os.path.abspath(__file__))
    # Vercel 环境检测：VERCEL 环境变量存在 或 源码目录不可写
    if os.environ.get("VERCEL") or not os.access(_dir, os.W_OK):
        _tmp = "/tmp/parite"
        os.makedirs(_tmp, exist_ok=True)
        return _tmp
    return _dir


def _admin_config_path():
    return os.path.join(_data_dir(), "admin_config.json")


def _load_admin_config():
    """读取管理员配置：admin_password / mail_auth_code / mail_address"""
    default = {
        "admin_password": "",          # 管理员登录密码，为空则 /ai-config 不加保护
        "mail_address": "snowjqm@163.com",   # 收件邮箱
        "mail_auth_code": "",           # 163 邮箱 SMTP 授权码（非登录密码）
    }
    path = _admin_config_path()
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        merged = dict(default)
        merged.update(data or {})
        return merged
    except Exception:
        return default


def _save_admin_config(cfg):
    with open(_admin_config_path(), "w", encoding="utf-8") as f:
        _json.dump(cfg, f, ensure_ascii=False, indent=2)


def _is_admin():
    """检查当前 session 是否已登录管理员"""
    return session.get("is_admin") is True


def _send_feedback_mail(fb):
    """将反馈发送到管理员邮箱（163 SMTP）。

    需要 admin_config.json 中配置 mail_auth_code（163 邮箱授权码）。
    失败时静默返回错误信息，不影响反馈保存。
    """
    cfg = _load_admin_config()
    auth_code = cfg.get("mail_auth_code", "")
    to_addr = cfg.get("mail_address", "snowjqm@163.com")
    if not auth_code:
        return False, "未配置邮箱授权码"
    try:
        body = (
            f"【Parité 平台新反馈】\n\n"
            f"分类：{fb.get('category', '其他')}\n"
            f"内容：{fb.get('content', '')}\n"
            f"联系方式：{fb.get('contact', '无')}\n"
            f"提交时间：{fb.get('time', '')}\n"
        )
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[Parité反馈] {fb.get('category', '其他')}"
        msg["From"] = formataddr(("Parité 反馈系统", to_addr))
        msg["To"] = to_addr
        with smtplib.SMTP_SSL("smtp.163.com", 465, timeout=15) as server:
            server.login(to_addr, auth_code)
            server.sendmail(to_addr, [to_addr], msg.as_string())
        return True, "邮件已发送"
    except Exception as e:
        return False, str(e)


# ============================================================
# 页面路由
# ============================================================
@app.route("/")
def index():
    """首页：市场总览"""
    announcements = _load_announcements()
    return render_template(
        "index.html",
        active="index",
        snapshot=DATA.MARKET_SNAPSHOT,
        currencies=DATA.CURRENCIES,
        currency_nav=DATA.CURRENCY_NAV,
        home_hero=DATA.HOME_HERO,
        rate_radar=DATA.RATE_RADAR,
        recent_updates=DATA.RECENT_UPDATES,
        interest_rates=DATA.INTEREST_RATES,
        announcements=announcements,
    )


@app.route("/basics")
def basics():
    """外汇基础"""
    return render_template(
        "basics.html",
        active="basics",
        concepts=DATA.FOREX_CONCEPTS,
        learning_path=DATA.LEARNING_PATH,
        learning_stages=DATA.LEARNING_STAGES,
        currency_nav=DATA.CURRENCY_NAV,
    )


@app.route("/currency/<code>")
def currency_page(code):
    """货币研究页（动态路由，适用于所有货币）"""
    code = code.lower()
    cur = DATA.CURRENCIES.get(code)
    if not cur:
        abort(404)
    # 货币自身的利率序列（用于利差图）
    rate_key_a, rate_key_b = cur["rate_pair"]
    rate_series = [
        {"date": r["date"], "a": r.get(rate_key_a), "b": r.get(rate_key_b),
         "spread": (r.get(rate_key_a, 0) - r.get(rate_key_b, 0)) if (r.get(rate_key_a) is not None and r.get(rate_key_b) is not None) else None}
        for r in DATA.INTEREST_RATES
    ]
    return render_template(
        "currency.html",
        active="cur_" + code,
        cur=cur,
        code=code,
        history=cur["history"],
        drivers=cur["drivers"],
        questions=cur["questions"],
        correlations=cur["correlations"],
        rate_series=rate_series,
        currency_nav=DATA.CURRENCY_NAV,
        deep=DATA.CURRENCY_DEEP_ANALYSIS.get(code, {}),
        glossary=DATA.GLOSSARY,
    )


@app.route("/comparison")
def comparison():
    """对比与自由思考"""
    return render_template(
        "comparison.html",
        active="comparison",
        questions=DATA.DISCUSSION_QUESTIONS,
        currency_nav=DATA.CURRENCY_NAV,
    )


@app.route("/futures")
def futures():
    """外汇期货板块"""
    return render_template(
        "futures.html",
        active="futures",
        intro=DATA.FOREX_FUTURES_INTRO,
        contracts=DATA.FOREX_FUTURES_CONTRACTS,
        strategies=DATA.FOREX_FUTURES_STRATEGIES,
        glossary=DATA.FOREX_FUTURES_GLOSSARY,
        margin_contracts=DATA.MARGIN_CALCULATOR_CONTRACTS,
        currency_nav=DATA.CURRENCY_NAV,
        exchanges_summary=DATA.FX_EXCHANGES_SUMMARY,
    )


@app.route("/cme")
def cme():
    """CME 比赛作战室（War Room）— MVP：手工录入快照 + localStorage"""
    return render_template(
        "cme.html",
        active="cme",
        currency_nav=DATA.CURRENCY_NAV,
    )


@app.route("/cme/symbol/<key>")
def cme_symbol(key):
    """CME 品种详情页：介绍 / 行情 / 现货 / 研报平台链接"""
    detail = DATA.CME_SYMBOL_DETAILS.get(key)
    if not detail:
        abort(404)
    return render_template(
        "cme_symbol.html",
        active="cme",
        currency_nav=DATA.CURRENCY_NAV,
        detail=detail,
        pages=DATA.CME_SYMBOL_PAGES,
    )


@app.route("/bond")
def bond():
    """债券板块：收益率曲线、利差、市场总览"""
    return render_template(
        "bond.html",
        active="bond",
        yield_curve=DATA.BOND_YIELD_CURVE,
        yield_history=DATA.BOND_YIELD_HISTORY_10Y,
        spreads=DATA.BOND_SPREADS,
        market_overview=DATA.BOND_MARKET_OVERVIEW,
        concepts=DATA.BOND_CONCEPTS,
        currency_nav=DATA.CURRENCY_NAV,
    )


@app.route("/credit")
def credit():
    """信贷板块：无风险利率、信用利差、中国信用债"""
    return render_template(
        "credit.html",
        active="credit",
        risk_free_rates=DATA.RISK_FREE_RATES,
        credit_spreads=DATA.CREDIT_SPREADS,
        china_credit=DATA.CHINA_CREDIT_BONDS,
        concepts=DATA.CREDIT_CONCEPTS,
        currency_nav=DATA.CURRENCY_NAV,
    )


@app.route("/futures/exchanges")
def futures_exchanges():
    """三大外汇期货交易所详细介绍"""
    return render_template(
        "exchanges.html",
        active="futures",
        exchanges=DATA.FX_EXCHANGES,
        summary=DATA.FX_EXCHANGES_SUMMARY,
        currency_nav=DATA.CURRENCY_NAV,
    )


@app.route("/explorer")
def explorer():
    """数据探索"""
    return render_template(
        "explorer.html",
        active="explorer",
        currencies=DATA.CURRENCIES,
        rates=DATA.INTEREST_RATES,
        sources=DATA.DATA_SOURCES_DETAIL,
        currency_nav=DATA.CURRENCY_NAV,
    )


@app.route("/feedback")
def feedback():
    """反馈与建议页面"""
    import json as _json
    import os
    feedbacks = []
    fb_path = os.path.join(_data_dir(), "feedback.json")
    if os.path.exists(fb_path):
        try:
            with open(fb_path, "r", encoding="utf-8") as f:
                feedbacks = _json.load(f)
        except Exception:
            feedbacks = []
    # 按时间倒序显示
    feedbacks = list(reversed(feedbacks))
    return render_template("feedback.html", active="feedback", feedbacks=feedbacks,
                           currency_nav=DATA.CURRENCY_NAV)


# ============================================================
# 外汇日报 / 周报
# ============================================================
@app.route("/reports")
def reports_index():
    """报告中心：列出所有日报和周报"""
    daily = DATA.DAILY_REPORTS
    weekly = DATA.WEEKLY_REPORTS
    return render_template("reports.html", active="reports",
                           daily_reports=daily, weekly_reports=weekly,
                           currency_nav=DATA.CURRENCY_NAV)


@app.route("/reports/daily/<date>")
def daily_report(date):
    """单篇日报详情"""
    report = None
    for r in DATA.DAILY_REPORTS:
        if r["date"] == date:
            report = r
            break
    if not report:
        abort(404)
    return render_template("daily_report.html", active="reports",
                           report=report,
                           daily_reports=DATA.DAILY_REPORTS,
                           currency_nav=DATA.CURRENCY_NAV)


@app.route("/reports/weekly/<date>")
def weekly_report(date):
    """单篇周报详情"""
    report = None
    for r in DATA.WEEKLY_REPORTS:
        if r["date"] == date:
            report = r
            break
    if not report:
        abort(404)
    return render_template("weekly_report.html", active="reports",
                           report=report,
                           weekly_reports=DATA.WEEKLY_REPORTS,
                           currency_nav=DATA.CURRENCY_NAV)


# ============================================================
# 数据 API
# ============================================================
@app.route("/api/snapshot")
def api_snapshot():
    return jsonify(DATA.MARKET_SNAPSHOT)


@app.route("/api/currency/<code>/history")
def api_currency_history(code):
    """货币历史数据 — 静态年度数据 + 当前年份自动用实时汇率刷新"""
    from datetime import datetime

    code = code.lower()
    cur = DATA.CURRENCIES.get(code)
    if not cur:
        return jsonify({"error": "unknown currency"}), 404

    history = list(cur.get("history", []))
    current_year = str(datetime.now().year)

    # 尝试用实时汇率刷新当前年份的数据点（USD/DXY 无单一货币对，跳过）
    pair = DATA.LIVE_PAIRS.get(code)
    if pair and cur.get("pair") != "DXY":
        from_ccy, to_ccy = pair["from"], pair["to"]
        try:
            live_data, _ = _fetch_latest_rates(from_ccy, [to_ccy])
            live_rates = live_data.get("rates", {})
            live_rate = live_rates.get(to_ccy)
            live_date = live_data.get("date", datetime.now().strftime("%Y-%m-%d"))
            is_fallback = bool(live_data.get("_fallback"))
            if live_rate:
                live_rate = round(float(live_rate), 4)
                event_suffix = f"（实时·{live_date}）" if not is_fallback else f"（兜底·{live_date}）"
                # 更新或追加当前年份
                updated = False
                for item in history:
                    if item.get("date") == current_year:
                        item["rate"] = live_rate
                        # 保留原事件描述的核心部分，只更新日期标注
                        orig_event = item.get("event", "")
                        # 去掉旧的日期标注括号
                        if "（" in orig_event:
                            orig_event = orig_event[:orig_event.index("（")]
                        item["event"] = orig_event + event_suffix
                        updated = True
                        break
                if not updated:
                    history.append({
                        "date": current_year,
                        "rate": live_rate,
                        "event": f"实时汇率{event_suffix}",
                    })
        except Exception:
            pass  # 实时获取失败时回退到静态数据

    return jsonify(history)


@app.route("/api/rates")
def api_rates():
    return jsonify(DATA.INTEREST_RATES)


@app.route("/api/currencies")
def api_currencies():
    """所有货币元信息"""
    result = []
    for code, cur in DATA.CURRENCIES.items():
        result.append({
            "code": code,
            "name": cur["name"],
            "pair": cur["pair"],
            "current": cur["current"],
            "trend": cur["trend"],
            "category": cur["category"],
        })
    return jsonify(result)


@app.route("/api/regression")
def api_regression():
    """利差-汇率 OLS 回归分析"""
    rates = DATA.INTEREST_RATES
    cur_map = {}
    for code, cur in DATA.CURRENCIES.items():
        if code == "usd":
            continue
        cur_map[code] = {h["date"]: h["rate"] for h in cur["history"]}

    def ols(points):
        n = len(points)
        if n < 2:
            return None
        xs = [p["x"] for p in points]
        ys = [p["y"] for p in points]
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        num = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
        den = sum((xs[i] - x_mean) ** 2 for i in range(n))
        if den == 0:
            return None
        b = num / den
        a = y_mean - b * x_mean
        ss_res = sum((ys[i] - (a + b * xs[i])) ** 2 for i in range(n))
        ss_tot = sum((ys[i] - y_mean) ** 2 for i in range(n))
        r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
        r = math.sqrt(r_squared) if r_squared >= 0 else 0
        return {
            "intercept": round(a, 4),
            "slope": round(b, 4),
            "r_squared": round(r_squared, 4),
            "r": round(r, 4),
            "n": n,
            "equation": f"y = {a:.2f} + {b:.2f}x",
        }

    result = {}
    for code, hist_map in cur_map.items():
        cur = DATA.CURRENCIES[code]
        rk_a, rk_b = cur["rate_pair"]
        pts = []
        for r in rates:
            d = r["date"]
            if "-" in d:
                continue
            a_val = r.get(rk_a)
            b_val = r.get(rk_b)
            if a_val is not None and b_val is not None and d in hist_map:
                pts.append({"x": round(a_val - b_val, 2), "y": hist_map[d], "year": d})
        reg = ols(pts)
        result[code] = {
            "points": pts,
            "regression": reg,
            "x_label": f"{cur['rate_context']}（百分点）",
            "y_label": cur["pair"],
            "interpretation": (
                f"斜率 {reg['slope']:.2f}：利差每扩大1个百分点，{cur['pair']}变动约 {reg['slope']:.2f}。"
                f"R²={reg['r_squared']:.2f}，利差解释了汇率变动的 {reg['r_squared']*100:.0f}%。"
            ) if reg else "数据不足",
        }
    return jsonify(result)


@app.route("/api/fed-rate")
def api_fed_rate():
    """美联储利率历史"""
    return jsonify(DATA.FED_RATE_HISTORY)


@app.route("/api/treasury")
def api_treasury():
    """美债收益率历史"""
    return jsonify(DATA.US_TREASURY_HISTORY)


@app.route("/api/dxy-components")
def api_dxy_components():
    """美元指数构成"""
    return jsonify(DATA.DXY_COMPONENTS)


@app.route("/api/fed-cycles")
def api_fed_cycles():
    """美联储政策周期"""
    return jsonify(DATA.FED_POLICY_CYCLES)


# ============================================================
# 实时汇率代理 API（多源 fallback：Frankfurter → exchangerate.host → 静态兜底）
# ============================================================
@app.route("/api/ticker")
def api_ticker():
    """全局滚动横条数据：返回主要货币对的实时汇率（一次请求获取全部）。"""
    from datetime import datetime

    # 主要交易货币对（以 USD 为基准）
    targets = ["EUR", "JPY", "GBP", "CNY", "CHF", "AUD", "CAD"]
    data, _ = _fetch_latest_rates("USD", targets)

    rates = data.get("rates", {})
    # 构建紧凑的 ticker 数据
    pairs = []
    pair_labels = {
        "EUR": ("EUR/USD", 4), "JPY": ("USD/JPY", 2), "GBP": ("GBP/USD", 4),
        "CNY": ("USD/CNY", 4), "CHF": ("USD/CHF", 4), "AUD": ("AUD/USD", 4),
        "CAD": ("USD/CAD", 4),
    }
    for code in targets:
        if code in rates:
            label, decimals = pair_labels.get(code, (f"USD/{code}", 4))
            # EUR/GBP/AUD/CAD 是间接标价，需要取倒数
            if code in ("EUR", "GBP", "AUD", "CAD"):
                rate = round(1.0 / rates[code], decimals) if rates[code] else 0
            else:
                rate = round(rates[code], decimals)
            pairs.append({"pair": label, "rate": rate, "code": code})

    return jsonify({
        "pairs": pairs,
        "date": data.get("date", ""),
        "source": data.get("_source", "Frankfurter API") if data.get("_source") else
                  (data.get("_fallbackSource", "备用数据") if data.get("_fallback") else "Frankfurter API"),
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/live/<base>")
def api_live(base):
    """获取 base 货币对所有关联货币的实时汇率（多源降级 + 60s 缓存）。"""
    from datetime import datetime

    base = base.upper()
    correlated = DATA.CORRELATED_CODES.get(base, ["USD", "EUR", "JPY", "GBP", "CNY"])
    targets = list(dict.fromkeys([base] + correlated))

    data, _ = _fetch_latest_rates(base, targets)

    resp = dict(data)  # copy，避免污染缓存
    resp["generatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    resp["cacheFor"] = f"{_CACHE_TTL_SEC}s"
    return jsonify(resp)


@app.route("/api/live/<base>/history")
def api_live_history(base):
    """获取 base 货币近 30 天历史汇率（多源降级）。"""
    from datetime import datetime, timedelta

    base = base.upper()
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    data, _ = _fetch_range_rates(base, "USD", start, end)
    resp = dict(data)
    resp["generatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(resp)


@app.route("/api/currency/<code>/monthly")
def api_currency_monthly(code):
    """近 12 个月月度汇率（每月最后一个工作日）— 多源降级版本。"""
    from datetime import datetime, timedelta

    code = code.lower()
    cur = DATA.CURRENCIES.get(code)
    if not cur:
        return jsonify({"error": "unknown currency"}), 404

    pair = DATA.LIVE_PAIRS.get(code)
    if not pair:
        return jsonify({"error": "live data not supported for this currency"}), 400

    from_ccy = pair["from"]
    to_ccy = pair["to"]

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
    data, _ = _fetch_range_rates(from_ccy, to_ccy, start, end)

    rates = data.get("rates", {})
    monthly = {}
    for date_str, rate_obj in rates.items():
        month_key = date_str[:7]
        rate_val = rate_obj.get(to_ccy) if isinstance(rate_obj, dict) else rate_obj
        if rate_val is None:
            continue
        monthly[month_key] = {"date": date_str, "rate": rate_val}

    result = [v for k, v in sorted(monthly.items())]
    result = result[-12:]

    source = "Frankfurter API"
    if data.get("_source"):
        source = data["_source"]
    elif data.get("_fallback"):
        source = f"{data.get('_fallbackSource', 'static fallback')}"

    return jsonify({
        "currency": code,
        "pair": pair["label"],
        "from": from_ccy,
        "to": to_ccy,
        "data": result,
        "source": source,
        "fallback": bool(data.get("_fallback")),
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/currency/<code>/daily")
def api_currency_daily(code):
    """近 30 天日度汇率 — 多源降级版本。"""
    from datetime import datetime, timedelta

    code = code.lower()
    cur = DATA.CURRENCIES.get(code)
    if not cur:
        return jsonify({"error": "unknown currency"}), 404

    pair = DATA.LIVE_PAIRS.get(code)
    if not pair:
        return jsonify({"error": "live data not supported for this currency"}), 400

    from_ccy = pair["from"]
    to_ccy = pair["to"]

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
    data, _ = _fetch_range_rates(from_ccy, to_ccy, start, end)

    rates = data.get("rates", {})
    result = []
    for d, r in rates.items():
        rate_val = r.get(to_ccy) if isinstance(r, dict) else r
        if rate_val is None:
            continue
        result.append({"date": d, "rate": rate_val})
    result.sort(key=lambda x: x["date"])
    result = result[-30:]

    source = "Frankfurter API"
    if data.get("_source"):
        source = data["_source"]
    elif data.get("_fallback"):
        source = f"{data.get('_fallbackSource', 'static fallback')}"

    return jsonify({
        "currency": code,
        "pair": pair["label"],
        "from": from_ccy,
        "to": to_ccy,
        "data": result,
        "source": source,
        "fallback": bool(data.get("_fallback")),
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


# ============================================================
# 反馈与建议 API（保存到本地 feedback.json）
# ============================================================
@app.route("/api/feedback", methods=["POST"])
def api_submit_feedback():
    """提交反馈或建议，保存到本地文件"""
    import json as _json
    import os
    from datetime import datetime

    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "反馈内容不能为空"}), 400

    fb = {
        "category": data.get("category", "其他").strip() or "其他",
        "content": content,
        "contact": (data.get("contact") or "").strip(),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    fb_path = os.path.join(_data_dir(), "feedback.json")
    feedbacks = []
    if os.path.exists(fb_path):
        try:
            with open(fb_path, "r", encoding="utf-8") as f:
                feedbacks = _json.load(f)
        except Exception:
            feedbacks = []

    feedbacks.append(fb)
    with open(fb_path, "w", encoding="utf-8") as f:
        _json.dump(feedbacks, f, ensure_ascii=False, indent=2)

    # 异步发送邮件通知管理员（失败不影响反馈保存）
    mail_ok, mail_msg = _send_feedback_mail(fb)

    return jsonify({"success": True, "message": "反馈已提交，感谢您的建议！", "mail_sent": mail_ok})


@app.route("/api/feedback", methods=["GET"])
def api_list_feedback():
    """获取所有反馈"""
    import json as _json
    import os

    fb_path = os.path.join(_data_dir(), "feedback.json")
    feedbacks = []
    if os.path.exists(fb_path):
        try:
            with open(fb_path, "r", encoding="utf-8") as f:
                feedbacks = _json.load(f)
        except Exception:
            feedbacks = []
    return jsonify(list(reversed(feedbacks)))


# ============================================================
# CME 小窝：快照持久化 API（本地文件 + 可选客户端密钥隔离）
# ============================================================
def _load_cme_snapshots():
    """读取所有 CME 快照（云端优先，本地兜底）。"""
    return _cme_load("snapshots", [])


def _save_cme_snapshots(snapshots):
    """写入 CME 快照列表（本地 + 云端双写）。"""
    _cme_save("snapshots", snapshots)


@app.route("/api/cme/snapshots", methods=["GET"])
def api_cme_get_snapshots():
    """获取全部 CME 快照。"""
    snapshots = _load_cme_snapshots()
    snapshots.sort(key=lambda s: s.get("createdAt", 0), reverse=True)
    return jsonify(snapshots)


@app.route("/api/cme/snapshots", methods=["POST"])
def api_cme_add_snapshot():
    """新增单条快照。"""
    data = request.get_json(silent=True) or {}
    snap = data.get("snapshot") or data
    symbol = (snap.get("symbol") or "").strip()
    price = snap.get("price")
    if not symbol or price is None:
        return jsonify({"error": "symbol 和 price 不能为空"}), 400
    item = {
        "symbol": symbol,
        "price": price,
        "change": snap.get("change"),
        "date": snap.get("date") or time.strftime("%Y-%m-%d", time.localtime()),
        "time": snap.get("time") or time.strftime("%H:%M", time.localtime()),
        "note": (snap.get("note") or "").strip(),
        "createdAt": int(snap.get("createdAt") or time.time() * 1000),
    }
    snapshots = _load_cme_snapshots()
    snapshots.append(item)
    _save_cme_snapshots(snapshots)
    return jsonify({"success": True, "snapshot": item})


@app.route("/api/cme/snapshots/batch", methods=["POST"])
def api_cme_batch_snapshots():
    """批量导入快照（CSV 解析结果）。"""
    data = request.get_json(silent=True) or {}
    items = data.get("snapshots") or []
    if not isinstance(items, list) or not items:
        return jsonify({"error": "snapshots 列表不能为空"}), 400
    snapshots = _load_cme_snapshots()
    added = 0
    base_ts = int(time.time() * 1000)
    for idx, snap in enumerate(items):
        symbol = (snap.get("symbol") or "").strip()
        price = snap.get("price")
        if not symbol or price is None:
            continue
        snapshots.append({
            "symbol": symbol,
            "price": price,
            "change": snap.get("change"),
            "date": snap.get("date") or time.strftime("%Y-%m-%d", time.localtime()),
            "time": snap.get("time") or time.strftime("%H:%M", time.localtime()),
            "note": (snap.get("note") or "").strip(),
            "createdAt": int(snap.get("createdAt") or (base_ts + idx)),
        })
        added += 1
    _save_cme_snapshots(snapshots)
    return jsonify({"success": True, "added": added})


@app.route("/api/cme/snapshots", methods=["DELETE"])
def api_cme_delete_snapshot():
    """按 createdAt 删除单条快照。"""
    data = request.get_json(silent=True) or {}
    target = data.get("createdAt")
    if target is None:
        return jsonify({"error": "缺少 createdAt"}), 400
    snapshots = _load_cme_snapshots()
    before = len(snapshots)
    snapshots = [s for s in snapshots if int(s.get("createdAt", 0)) != int(target)]
    _save_cme_snapshots(snapshots)
    return jsonify({"success": True, "removed": before - len(snapshots)})


# ============================================================
# CME 小窝 · 四大模块后端（Macro Score / Event Scenario / Trade Planner / Risk Engine）
# 数据模型对应任务书第 6 节；API 对应第 7 节。全部落本地 JSON 文件，换浏览器/清缓存不丢。
# ============================================================
import uuid as _uuid


# ---- 云存储（Upstash Redis REST）：线上部署时数据不丢的权威来源 ----
# 在 Vercel 环境变量配置 UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN 即启用；
# 未配置时自动退回本地 JSON 文件（本地开发模式），两套行为完全兼容。
def _kv_env():
    """返回 (url, token)；未配置时返回 None。"""
    url = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or ""
    return (url, token) if url and token else None


def _kv_get(key):
    """从 Upstash 读取并反序列化；任何异常返回 None（调用方自行兜底）。"""
    try:
        url, token = _kv_env()
        req = urllib.request.Request(
            url + "/get/" + key,
            headers={"Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = _json.loads(resp.read().decode("utf-8"))
        result = (body or {}).get("result")
        return _json.loads(result) if result is not None else None
    except Exception:
        return None


def _kv_set(key, value):
    """把 value 序列化后写入 Upstash；返回是否成功。"""
    try:
        url, token = _kv_env()
        payload = _json.dumps(value, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url + "/set/" + key,
            data=payload,
            method="POST",
            headers={"Authorization": "Bearer " + token,
                     "Content-Type": "text/plain"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            _json.loads(resp.read().decode("utf-8"))
        return True
    except Exception:
        return False


# CME 小窝全部数据集合（导出/导入也按此清单）
_CME_COLLECTIONS = (
    "snapshots",     # 手工行情快照
    "signals",       # 模块 A：Macro Score 信号
    "events",        # 模块 B：经济事件
    "scenarios",     # 模块 B：事件情景推演
    "event_config",  # V2：Event 状态机 + Surprise 三情景阈值配置
    "proposals",     # 模块 C：交易计划
    "positions",     # 模块 D：持仓
    "journal",       # 模块 D：交易日志
    "risk_config",   # 模块 D：风控参数
)


def _cme_file_path(name):
    """返回 CME 模块数据文件路径。"""
    return os.path.join(_data_dir(), "cme_" + name + ".json")


try:  # 演示数据随代码部署，保证线上首次打开就能看到每个功能的完整示例
    from cme_seed import CME_DEMO_SEED as _CME_DEMO_SEED
except Exception:  # pragma: no cover - 缺少演示数据时退化为空
    _CME_DEMO_SEED = {}


def _cme_demo(name):
    """返回演示数据的深拷贝；该集合没有演示数据时返回 None。

    cme_*.json 已被 .gitignore 忽略（运行期数据线上走 Upstash KV），
    因此全新部署时云端与本地都为空，页面会是一片空白。
    这里提供一份可交互的示例数据兜底，让「使用方式」在真实网页上可见。
    """
    data = _CME_DEMO_SEED.get(name)
    if data is None:
        return None
    try:  # 用 JSON 往返做深拷贝，避免调用方原地修改污染模块级常量
        return _json.loads(_json.dumps(data, ensure_ascii=False))
    except Exception:
        return None


def _cme_load(name, default):
    """通用读取：云端优先 → 本地 JSON 文件 → 演示数据 → 调用方默认值。"""
    if _kv_env():
        data = _kv_get("parite:cme:" + name)
        if data is not None:
            return data
    path = _cme_file_path(name)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            if data is not None:  # 空列表/空字典是用户的有意结果，需尊重
                return data
        except Exception:
            pass
    demo = _cme_demo(name)
    return demo if demo is not None else default


_cme_demo_state = {}  # name -> (checked_at, is_demo)，避免每次请求都打 KV
_CME_DEMO_STATE_TTL = 60.0


def _cme_is_demo(name):
    """当前集合是否正在展示演示数据（云端无数据 且 本地文件不存在）。"""
    cached = _cme_demo_state.get(name)
    if cached and (time.time() - cached[0]) < _CME_DEMO_STATE_TTL:
        return cached[1]
    flag = False
    if name in _CME_DEMO_SEED:
        has_cloud = False
        if _kv_env():
            has_cloud = _kv_get("parite:cme:" + name) is not None
        flag = (not has_cloud) and (not os.path.exists(_cme_file_path(name)))
    _cme_demo_state[name] = (time.time(), flag)
    return flag


def _cme_save(name, data):
    """通用写入：本地文件 + 云端 KV 双写（云端失败不影响本地保存）。"""
    try:
        with open(_cme_file_path(name), "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    if _kv_env():
        _kv_set("parite:cme:" + name, data)


def _now_ms():
    return int(time.time() * 1000)


def _new_id():
    return _uuid.uuid4().hex[:12]


# ---- 比赛时间（2026 CME University Trading Challenge，10/4 - 10/30）----
COMPETITION_START = "2026-10-04"
COMPETITION_END = "2026-10-30"


def _competition_info():
    """返回比赛倒计时 / 状态。"""
    now = time.strftime("%Y-%m-%d", time.localtime())
    started = now >= COMPETITION_START
    ended = now > COMPETITION_END
    return {
        "now": now,
        "start": COMPETITION_START,
        "end": COMPETITION_END,
        "started": started,
        "ended": ended,
    }


# ---- 模块 A：Macro Score 打分引擎 ----
# 因子权重采用配置化（默认人工可解释权重），第二版再回归优化。
MACRO_SCORE_FACTORS = [
    {"key": "dxy", "label": "美元指数 DXY", "weight": 2,
     "options": [{"v": "down", "score": 2, "label": "走弱"}, {"v": "flat", "score": 0, "label": "震荡"},
                 {"v": "up", "score": -2, "label": "走强"}]},
    {"key": "real_yield", "label": "美实际利率", "weight": 2,
     "options": [{"v": "down", "score": 2, "label": "下行"}, {"v": "flat", "score": 0, "label": "持平"},
                 {"v": "up", "score": -2, "label": "上行"}]},
    {"key": "fed_expect", "label": "美联储预期", "weight": 1,
     "options": [{"v": "dovish", "score": 1, "label": "鸽派"}, {"v": "neutral", "score": 0, "label": "中性"},
                 {"v": "hawkish", "score": -1, "label": "鹰派"}]},
    {"key": "risk_sentiment", "label": "风险情绪", "weight": 1,
     "options": [{"v": "risk_off", "score": 1, "label": "避险"}, {"v": "neutral", "score": 0, "label": "中性"},
                 {"v": "risk_on", "score": -1, "label": "风险偏好"}]},
    {"key": "momentum", "label": "动量", "weight": 1,
     "options": [{"v": "oversold", "score": 1, "label": "超卖"}, {"v": "neutral", "score": 0, "label": "中性"},
                 {"v": "overbought", "score": -1, "label": "超买"}]},
]


def _score_to_bias(total):
    if total >= 5:
        return "strong_bullish"
    if total >= 2:
        return "bullish"
    if total <= -5:
        return "strong_bearish"
    if total <= -2:
        return "bearish"
    return "neutral"


def _build_signal(symbol, price, factors, drivers, invalidation, range_pct=1.0):
    """根据因子状态计算总分，生成结构化 signal（模块 A 输出）。"""
    template = {t["key"]: t for t in MACRO_SCORE_FACTORS}
    total = 0
    factor_detail = []
    for f in factors:
        key = f["key"]
        state = f.get("state", "flat")
        defn = template.get(key) or {}
        weight = defn.get("weight", 0)
        score = 0
        label = "中性"
        for opt in defn.get("options", []):
            if opt["v"] == state:
                score = opt["score"]
                label = opt["label"]
                break
        total += score * weight
        factor_detail.append({"key": key, "label": defn.get("label", key), "state": state,
                              "state_label": label, "score": score, "weight": weight})
    bias = _score_to_bias(total)
    # confidence：信号一致性 + 因子离散度（人工可解释，非概率真值）
    consistency = min(1.0, abs(total) / 7.0)
    confidence = int(round(40 + consistency * 50))
    price = float(price)
    return {
        "symbol": symbol,
        "price": price,
        "bias": bias,
        "macro_score": total,
        "confidence": confidence,
        "range_low": round(price * (1 - range_pct / 100.0), 4),
        "range_high": round(price * (1 + range_pct / 100.0), 4),
        "drivers": drivers or [],
        "invalidation": invalidation or [],
        "factors": factor_detail,
        "model_version": "macro_score_v1",
        "timestamp": _now_ms(),
    }


def _load_signals():
    return _cme_load("signals", [])


def _save_signals(signals):
    _cme_save("signals", signals)


# ---- 模块 B：Event Scenario 引擎 ----
MAX_EVENT_SHOTS = 3                      # 每个事件最多 3 张资讯截图
MAX_SHOT_DATA_LEN = 300_000              # 单张 data URL 字符上限（≈220KB，压缩后资讯截图足够清晰）


def _load_events():
    return _cme_load("events", [])


def _save_events(events):
    _cme_save("events", events)


def _load_scenarios():
    return _cme_load("scenarios", [])


def _save_scenarios(scenarios):
    _cme_save("scenarios", scenarios)


# ---- V2：Event 状态机 + Surprise 三情景（确定性引擎，非 AI）----
# 状态机只允许顺序推进；actual 落地时由系统自动置为 RELEASED。
EVENT_STATUS_FLOW = ("SCHEDULED", "PRE_EVENT", "RELEASED", "POST_EVENT", "ARCHIVED")

DEFAULT_EVENT_SCENARIO_CONFIG = {
    "mode": "fixed_pp",        # 第一版：固定百分点阈值；未来升级 Standardized Surprise（Z-score）
    "strongPositive": 0.2,     # surprise >= +0.2pp → HOT
    "neutralUpper": 0.2,       # surprise <  +0.2pp → INLINE
    "neutralLower": -0.2,      # surprise >  -0.2pp → INLINE
    "strongNegative": -0.2,    # surprise <= -0.2pp → COOL
    "zscore_std": None,        # 预留：历史预测误差标准差（surprise_z = surprise / std）
}


def _load_event_config():
    return _cme_load("event_config", dict(DEFAULT_EVENT_SCENARIO_CONFIG))


def _save_event_config(cfg):
    _cme_save("event_config", cfg)


# 事件类型模板：CPI 完整链路 + 常见事件类型扩展（NFP/FOMC/零售销售/ECB/BOJ）。
# 每个场景的 transmission / asset_impacts / counter_case / invalidation 均为确定性内容，
# 数据公布后绝不重新编故事，只冻结并标记触发的情景。
# threshold 为各类事件的匹配阈值（与数值单位量级匹配）；缺省回退到全局事件配置。
EVENT_TYPE_DEFS = {
    "CPI": {
        "label": "US CPI",
        "country": "US",
        "metric": "整体 CPI 同比",
        "unit": "%",
        "sourceId": "bloomberg-econ",
        "threshold": {"positive": 0.2, "negative": -0.2},
        "transmission_map": [
            "CPI", "Fed Expectations", "US 2Y Yield", "DXY", "Gold / EUR / NQ",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "通胀超预期",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +0.2 个百分点",
                "transmission": [
                    "通胀超预期 ↑",
                    "市场对美联储降息的预期 ↓",
                    "美国 2 年期国债收益率 ↑",
                    "美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "长久期股票估值承压 ↑ → 纳斯达克 ↓",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "纳斯达克", "direction": "down", "label": "↓"},
                ],
                "counter_case": "市场可能已在数据公布前提前计入鹰派预期，公布后反而出现“利好出尽”式回落；或核心分项意外温和，削弱整体超预期的传导。",
                "invalidation": ["美国 2 年期收益率未上行", "美元指数未走强", "核心 CPI 分项温和"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±0.2 个百分点之间",
                "transmission": [
                    "宏观事件本身未带来足够大的意外。",
                    "价格反应更多取决于持仓结构、数据修正、核心 CPI 分项以及市场已有预期。",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "纳斯达克", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使整体数据符合预期，核心分项或季调修正仍可能主导即时反应。",
                "invalidation": ["美国 2 年期收益率出现 >10bp 的方向性波动", "美元指数突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "通胀低于预期",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -0.2 个百分点",
                "transmission": [
                    "通胀低于预期 ↓",
                    "市场对美联储降息的预期 ↑",
                    "美国 2 年期国债收益率 ↓",
                    "美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "折现率 ↓ → 利好纳斯达克 ↑",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "纳斯达克", "direction": "up", "label": "↑"},
                ],
                "counter_case": "若通胀预期锚定牢固或核心分项仍然偏强，市场可能对整体数据下修反应平淡。",
                "invalidation": ["美国 2 年期收益率未下行", "美元指数未走弱"],
            },
        ],
    },
    "NFP": {
        "label": "US Nonfarm Payrolls",
        "country": "US",
        "metric": "非农就业人数",
        "unit": "K",
        "sourceId": "bloomberg-econ",
        "threshold": {"positive": 20, "negative": -20},
        "transmission_map": [
            "Nonfarm Payrolls", "Fed Expectations", "US 2Y Yield", "DXY", "Gold / EUR / NQ",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "就业数据超预期",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +20K（2 万人）",
                "transmission": [
                    "非农就业超预期 ↑",
                    "劳动力市场强劲 → 美联储推迟降息的预期 ↑",
                    "美国 2 年期国债收益率 ↑",
                    "美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "利率维持高位 → 估值承压 → 纳斯达克 ↓",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "纳斯达克", "direction": "down", "label": "↓"},
                ],
                "counter_case": "若薪资增速放缓或失业率同步上升，总人数超预期的鹰派含义会被削弱；失业率走弱（萨姆规则升温）时市场反而可能交易降息预期。",
                "invalidation": ["美国 2 年期收益率未上行", "美元指数未走强", "失业率明显上升"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±20K 之间",
                "transmission": [
                    "宏观事件本身未带来足够大的意外。",
                    "价格反应更多取决于薪资增速、失业率与劳动参与率等分项以及市场已有预期。",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "纳斯达克", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使总人数符合预期，薪资增速或失业率的意外仍可能主导即时反应。",
                "invalidation": ["美国 2 年期收益率出现 >10bp 的方向性波动", "美元指数突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "就业数据不及预期",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -20K（2 万人）",
                "transmission": [
                    "非农就业不及预期 ↓",
                    "劳动力市场转弱 → 美联储提前降息的预期 ↑",
                    "美国 2 年期国债收益率 ↓",
                    "美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "折现率 ↓ → 利好纳斯达克 ↑",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "纳斯达克", "direction": "up", "label": "↑"},
                ],
                "counter_case": "若就业走弱但薪资增速仍偏高（工资-物价螺旋担忧），市场可能对单月数据反应平淡。",
                "invalidation": ["美国 2 年期收益率未下行", "美元指数未走弱"],
            },
        ],
    },
    "FOMC": {
        "label": "FOMC 利率决议",
        "country": "US",
        "metric": "联邦基金目标利率",
        "unit": "%",
        "sourceId": "federalreserve",
        "threshold": {"positive": 0.25, "negative": -0.25},
        "transmission_map": [
            "FOMC Decision", "Fed Funds Path", "US 2Y Yield", "DXY", "Gold / EUR / NQ",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "决议偏鹰",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +0.25（25 个基点）",
                "transmission": [
                    "利率决议偏鹰 ↑",
                    "政策路径比预期更紧 → 降息预期 ↓",
                    "美国 2 年期国债收益率 ↑",
                    "美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "利率维持高位 → 估值承压 → 纳斯达克 ↓",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "纳斯达克", "direction": "down", "label": "↓"},
                ],
                "counter_case": "点阵图与新闻发布会措辞可能比利率结果本身更关键；若发布会释放宽松信号，鹰派效果或被对冲。",
                "invalidation": ["美国 2 年期收益率未上行", "美元指数未走强", "点阵图 / 发布会措辞偏鸽"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±0.25（25 个基点）之间",
                "transmission": [
                    "利率决议符合市场预期。",
                    "价格反应取决于点阵图、经济预测与新闻发布会措辞的边际变化。",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "纳斯达克", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使利率结果符合预期，点阵图或发布会措辞仍可能主导即时反应。",
                "invalidation": ["美国 2 年期收益率出现 >10bp 的方向性波动", "美元指数突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "决议偏鸽",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -0.25（25 个基点）",
                "transmission": [
                    "利率决议偏鸽 ↓",
                    "政策路径比预期更松 → 降息预期 ↑",
                    "美国 2 年期国债收益率 ↓",
                    "美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "折现率 ↓ → 利好纳斯达克 ↑",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "纳斯达克", "direction": "up", "label": "↑"},
                ],
                "counter_case": "若点阵图仍显示年内不会多次降息，市场可能认为鸽派幅度有限。",
                "invalidation": ["美国 2 年期收益率未下行", "美元指数未走弱"],
            },
        ],
    },
    "RETAIL_SALES": {
        "label": "US Retail Sales",
        "country": "US",
        "metric": "零售销售环比",
        "unit": "%",
        "sourceId": "bloomberg-econ",
        "threshold": {"positive": 0.2, "negative": -0.2},
        "transmission_map": [
            "Retail Sales", "Fed Expectations", "US 2Y Yield", "DXY", "Gold / EUR / NQ",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "消费数据超预期",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +0.2 个百分点",
                "transmission": [
                    "零售销售超预期 ↑",
                    "消费韧性 → 美联储维持高利率的预期 ↑",
                    "美国 2 年期国债收益率 ↑",
                    "美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "利率维持高位 → 估值承压 → 纳斯达克 ↓",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "纳斯达克", "direction": "down", "label": "↓"},
                ],
                "counter_case": "零售数据月度波动大且常被大幅修正；剔除汽车/能源的核心零售分项可能给出不同信号。",
                "invalidation": ["美国 2 年期收益率未上行", "美元指数未走强"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±0.2 个百分点之间",
                "transmission": [
                    "宏观事件本身未带来足够大的意外。",
                    "价格反应更多取决于上期修正值与核心零售（剔除汽车/能源）分项。",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "纳斯达克", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "上期数据的大幅修正可能改变市场对消费趋势的判断。",
                "invalidation": ["美国 2 年期收益率出现 >10bp 的方向性波动", "美元指数突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "消费数据不及预期",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -0.2 个百分点",
                "transmission": [
                    "零售销售不及预期 ↓",
                    "消费转弱 → 美联储提前降息的预期 ↑",
                    "美国 2 年期国债收益率 ↓",
                    "美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "折现率 ↓ → 利好纳斯达克 ↑",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "纳斯达克", "direction": "up", "label": "↑"},
                ],
                "counter_case": "若数据疲软被归因于一次性因素（天气 / 节假日错位），市场可能不将其视为趋势信号。",
                "invalidation": ["美国 2 年期收益率未下行", "美元指数未走弱"],
            },
        ],
    },
    "ECB": {
        "label": "ECB 利率决议",
        "country": "EU",
        "metric": "欧元区存款便利利率",
        "unit": "%",
        "sourceId": "ecb",
        "threshold": {"positive": 0.25, "negative": -0.25},
        "transmission_map": [
            "ECB Decision", "EUR Rate Path", "DE 10Y Yield", "EUR / DXY", "SX5E / XAU",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "决议偏鹰",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +0.25（25 个基点）",
                "transmission": [
                    "欧央行决议偏鹰 ↑",
                    "欧元区政策路径比预期更紧 → 降息预期 ↓",
                    "德国 10 年期国债收益率 ↑",
                    "欧元 ↑ → 美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "欧元区风险资产承压 → 欧洲斯托克 50 ↓",
                ],
                "asset_impacts": [
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "欧洲斯托克 50", "direction": "down", "label": "↓"},
                ],
                "counter_case": "拉加德发布会措辞若强调增长下行风险，可能对冲鹰派利率结果；欧元区经济基本面偏弱时鹰派传导有限。",
                "invalidation": ["德国 10 年期收益率未上行", "欧元兑美元未走强", "发布会措辞偏鸽"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±0.25（25 个基点）之间",
                "transmission": [
                    "利率决议符合市场预期。",
                    "价格反应取决于发布会措辞、经济预测与分步降息路径的边际变化。",
                ],
                "asset_impacts": [
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "欧洲斯托克 50", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使利率结果符合预期，发布会措辞或前瞻指引仍可能主导即时反应。",
                "invalidation": ["德国 10 年期收益率出现 >10bp 的方向性波动", "欧元兑美元突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "决议偏鸽",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -0.25（25 个基点）",
                "transmission": [
                    "欧央行决议偏鸽 ↓",
                    "欧元区政策路径比预期更松 → 降息预期 ↑",
                    "德国 10 年期国债收益率 ↓",
                    "欧元 ↓ → 美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "宽松预期 → 欧元区风险资产受益 → 欧洲斯托克 50 ↑",
                ],
                "asset_impacts": [
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "欧洲斯托克 50", "direction": "up", "label": "↑"},
                ],
                "counter_case": "若市场已充分定价降息，鸽派结果可能被解读为“利好出尽”。",
                "invalidation": ["德国 10 年期收益率未下行", "欧元兑美元未走弱"],
            },
        ],
    },
    "BOJ": {
        "label": "BOJ 利率决议",
        "country": "JP",
        "metric": "日本央行政策利率",
        "unit": "%",
        "sourceId": "boj",
        "threshold": {"positive": 0.25, "negative": -0.25},
        "transmission_map": [
            "BOJ Decision", "JPY Rate Path", "JGB 10Y Yield", "USDJPY", "Nikkei / XAU",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "决议偏鹰",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +0.25（25 个基点）",
                "transmission": [
                    "日央行决议偏鹰 ↑",
                    "日本政策路径比预期更紧 → 加息预期 ↑",
                    "日本 10 年期国债收益率 ↑",
                    "日元升值 → 美元兑日元 ↓",
                    "日元走强 → 出口盈利承压 → 日经 225 ↓；日元走强 → 美元走弱 → 黄金 ↑",
                ],
                "asset_impacts": [
                    {"asset": "美元兑日元", "direction": "down", "label": "↓"},
                    {"asset": "日经 225", "direction": "down", "label": "↓"},
                    {"asset": "日本国债收益率", "direction": "up", "label": "↑"},
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                ],
                "counter_case": "若植田和男发布会强调维持宽松立场，鹰派结果可能被迅速回吐；日元套息交易平仓节奏也可能扭曲即时反应。",
                "invalidation": ["美元兑日元未走弱", "日本 10 年期收益率未上行"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±0.25（25 个基点）之间",
                "transmission": [
                    "利率决议符合市场预期。",
                    "价格反应取决于发布会措辞、季度展望与购债规模调整的边际变化。",
                ],
                "asset_impacts": [
                    {"asset": "美元兑日元", "direction": "flat", "label": "震荡"},
                    {"asset": "日经 225", "direction": "flat", "label": "震荡"},
                    {"asset": "日本国债收益率", "direction": "flat", "label": "震荡"},
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使利率结果符合预期，购债缩减或汇率口头干预仍可能主导即时反应。",
                "invalidation": ["美元兑日元突破近期区间", "日本 10 年期收益率出现 >10bp 方向性波动"],
            },
            {
                "key": "COOL",
                "name": "决议偏鸽",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -0.25（25 个基点）",
                "transmission": [
                    "日央行决议偏鸽 ↓",
                    "日本政策路径比预期更松 → 加息预期 ↓",
                    "日本 10 年期国债收益率 ↓",
                    "日元贬值 → 美元兑日元 ↑",
                    "日元贬值 → 出口盈利改善 → 日经 225 ↑；日元贬值 → 美元走强 → 黄金 ↓",
                ],
                "asset_impacts": [
                    {"asset": "美元兑日元", "direction": "up", "label": "↑"},
                    {"asset": "日经 225", "direction": "up", "label": "↑"},
                    {"asset": "日本国债收益率", "direction": "down", "label": "↓"},
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                ],
                "counter_case": "若鸽派被解读为对全球衰退的确认（避险模式），日元反而可能走强、日股回落。",
                "invalidation": ["美元兑日元未走强", "日本 10 年期收益率未下行"],
            },
        ],
    },
    "FED_SPEECH": {
        "label": "美联储官员讲话",
        "country": "US",
        "metric": "讲话基调分（鹰派为正）",
        "unit": "分",
        "sourceId": "federalreserve",
        "threshold": {"positive": 0.5, "negative": -0.5},
        "transmission_map": [
            "Fed Speech", "Rate Expectations", "US 2Y Yield", "DXY", "Gold / US500",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "讲话偏鹰",
                "tag": "鹰派意外",
                "trigger_rule": "基调分 vs 预期 ≥ +0.5（明显偏鹰）",
                "transmission": [
                    "官员讲话偏鹰 ↑",
                    "市场对降息路径的预期推迟 → 降息预期 ↓",
                    "美国 2 年期国债收益率 ↑",
                    "美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "利率预期上移 → 长久期估值承压 → 纳斯达克 ↓",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "纳斯达克", "direction": "down", "label": "↓"},
                ],
                "counter_case": "官员讲话对市场影响取决于其投票权与市场地位；若讲话后其他官员随即对冲或点阵图预期未变，鹰派传导可能快速回吐。",
                "invalidation": ["美国 2 年期收益率未上行", "美元指数未走强", "讲话被其他官员对冲"],
            },
            {
                "key": "INLINE",
                "name": "讲话中性",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "基调分 vs 预期落在 ±0.5 之间",
                "transmission": [
                    "讲话基调与市场预期基本一致。",
                    "价格反应取决于具体措辞细节、是否重申数据依赖以及提问环节的边际表态。",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "纳斯达克", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使整体中性，个别关键措辞（如对通胀、就业的定性）仍可能主导即时反应。",
                "invalidation": ["美国 2 年期收益率出现 >10bp 的方向性波动", "美元指数突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "讲话偏鸽",
                "tag": "鸽派意外",
                "trigger_rule": "基调分 vs 预期 ≤ -0.5（明显偏鸽）",
                "transmission": [
                    "官员讲话偏鸽 ↓",
                    "市场对降息路径的预期提前 → 降息预期 ↑",
                    "美国 2 年期国债收益率 ↓",
                    "美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "利率预期下移 → 估值支撑 → 纳斯达克 ↑",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "纳斯达克", "direction": "up", "label": "↑"},
                ],
                "counter_case": "若鸽派表述与近期数据指引相矛盾，或市场担心只是“口头安抚”，反应可能有限甚至反向。",
                "invalidation": ["美国 2 年期收益率未下行", "美元指数未走弱"],
            },
        ],
    },
    "GDP": {
        "label": "美国 GDP",
        "country": "US",
        "metric": "美国 GDP 环比年化",
        "unit": "%",
        "sourceId": "bloomberg-econ",
        "threshold": {"positive": 0.3, "negative": -0.3},
        "transmission_map": [
            "US GDP", "Growth Surprise", "US 10Y Yield", "DXY", "Gold / US500",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "增长超预期",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +0.3 个百分点",
                "transmission": [
                    "经济增长超预期 ↑",
                    "衰退担忧 ↓ → 降息预期 ↓",
                    "美国 10 年期国债收益率 ↑",
                    "美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "基本面支撑盈利，但利率上移压制估值 → 标普 500 分化或承压",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "标普 500", "direction": "down", "label": "↓"},
                ],
                "counter_case": "若市场将强劲增长解读为盈利利好而非通胀风险，风险资产可能不跌反涨；或分项（库存、净出口）质量不高时传导减弱。",
                "invalidation": ["美国 10 年期收益率未上行", "美元指数未走强", "增长分项结构偏弱"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±0.3 个百分点之间",
                "transmission": [
                    "增长数据本身未带来足够大的意外。",
                    "价格反应更多取决于分项质量、消费韧性以及市场对衰退路径的既定判断。",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "标普 500", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使整体符合预期，消费、投资与库存分项的组合仍可能主导即时反应。",
                "invalidation": ["美国 10 年期收益率出现 >10bp 的方向性波动", "美元指数突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "增长不及预期",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -0.3 个百分点",
                "transmission": [
                    "经济增长不及预期 ↓",
                    "衰退担忧 ↑ → 降息预期 ↑",
                    "美国 10 年期国债收益率 ↓",
                    "美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "盈利预期下修压制股市，但降息预期提供支撑 → 标普 500 分化",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "标普 500", "direction": "down", "label": "↓"},
                ],
                "counter_case": "若走弱被解读为滞胀信号（增长与通胀同弱）或衰退确认，黄金与股市可能同涨，美元未必下跌。",
                "invalidation": ["美国 10 年期收益率未下行", "美元指数未走弱"],
            },
        ],
    },
    "PPI": {
        "label": "美国 PPI",
        "country": "US",
        "metric": "美国 PPI 同比",
        "unit": "%",
        "sourceId": "bloomberg-econ",
        "threshold": {"positive": 0.2, "negative": -0.2},
        "transmission_map": [
            "PPI", "Producer Inflation", "US 2Y Yield", "DXY", "Gold / NQ",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "通胀超预期",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +0.2 个百分点",
                "transmission": [
                    "生产者通胀超预期 ↑",
                    "上游价格压力 → 通胀粘性预期 ↑ → 降息预期 ↓",
                    "美国 2 年期国债收益率 ↑",
                    "美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "长久期股票估值承压 → 纳斯达克 ↓",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "纳斯达克", "direction": "down", "label": "↓"},
                ],
                "counter_case": "PPI 对上中游传导存在滞后，若核心分项温和或下游 CPI 尚未跟随，市场可能淡化其影响。",
                "invalidation": ["美国 2 年期收益率未上行", "美元指数未走强", "核心 PPI 分项温和"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±0.2 个百分点之间",
                "transmission": [
                    "生产者通胀数据本身未带来足够大的意外。",
                    "价格反应更多取决于对后续 CPI 的预示作用及市场已有的通胀路径判断。",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "纳斯达克", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使整体符合预期，细分行业 PPI 或对 CPI 的传导暗示仍可能主导即时反应。",
                "invalidation": ["美国 2 年期收益率出现 >10bp 的方向性波动", "美元指数突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "通胀低于预期",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -0.2 个百分点",
                "transmission": [
                    "生产者通胀低于预期 ↓",
                    "上游压力缓解 → 通胀回落预期 ↑ → 降息预期 ↑",
                    "美国 2 年期国债收益率 ↓",
                    "美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "折现率 ↓ → 利好纳斯达克 ↑",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "纳斯达克", "direction": "up", "label": "↑"},
                ],
                "counter_case": "若 PPI 回落主要由能源分项驱动而被视为一次性扰动，市场可能对整体数据反应平淡。",
                "invalidation": ["美国 2 年期收益率未下行", "美元指数未走弱"],
            },
        ],
    },
    "ISM_MANUFACTURING": {
        "label": "ISM 制造业 PMI",
        "country": "US",
        "metric": "ISM 制造业 PMI",
        "unit": "点",
        "sourceId": "bloomberg-econ",
        "threshold": {"positive": 2.0, "negative": -2.0},
        "transmission_map": [
            "ISM Manufacturing", "Activity vs Expectations", "US 10Y Yield", "DXY", "Gold / US500",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "景气超预期",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +2.0（PMI 明显高于预期）",
                "transmission": [
                    "制造业景气超预期 ↑",
                    "经济韧性 → 衰退担忧 ↓ → 降息预期 ↓",
                    "美国 10 年期国债收益率 ↑",
                    "美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "盈利预期上修 vs 利率上移压制估值 → 标普 500 分化",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "标普 500", "direction": "down", "label": "↓"},
                ],
                "counter_case": "PMI 分项（新订单、就业、物价）组合若显示“过热涨价”而非“健康扩张”，风险资产可能同步承压。",
                "invalidation": ["美国 10 年期收益率未上行", "美元指数未走强", "新订单分项走弱"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±2.0 之间",
                "transmission": [
                    "PMI 数据本身未带来足够大的意外。",
                    "价格反应更多取决于荣枯线附近的方向感及新订单 / 就业分项的边际变化。",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "标普 500", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使整体符合预期，分项结构或价格支付分项仍可能主导即时反应。",
                "invalidation": ["美国 10 年期收益率出现 >10bp 的方向性波动", "美元指数突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "景气不及预期",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -2.0（PMI 明显低于预期）",
                "transmission": [
                    "制造业景气不及预期 ↓",
                    "经济走弱 → 衰退担忧 ↑ → 降息预期 ↑",
                    "美国 10 年期国债收益率 ↓",
                    "美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "降息预期支撑估值 vs 盈利预期下修 → 标普 500 分化",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "标普 500", "direction": "down", "label": "↓"},
                ],
                "counter_case": "若走弱被解读为衰退确认，避险模式下美元未必下跌，黄金与股市可能同涨。",
                "invalidation": ["美国 10 年期收益率未下行", "美元指数未走弱"],
            },
        ],
    },
    "UNEMPLOYMENT": {
        "label": "美国失业率",
        "country": "US",
        "metric": "美国失业率",
        "unit": "%",
        "sourceId": "bloomberg-econ",
        "threshold": {"positive": 0.2, "negative": -0.2},
        "invert": True,
        "transmission_map": [
            "US Unemployment", "Labor Tightness", "US 2Y Yield", "DXY", "Gold / US500",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "失业率意外走低",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -0.2 个百分点（失业率意外走低 → 就业超预期紧俏）",
                "transmission": [
                    "失业率意外走低 ↑",
                    "就业市场紧俏 → 薪资与通胀压力 ↑ → 降息预期 ↓",
                    "美国 2 年期国债收益率 ↑",
                    "美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "利率预期上移 → 长久期估值承压 → 标普 500 ↓",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "标普 500", "direction": "down", "label": "↓"},
                ],
                "counter_case": "失业率走低若伴随劳动参与率下降（供给收缩而非需求强劲），通胀与政策含义可能被市场淡化。",
                "invalidation": ["美国 2 年期收益率未上行", "美元指数未走强", "劳动参与率同步走低"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±0.2 个百分点之间",
                "transmission": [
                    "失业率数据本身未带来足够大的意外。",
                    "价格反应更多取决于非农分项与劳动参与率的结构性变化。",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "标普 500", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使整体符合预期，薪资与参与率等结构分项仍可能主导即时反应。",
                "invalidation": ["美国 2 年期收益率出现 >10bp 的方向性波动", "美元指数突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "失业率意外走高",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +0.2 个百分点（失业率意外走高 → 就业超预期疲软）",
                "transmission": [
                    "失业率意外走高 ↓",
                    "就业市场转弱 → 衰退担忧 ↑ → 降息预期 ↑",
                    "美国 2 年期国债收益率 ↓",
                    "美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "降息预期支撑估值 vs 盈利预期下修 → 标普 500 分化",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "标普 500", "direction": "down", "label": "↓"},
                ],
                "counter_case": "若失业率走高被解读为衰退确认，避险模式下美元未必下跌，黄金与股市可能同涨。",
                "invalidation": ["美国 2 年期收益率未下行", "美元指数未走弱"],
            },
        ],
    },
    "JOBLESS_CLAIMS": {
        "label": "初请失业金人数",
        "country": "US",
        "metric": "初请失业金人数",
        "unit": "K",
        "sourceId": "bloomberg-econ",
        "threshold": {"positive": 20, "negative": -20},
        "invert": True,
        "transmission_map": [
            "Jobless Claims", "Labor Resilience", "US 2Y Yield", "DXY", "Gold / US500",
        ],
        "scenarios": [
            {
                "key": "HOT",
                "name": "初请意外减少",
                "tag": "鹰派意外",
                "trigger_rule": "实际值 vs 预期 ≤ -20（初请意外减少 → 就业超预期韧性）",
                "transmission": [
                    "初请失业金意外减少 ↑",
                    "就业韧性 → 裁员压力小 → 降息预期 ↓",
                    "美国 2 年期国债收益率 ↑",
                    "美元 ↑ → 欧元兑美元 ↓ / 黄金 ↓",
                    "利率预期上移 → 长久期估值承压 → 标普 500 ↓",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "down", "label": "↓"},
                    {"asset": "美元指数", "direction": "up", "label": "↑"},
                    {"asset": "欧元兑美元", "direction": "down", "label": "↓"},
                    {"asset": "标普 500", "direction": "down", "label": "↓"},
                ],
                "counter_case": "单周初请波动较大且常受季节性调整干扰，若与四周均值趋势相悖，市场可能选择淡化。",
                "invalidation": ["美国 2 年期收益率未上行", "美元指数未走强", "四周均值趋势相反"],
            },
            {
                "key": "INLINE",
                "name": "符合预期",
                "tag": "信号中性 / 政策意外有限",
                "trigger_rule": "实际值 vs 预期落在 ±20 之间",
                "transmission": [
                    "初请数据本身未带来足够大的意外。",
                    "价格反应更多取决于四周均值与续请失业金人数的趋势方向。",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "flat", "label": "震荡"},
                    {"asset": "美元指数", "direction": "flat", "label": "震荡"},
                    {"asset": "欧元兑美元", "direction": "flat", "label": "震荡"},
                    {"asset": "标普 500", "direction": "flat", "label": "震荡"},
                ],
                "counter_case": "即使整体符合预期，续请人数或四周均值趋势仍可能主导即时反应。",
                "invalidation": ["美国 2 年期收益率出现 >10bp 的方向性波动", "美元指数突破近期区间"],
            },
            {
                "key": "COOL",
                "name": "初请意外增加",
                "tag": "鸽派意外",
                "trigger_rule": "实际值 vs 预期 ≥ +20（初请意外增加 → 就业超预期疲软）",
                "transmission": [
                    "初请失业金意外增加 ↓",
                    "就业转弱 → 衰退担忧 ↑ → 降息预期 ↑",
                    "美国 2 年期国债收益率 ↓",
                    "美元 ↓ → 欧元兑美元 ↑ / 黄金 ↑",
                    "降息预期支撑估值 vs 盈利预期下修 → 标普 500 分化",
                ],
                "asset_impacts": [
                    {"asset": "黄金", "direction": "up", "label": "↑"},
                    {"asset": "美元指数", "direction": "down", "label": "↓"},
                    {"asset": "欧元兑美元", "direction": "up", "label": "↑"},
                    {"asset": "标普 500", "direction": "down", "label": "↓"},
                ],
                "counter_case": "单周跳升若被归因为季节性或一次性事件（如假期、天气），市场可能反应平淡。",
                "invalidation": ["美国 2 年期收益率未下行", "美元指数未走弱", "四周均值趋势相反"],
            },
        ],
    },
}


def _norm_event_type(raw):
    """归一化事件类型键：去首尾空格 + 转大写 + 空格转下划线。
    前端下拉 "Retail Sales" 与模板键 "RETAIL_SALES" 因此可互相匹配。"""
    s = (raw or "").strip().upper()
    return s.replace(" ", "_")


def _type_threshold(event_type, cfg=None):
    """返回 (positive, negative) 匹配阈值：优先事件类型模板的 threshold（适配各指标量级），
    缺省回退全局事件配置的 strongPositive / strongNegative。"""
    cfg = cfg or _load_event_config()
    tpl = EVENT_TYPE_DEFS.get(_norm_event_type(event_type)) if event_type else None
    if tpl and tpl.get("threshold"):
        th = tpl["threshold"]
        sp = float(th.get("positive", cfg.get("strongPositive", 0.2)))
        sn = float(th.get("negative", cfg.get("strongNegative", -0.2)))
    else:
        sp = float(cfg.get("strongPositive", 0.2))
        sn = float(cfg.get("strongNegative", -0.2))
    return sp, sn


def _match_scenario(surprise, cfg=None, event_type=None):
    """根据 surprise 确定性匹配情景 key：HOT / INLINE / COOL；无法计算返回 None。
    阈值优先取事件类型模板的 threshold，缺省回退全局事件配置。
    invert 型指标（失业率、初请失业金等）数值越低越鹰派：实际 ≤ 预期 → HOT，实际 ≥ 预期 → COOL。"""
    try:
        s = float(surprise)
    except (TypeError, ValueError):
        return None
    sp, sn = _type_threshold(event_type, cfg)
    tpl = EVENT_TYPE_DEFS.get(_norm_event_type(event_type)) if event_type else None
    if tpl and tpl.get("invert"):
        if s <= sn:
            return "HOT"
        if s >= sp:
            return "COOL"
        return "INLINE"
    if s >= sp:
        return "HOT"
    if s <= sn:
        return "COOL"
    return "INLINE"


# 指标 / 数据源显示名中文化：存储层保留原始代码，展示层翻译，保证 API 键稳定、界面友好。
METRIC_LABELS = {
    "Headline CPI YoY": "整体 CPI 同比",
    "Nonfarm Payrolls": "非农就业人数",
    "Fed Funds Target Rate": "联邦基金目标利率",
    "Retail Sales MoM": "零售销售环比",
}
SOURCE_LABELS = {
    "bloomberg-econ": "彭博经济",
    "federalreserve": "美联储",
}


def _sync_scenario_display(scenarios, event_id, tpl):
    """把模板中的中文展示字段同步到已存在的情景（保留运行态字段）。

    情景内容是确定性的模板内容，数据公布后只冻结、不重写故事；
    因此这里只做展示字段对齐，用于已存储数据的一次性中文化迁移。
    返回是否有改动。
    """
    tpl_map = {s["key"]: s for s in tpl.get("scenarios", [])}
    changed = False
    for sc in scenarios:
        if sc.get("event_id") != event_id:
            continue
        t = tpl_map.get(sc.get("scenario_key"))
        if not t:
            continue
        display = {
            "scenario_name": t["name"],
            "tag": t["tag"],
            "trigger_rule": t["trigger_rule"],
            "transmission": list(t.get("transmission", [])),
            "asset_impacts": list(t.get("asset_impacts", [])),
            "counter_case": t.get("counter_case", ""),
            "invalidation": list(t.get("invalidation", [])),
        }
        for k, v in display.items():
            if sc.get(k) != v:
                sc[k] = v
                changed = True
    return changed


def _generate_event_scenarios(ev):
    """根据事件类型模板为事件生成 3 个情景（幂等：已存在则跳过并同步展示字段）。"""
    tpl = EVENT_TYPE_DEFS.get(_norm_event_type(ev.get("event_type")))
    if not tpl:
        return []
    scenarios = _load_scenarios()
    existing = [s for s in scenarios if s.get("event_id") == ev.get("id")]
    if existing:
        if _sync_scenario_display(scenarios, ev.get("id"), tpl):
            _save_scenarios(scenarios)
        return existing
    created = []
    for sc_tpl in tpl["scenarios"]:
        sc = {
            "id": _new_id(),
            "event_id": ev["id"],
            "scenario_key": sc_tpl["key"],
            "scenario_name": sc_tpl["name"],
            "tag": sc_tpl["tag"],
            "trigger_rule": sc_tpl["trigger_rule"],
            "transmission": list(sc_tpl.get("transmission", [])),
            "asset_impacts": list(sc_tpl.get("asset_impacts", [])),
            "counter_case": sc_tpl.get("counter_case", ""),
            "invalidation": list(sc_tpl.get("invalidation", [])),
            "triggered": False,
            "frozen_at": None,
            "created_at": _now_ms(),
        }
        scenarios.append(sc)
        created.append(sc)
    _save_scenarios(scenarios)
    return created


def _scenario_summary(event_id):
    """返回某事件的 3 情景摘要（用于 before_release 冻结）。"""
    return [{"key": s.get("scenario_key"), "name": s.get("scenario_name"),
             "tag": s.get("tag"), "trigger_rule": s.get("trigger_rule")}
            for s in _load_scenarios() if s.get("event_id") == event_id]


def _freeze_scenarios(ev, matched_key=None):
    """数据公布后冻结全部情景；被匹配的情景打上 triggered 标记。"""
    scenarios = _load_scenarios()
    frozen = _now_ms()
    changed = False
    for sc in scenarios:
        if sc.get("event_id") != ev.get("id"):
            continue
        if not sc.get("frozen_at"):
            sc["frozen_at"] = frozen
        sc["triggered"] = bool(sc.get("scenario_key") == matched_key)
        changed = True
    if changed:
        _save_scenarios(scenarios)


# ---- 模块 2B：Historical Event Study（确定性统计，非 AI）----
# 数据源为 cme_history.py 参考数据集（sourceId="reference-dataset"，用于纵向切片演示与验收）。
# 分钟级收益（5m/30m/1h）数据源明确不可用：一律返回 "30m data unavailable"，绝不伪造。
STUDY_INSTRUMENTS = ("GC", "DX", "6E", "NQ")
STUDY_HORIZONS = (
    ("30m", "return_30m"),
    ("2h", "return_2h"),
    ("1d", "return_1d"),
    ("3d", "return_3d"),
    ("5d", "return_5d"),
)
STUDY_MINUTE_FIELDS = {"return_5m", "return_30m", "return_1h"}


def _ev_evidence_level(n):
    """证据质量分级：n<5 VERY LOW；5-9 LOW；10-19 MEDIUM；>=20 HIGHER。"""
    if n < 5:
        return "VERY LOW"
    if n < 10:
        return "LOW"
    if n < 20:
        return "MEDIUM"
    return "HIGHER"


def _ev_median(values):
    if not values:
        return None
    s = sorted(values)
    m = len(s)
    if m % 2 == 1:
        return s[m // 2]
    return (s[m // 2 - 1] + s[m // 2]) / 2.0


def _ev_quantile(values, q):
    """线性插值分位数；数据不足时返回 None。"""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return None
    pos = (n - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _ev_stats(values):
    """对一组历史收益（%）计算描述统计；空样本返回 None。"""
    n = len(values)
    if n == 0:
        return None
    mean = sum(values) / n
    med = _ev_median(values)
    positive = sum(1 for v in values if v > 0)
    negative = n - positive
    hit_rate = round(positive / n * 100, 1)
    return {
        "n": n,
        "mean": round(mean, 4),
        "median": round(med, 4),
        "positive": positive,
        "negative": negative,
        "hit_rate": hit_rate,
        "q25": round(_ev_quantile(values, 0.25), 4),
        "q75": round(_ev_quantile(values, 0.75), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "evidence": _ev_evidence_level(n),
    }


def _ev_tendency(day_stats):
    """依据 1d 中位数给出历史倾向标签（描述历史样本，非概率预测）。"""
    if not day_stats or day_stats.get("median") is None:
        return "Insufficient data"
    m = day_stats["median"]
    if m >= 0.5:
        return "Bullish"
    if m >= 0.15:
        return "Moderately Bullish"
    if m > -0.15:
        return "Mixed / Neutral"
    if m > -0.5:
        return "Moderately Bearish"
    return "Bearish"


def _study_filter_for_scenario(scenario_key, cfg=None, event_type=None):
    """根据匹配情景返回历史检索过滤条件（阈值与应用层匹配一致，按事件类型适配量级）。
    invert 型指标（失业率、初请失业金等）数值越低越鹰派，检索方向与应用层匹配保持一致。"""
    cfg = cfg or _load_event_config()
    sp, sn = _type_threshold(event_type, cfg)
    tpl = EVENT_TYPE_DEFS.get(_norm_event_type(event_type)) if event_type else None
    invert = bool(tpl and tpl.get("invert"))

    def _fmt(v):
        return "%g" % v

    if scenario_key == "HOT":
        if invert:
            return {"operator": "<=", "threshold": sn, "sp": sp, "sn": sn,
                    "label": "意外 ≤ -%s（数值越低越强劲）" % _fmt(abs(sn))}
        return {"operator": ">=", "threshold": sp, "sp": sp, "sn": sn,
                "label": "意外 ≥ +%s" % _fmt(sp)}
    if scenario_key == "COOL":
        if invert:
            return {"operator": ">=", "threshold": sp, "sp": sp, "sn": sn,
                    "label": "意外 ≥ +%s（数值越高越疲弱）" % _fmt(sp)}
        return {"operator": "<=", "threshold": sn, "sp": sp, "sn": sn,
                "label": "意外 ≤ -%s" % _fmt(abs(sn))}
    return {"operator": "between", "threshold": None, "sp": sp, "sn": sn,
            "label": "-%s < 意外 < +%s" % (_fmt(abs(sn)), _fmt(sp))}


def _select_history_events(event_type, scenario_key, cfg=None):
    """从参考数据集筛选符合条件的历史事件；返回 (事件列表, 过滤条件)。"""
    cfg = cfg or _load_event_config()
    f = _study_filter_for_scenario(scenario_key, cfg, event_type)
    selected = []
    for ev in CME_HISTORY.MACRO_EVENT_HISTORY:
        if ev.get("event_type") != event_type:
            continue
        try:
            s = float(ev.get("surprise"))
        except (TypeError, ValueError):
            continue
        if f["operator"] == ">=":
            if s >= f["sp"]:
                selected.append(ev)
        elif f["operator"] == "<=":
            if s <= f["sn"]:
                selected.append(ev)
        else:
            if f["sn"] < s < f["sp"]:
                selected.append(ev)
    return selected, f


def _compute_event_study(event_id):
    """模块 2B 核心：确定性计算历史事件研究统计 + Historical Path vs Today。"""
    events = _load_events()
    ev = next((e for e in events if e.get("id") == event_id), None)
    if ev is None:
        return {"error": "事件不存在"}
    event_type = (ev.get("event_type") or "").upper()
    scenario_key = ev.get("matched_scenario") or _match_scenario(ev.get("surprise"), event_type=event_type)
    if not event_type or not scenario_key:
        return {"error": "无法确定匹配情景，无法检索历史对照"}
    selected, filters = _select_history_events(event_type, scenario_key)
    selected_ids = {e["event_id"] for e in selected}
    returns_map = {(r["event_id"], r.get("instrument")): r for r in CME_HISTORY.EVENT_ASSET_RETURN
                   if r.get("event_id") in selected_ids}
    instruments = {}
    for inst in STUDY_INSTRUMENTS:
        horizons = {}
        inst_name = CME_CONTRACT_SPECS[inst]["name"]
        for label, field in STUDY_HORIZONS:
            if field in STUDY_MINUTE_FIELDS:
                horizons[label] = {"unavailable": True, "reason": "30m data unavailable"}
                continue
            values = []
            for eid in selected_ids:
                rec = returns_map.get((eid, inst_name))
                v = rec.get(field) if rec else None
                if v is not None:
                    try:
                        values.append(float(v))
                    except (TypeError, ValueError):
                        pass
            stats = _ev_stats(values)
            horizons[label] = stats if stats else {"n": 0, "unavailable": True}
        day_stats = horizons.get("1d")
        instruments[inst] = {
            "horizons": horizons,
            "tendency": _ev_tendency(day_stats),
            "evidence": _ev_evidence_level((day_stats or {}).get("n", 0)),
        }
    # Historical Path vs Today：今日已实现变动来自事件上的 realized_moves（人工记录或快照），缺失则为 None。
    realized = ev.get("realized_moves") or {}
    path_vs_today = {}
    for inst in STUDY_INSTRUMENTS:
        rows = []
        for label, _field in STUDY_HORIZONS:
            h = instruments[inst]["horizons"].get(label) or {}
            hist_med = h.get("median") if h.get("median") is not None and not h.get("unavailable") else None
            today_val = None
            rv = realized.get(inst) or {}
            if label in rv and rv[label] is not None:
                try:
                    today_val = round(float(rv[label]), 4)
                except (TypeError, ValueError):
                    today_val = None
            rows.append({
                "horizon": label,
                "historical_median": hist_med,
                "today": today_val,
                "unavailable": bool(h.get("unavailable")),
            })
        path_vs_today[inst] = rows
    return {
        "event_id": event_id,
        "event_type": event_type,
        "matched_scenario": scenario_key,
        "filters": filters,
        "sample_ids": sorted(selected_ids),
        "instruments": instruments,
        "path_vs_today": path_vs_today,
    }


# ---- 模块 C：Trade Planner ----
def _load_proposals():
    return _cme_load("proposals", [])


def _save_proposals(proposals):
    _cme_save("proposals", proposals)


# ---- V2：Trade Proposal 状态机 + Scenario Payoff（确定性引擎，非 AI）----
# 状态机：DRAFT → REVIEW → APPROVED → EXECUTED → CLOSED → REVIEWED
# 终态：REJECTED / INVALIDATED / CANCELLED；只有人工能推进状态，系统绝不自动下单。
TRADE_PROPOSAL_FLOW = ("DRAFT", "REVIEW", "APPROVED", "EXECUTED", "CLOSED", "REVIEWED")
TRADE_PROPOSAL_TERMINAL = ("REJECTED", "INVALIDATED", "CANCELLED")

# CME 合约规格：用于 Scenario Payoff 的确定性 P&L 计算（AI 不能触碰）。
CME_CONTRACT_SPECS = {
    "GC": {"name": "Gold",    "tick_size": 0.1,     "tick_value": 10.0,   "reference_price": 2900.0,  "margin_per_contract": 9000.0},
    "DX": {"name": "DXY",     "tick_size": 0.005,   "tick_value": 5.0,    "reference_price": 103.0,   "margin_per_contract": 2200.0},
    "6E": {"name": "EUR/USD", "tick_size": 0.00005, "tick_value": 6.25,   "reference_price": 1.08,    "margin_per_contract": 2750.0},
    "NQ": {"name": "Nasdaq",  "tick_size": 0.25,    "tick_value": 5.0,    "reference_price": 20500.0, "margin_per_contract": 19800.0},
}
CME_CONTRACT_SPECS_BY_NAME = {v["name"].upper(): k for k, v in CME_CONTRACT_SPECS.items()}
CME_COMMISSION_PER_SIDE = 2.50

# V2.1 Contract Context：近月/远月合约月份（演示用静态映射；正式赛按 CME 官网核对）。
# code 规则：G=2月 J=4月 M=6月 Z=12月，末两位为年份。
CME_CONTRACT_MONTHS = {
    "GC": [
        {"month": "Dec 2026", "code": "GCZ26", "active": True,  "expiry": "2026-11-27"},
        {"month": "Feb 2027", "code": "GCG27", "active": False, "expiry": "2027-01-27"},
        {"month": "Apr 2027", "code": "GCJ27", "active": False, "expiry": "2027-03-29"},
    ],
    "NQ": [
        {"month": "Dec 2026", "code": "NQZ26", "active": True,  "expiry": "2026-12-18"},
        {"month": "Mar 2027", "code": "NQH27", "active": False, "expiry": "2027-03-19"},
        {"month": "Jun 2027", "code": "NQM27", "active": False, "expiry": "2027-06-18"},
    ],
    "6E": [
        {"month": "Dec 2026", "code": "6EZ26", "active": True,  "expiry": "2026-12-14"},
        {"month": "Mar 2027", "code": "6EH27", "active": False, "expiry": "2027-03-15"},
        {"month": "Jun 2027", "code": "6EM27", "active": False, "expiry": "2027-06-14"},
    ],
    "DX": [
        {"month": "Dec 2026", "code": "DXZ26", "active": True,  "expiry": "2026-12-14"},
        {"month": "Mar 2027", "code": "DXH27", "active": False, "expiry": "2027-03-15"},
        {"month": "Jun 2027", "code": "DXM27", "active": False, "expiry": "2027-06-14"},
    ],
}
CME_CONTRACT_TYPE_LABELS = {
    "GC": "Gold Futures · COMEX · 100 troy oz",
    "NQ": "Nasdaq-100 Futures · CME · index × $20",
    "6E": "Euro FX Futures · CME · €125,000",
    "DX": "US Dollar Index Futures · ICE · $1,000 × index",
}

# ---- V2.1 §18：Position Sizing Engine（确定性引擎；AI 只能解释，不能发明数字）----
# 证据质量乘数：把风险上限按历史样本的可靠程度下调（§18：MEDIUM → 6 手降为 4 手）。
EVIDENCE_MULTIPLIERS = {
    "HIGHER": 1.00,
    "MEDIUM": 0.75,
    "LOW": 0.50,
    "VERY LOW": 0.25,
}
# 市场确认乘数（§6.7）：市场是否在确认该宏观逻辑；NO TRADE 表示不应开仓。
CONFIRMATION_MULTIPLIERS = {
    "CONFIRMED": 1.00,
    "PARTIALLY CONFIRMED": 0.75,
    "MIXED": 0.50,
    "DIVERGING": 0.25,
    "NO TRADE": 0.00,
}
# 宏观主题重叠乘数：新方向与现有持仓共享同一宏观逻辑时进一步下调（§18：4 手降为 3 手）。
CONCENTRATION_OVERLAP_MULTIPLIER = 0.75

# 宏观主题标签：用于确定性识别“新提案 vs 现有持仓”是否押注同一宏观逻辑。
# 注意：只描述方向性主题归属，不构成任何概率或预测。
CME_MACRO_THEMES = {
    "GC": {"long": ("US rates lower", "USD weaker"),
           "short": ("US rates higher", "USD stronger")},
    "NQ": {"long": ("US rates lower", "Risk appetite"),
           "short": ("US rates higher", "Risk aversion")},
    "DX": {"long": ("USD stronger", "US rates higher"),
           "short": ("USD weaker", "US rates lower")},
    "6E": {"long": ("USD weaker", "US rates lower"),
           "short": ("USD stronger", "US rates higher")},
}


def _resolve_symbol(raw):
    """接受 ticker（GC/DX/6E/NQ）或显示名（Gold/DXY/EUR/USD/Nasdaq），返回规范 ticker。"""
    s = (raw or "").strip()
    if not s:
        return None
    s_up = s.upper()
    if s_up in CME_CONTRACT_SPECS:
        return s_up
    return CME_CONTRACT_SPECS_BY_NAME.get(s_up)


def _proposal_transitions(current):
    """返回从当前状态允许迁移到的状态集合（状态机校验）。"""
    return {
        "DRAFT": ("REVIEW", "CANCELLED"),
        "REVIEW": ("APPROVED", "REJECTED", "CANCELLED"),
        "APPROVED": ("EXECUTED", "INVALIDATED", "CANCELLED"),
        "EXECUTED": ("CLOSED", "INVALIDATED"),
        "CLOSED": ("REVIEWED",),
        "REJECTED": (),
        "INVALIDATED": (),
        "CANCELLED": (),
    }.get(current, ())


def _proposal_payoff(event_id, symbol, direction, qty):
    """确定性计算 Scenario Payoff：从历史研究的 1d q25/median/q75 出发，
    用 CME 合约规格换算 P&L：price_move ÷ tick_size × tick_value × qty − 佣金。"""
    spec = CME_CONTRACT_SPECS.get(symbol)
    if not spec:
        return None
    study = _compute_event_study(event_id)
    if "error" in study:
        return None
    inst = (study.get("instruments") or {}).get(symbol) or {}
    day = (inst.get("horizons") or {}).get("1d") or {}
    q25, med, q75 = day.get("q25"), day.get("median"), day.get("q75")
    if q25 is None or med is None or q75 is None:
        return None
    try:
        qty = max(1, int(qty or 1))
    except (TypeError, ValueError):
        qty = 1
    base = float(spec["reference_price"])
    tick_size = float(spec["tick_size"])
    tick_value = float(spec["tick_value"])
    commission_total = CME_COMMISSION_PER_SIDE * 2 * qty
    sign = -1 if direction == "short" else 1

    def net_pnl(move_pct):
        gross = move_pct / 100.0 * base / tick_size * tick_value * qty
        return round(gross * sign - commission_total, 2)

    return {
        "symbol": symbol,
        "code": symbol,
        "name": spec.get("name", symbol),
        "qty": qty,
        "direction": direction,
        "tick_size": tick_size,
        "tick_value": tick_value,
        "reference_price": base,
        "commission_per_side": CME_COMMISSION_PER_SIDE,
        "commission_total": round(commission_total, 2),
        "bear": {"move_pct": q25, "pnl": net_pnl(q25)},
        "base": {"move_pct": med, "pnl": net_pnl(med)},
        "bull": {"move_pct": q75, "pnl": net_pnl(q75)},
    }


def _proposal_default_fields(ev, study, symbol, direction, qty):
    """基于已冻结的事件研究生成确定性默认内容（thesis / 五问 / invalidation / origin）。"""
    inst = (study.get("instruments") or {}).get(symbol) or {}
    day = (inst.get("horizons") or {}).get("1d") or {}
    med = day.get("median")
    hit = day.get("hit_rate")
    n = day.get("n") or 0
    evidence = day.get("evidence") or "N/A"
    scenario_key = ev.get("matched_scenario") or _match_scenario(ev.get("surprise"), event_type=ev.get("event_type"))
    scenario_label = scenario_key or "—"
    surprise = ev.get("surprise")
    actual = ev.get("actual")
    consensus = ev.get("consensus")
    previous = ev.get("previous")
    # 从事件类型模板取匹配情景的 invalidation 作为基准
    tpl = EVENT_TYPE_DEFS.get(_norm_event_type(ev.get("event_type")))
    invalidation_base = []
    if tpl:
        for sc in tpl.get("scenarios", []):
            if sc.get("key") == scenario_key:
                invalidation_base = list(sc.get("invalidation") or [])
                break
    inv_str = "; ".join(invalidation_base) if invalidation_base else "Price action diverges from the matched scenario path."
    thesis = (
        "US CPI actual {a}% vs consensus {c}% (surprise {s}pp) matched {scenario}. "
        "Historical {sym} 1D path after {n} comparable events: median {med}%, hit rate {hit}% ({ev} evidence). "
        "Proposed {dir} {q} contract(s) toward the historical median path."
    ).format(a=actual, c=consensus, s=surprise, scenario=scenario_label, sym=symbol,
             n=n, med=med if med is not None else "n/a", hit=hit if hit is not None else "n/a",
             ev=evidence, dir=direction, q=qty)
    return {
        "origin": {
            "event_id": ev.get("id"),
            "event_type": ev.get("event_type"),
            "scenario": scenario_label,
            "surprise": surprise,
        },
        "thesis": thesis,
        "five_questions": {
            "why": ("After {n} comparable {scenario} events, {sym} 1D median {med}% "
                    "with {hit}% hit rate ({ev} evidence).").format(
                        n=n, scenario=scenario_label, sym=symbol, med=med, hit=hit, ev=evidence),
            "why_now": ("Event released at {t}; entering the immediate post-release window "
                        "before the move is fully priced.").format(t=ev.get("scheduled_at") or "—"),
            "proves_wrong": ("{inv}").format(inv=inv_str),
            "max_loss": ("Stop out if loss exceeds the 1D Q25 range for {q} contract(s) "
                         "plus commissions.").format(q=qty),
            "reassess_at": ("Reassess at the 1D horizon mark; time-stop if not working."),
        },
        "invalidation": {
            "price_stop": ("Close if {sym} price moves against entry beyond the 1D Q25/Q75 "
                           "range.").format(sym=symbol),
            "macro_invalidation": inv_str,
            "time_stop": "No overnight hold beyond the 1D reassessment window.",
        },
        "event_data": {
            "actual": actual, "consensus": consensus, "previous": previous,
            "surprise": surprise, "scenario": scenario_label,
            "hist_1d_median": med, "hist_1d_hit_rate": hit, "hist_1d_n": n,
        },
    }


# ---- 模块 D：Risk Engine ----
def _load_positions():
    return _cme_load("positions", [])


def _save_positions(positions):
    _cme_save("positions", positions)


def _load_journal():
    return _cme_load("journal", [])


def _save_journal(journal):
    _cme_save("journal", journal)


def _load_risk_config():
    default = {
        "account_equity": 1000000.0,     # 初始权益（CME 2026 模拟账户 $1,000,000）
        "max_contracts_per_day": 10,     # 每日最低/上限成交 10 张合约（比赛规则）
        "max_concentration_pct": 40.0,   # 单品种集中度红线（%）
        "max_daily_loss_pct": 20.0,      # 单日亏损锁定红线（CME 官方 20%）
        "margin_pct": 10.0,              # 估算保证金比例（%）
        "competition_open": True,        # 赛程是否进行中（可人工开关）
        "final_day_liquidation": False,  # 是否为最后一日清仓窗口
        "contract_near_expiry": False,   # 合约是否临近到期
        "competition_timezone": "America/Chicago",  # CME 交易日时区
        "trading_date": None,            # 人工指定当前比赛交易日（None 时按时区推导）
        "risk_budget_pct": 0.30,         # 单笔交易风险预算（占权益 %，V2.1 §18）
        "default_stop_pct": 0.50,        # 无历史止损参考时的默认止损距离（%）
        "slippage_ticks": 0.0,           # 滑点缓冲（tick 数，计入每手风险）
        "sizing_multipliers": {},        # 仓位乘数覆盖（§6.2「不要硬编码」）
    }
    merged = dict(default)
    merged.update(_cme_load("risk_config", {}) or {})
    return merged


def _save_risk_config(cfg):
    _cme_save("risk_config", cfg)


# ============================================================
# API：/api/cme/overview —— War Room 全局快照
# ============================================================
@app.route("/api/cme/overview", methods=["GET"])
def api_cme_overview():
    return jsonify({
        "competition": _competition_info(),
        "signals_count": len(_load_signals()),
        "events_count": len(_load_events()),
        "proposals": _load_proposals(),
        "positions": _load_positions(),
        "risk": _compute_risk(),
    })


# ============================================================
# API：模块 A —— Macro Score / Signals
# ============================================================
@app.route("/api/cme/factors", methods=["GET"])
def api_cme_factors():
    """返回打分因子模板（供前端渲染打分表单）。"""
    return jsonify({"factors": MACRO_SCORE_FACTORS})


@app.route("/api/cme/signals", methods=["GET"])
def api_cme_get_signals():
    """获取全部 signal（按 timestamp 降序）。"""
    signals = _load_signals()
    signals.sort(key=lambda s: s.get("timestamp", 0), reverse=True)
    return jsonify(signals)


@app.route("/api/cme/signals", methods=["POST"])
def api_cme_add_signal():
    """根据因子状态生成并保存一条 signal（模块 A 输出）。"""
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip()
    price = data.get("price")
    if not symbol or price is None:
        return jsonify({"error": "symbol 和 price 不能为空"}), 400
    factors = data.get("factors") or []
    drivers = data.get("drivers") or []
    invalidation = data.get("invalidation") or []
    range_pct = data.get("range_pct") or 1.0
    signal = _build_signal(symbol, price, factors, drivers, invalidation, range_pct)
    signals = _load_signals()
    signals.append(signal)
    _save_signals(signals)
    return jsonify({"success": True, "signal": signal})


@app.route("/api/cme/signals", methods=["DELETE"])
def api_cme_delete_signal():
    data = request.get_json(silent=True) or {}
    target = data.get("timestamp")
    if target is None:
        return jsonify({"error": "缺少 timestamp"}), 400
    signals = _load_signals()
    signals = [s for s in signals if int(s.get("timestamp", 0)) != int(target)]
    _save_signals(signals)
    return jsonify({"success": True})


# ============================================================
# API：模块 B —— Event Scenario
# ============================================================
@app.route("/api/cme/events", methods=["GET"])
def api_cme_get_events():
    events = _load_events()
    for ev in events:
        # 幂等：已有情景则同步中文展示字段（一次性迁移），无则自动生成三情景
        ev_scenarios = _generate_event_scenarios(ev)
        ev["scenarios"] = ev_scenarios
        tpl = EVENT_TYPE_DEFS.get(_norm_event_type(ev.get("event_type")))
        if not ev.get("status"):
            ev["status"] = "SCHEDULED"
        if tpl and not ev.get("metric"):
            ev["metric"] = tpl["metric"]
        if tpl and not ev.get("unit"):
            ev["unit"] = tpl["unit"]
        if tpl and not ev.get("sourceId"):
            ev["sourceId"] = tpl["sourceId"]
        if ev.get("metric") in METRIC_LABELS:
            ev["metric"] = METRIC_LABELS[ev["metric"]]
        if ev.get("sourceId") in SOURCE_LABELS:
            ev["sourceId"] = SOURCE_LABELS[ev["sourceId"]]
    events.sort(key=lambda e: e.get("scheduled_at", ""), reverse=True)
    return jsonify(events)


@app.route("/api/cme/events", methods=["POST"])
def api_cme_add_event():
    data = request.get_json(silent=True) or {}
    event_type = (data.get("event_type") or "").strip()
    scheduled_at = (data.get("scheduled_at") or "").strip()
    if not event_type or not scheduled_at:
        return jsonify({"error": "event_type 和 scheduled_at 不能为空"}), 400
    tpl = EVENT_TYPE_DEFS.get(_norm_event_type(event_type))
    ev = {
        "id": _new_id(),
        "event_type": event_type,
        "status": "SCHEDULED",                       # V2 状态机起点
        "country": (data.get("country") or (tpl or {}).get("country") or "").strip(),
        "metric": (data.get("metric") or (tpl or {}).get("metric") or "").strip(),
        "unit": (data.get("unit") or (tpl or {}).get("unit") or "%").strip(),
        "sourceId": (data.get("sourceId") or (tpl or {}).get("sourceId") or "").strip(),
        "scheduled_at": scheduled_at,
        "consensus": data.get("consensus"),
        "previous": data.get("previous"),
        "actual": data.get("actual"),
        "surprise": data.get("surprise"),
        "importance": data.get("importance") or "medium",
        "source_url": (data.get("source_url") or "").strip(),
        "note": (data.get("note") or "").strip(),
        "screenshots": [],
        "created_at": _now_ms(),
    }
    events = _load_events()
    events.append(ev)
    _save_events(events)
    generated = _generate_event_scenarios(ev)
    ev["scenarios"] = generated
    return jsonify({"success": True, "event": ev})


@app.route("/api/cme/events/<event_id>", methods=["DELETE"])
def api_cme_delete_event(event_id):
    events = _load_events()
    events = [e for e in events if e.get("id") != event_id]
    _save_events(events)
    scenarios = _load_scenarios()
    scenarios = [s for s in scenarios if s.get("event_id") != event_id]
    _save_scenarios(scenarios)
    return jsonify({"success": True})


@app.route("/api/cme/events/<event_id>", methods=["PATCH"])
def api_cme_update_event(event_id):
    """事件落地后更新 actual：
    1) 计算 surprise；2) 确定性匹配情景；3) 冻结全部情景（不重写）；4) 状态推进 RELEASED。"""
    data = request.get_json(silent=True) or {}
    events = _load_events()
    for ev in events:
        if ev.get("id") == event_id:
            if "consensus" in data or "previous" in data:
                if ev.get("status") not in ("SCHEDULED", "PRE_EVENT"):
                    return jsonify({"error": "事件已发布，consensus/previous 不可修改"}), 400
                try:
                    if "consensus" in data and data["consensus"] is not None:
                        ev["consensus"] = float(data["consensus"])
                    if "previous" in data and data["previous"] is not None:
                        ev["previous"] = float(data["previous"])
                except (TypeError, ValueError):
                    return jsonify({"error": "consensus/previous 必须为数字"}), 400
            if "actual" in data and data["actual"] is not None:
                ev["actual"] = data["actual"]
                if ev.get("consensus") is not None:
                    try:
                        ev["surprise"] = round(float(data["actual"]) - float(ev["consensus"]), 4)
                    except (TypeError, ValueError):
                        ev["surprise"] = None
                matched = _match_scenario(ev.get("surprise"), event_type=ev.get("event_type"))
                ev["matched_scenario"] = matched
                ev["status"] = "RELEASED" if ev.get("status") not in ("ARCHIVED",) else ev.get("status")
                _freeze_scenarios(ev, matched)
            if "note" in data:
                ev["note"] = data["note"]
            if "screenshots" in data:
                shots = data["screenshots"]
                if not isinstance(shots, list) or len(shots) > MAX_EVENT_SHOTS:
                    return jsonify({"error": f"截图最多 {MAX_EVENT_SHOTS} 张"}), 400
                cleaned = []
                for s in shots:
                    if not isinstance(s, dict):
                        return jsonify({"error": "截图格式不正确"}), 400
                    name = str(s.get("name") or "").strip()
                    data_url = str(s.get("data_url") or "")
                    if not name or not data_url.startswith("data:image/"):
                        return jsonify({"error": "截图必须为图片格式"}), 400
                    if len(data_url) > MAX_SHOT_DATA_LEN:
                        return jsonify({"error": "单张截图过大，请压缩后重试"}), 400
                    cleaned.append({
                        "name": name,
                        "data_url": data_url,
                        "uploaded_at": s.get("uploaded_at") or _now_ms(),
                    })
                ev["screenshots"] = cleaned
            if "realized_moves" in data and isinstance(data["realized_moves"], dict):
                ev["realized_moves"] = data["realized_moves"]
            if "status" in data and data["status"]:
                allowed = EVENT_STATUS_FLOW
                new_status = str(data["status"]).upper()
                if new_status not in allowed:
                    return jsonify({"error": f"状态必须为 {', '.join(allowed)}"}), 400
                ev["status"] = new_status
            _save_events(events)
            ev["scenarios"] = [s for s in _load_scenarios() if s.get("event_id") == ev.get("id")]
            return jsonify({"success": True, "event": ev})
    return jsonify({"error": "事件不存在"}), 404


# ---- V2：Event Scenario Config（阈值可配置，预留 Z-score）----
@app.route("/api/cme/event-config", methods=["GET"])
def api_cme_get_event_config():
    return jsonify({"config": _load_event_config()})


@app.route("/api/cme/event-config", methods=["POST"])
def api_cme_set_event_config():
    data = request.get_json(silent=True) or {}
    cfg = data.get("config") or {}
    current = _load_event_config()
    try:
        if "strongPositive" in cfg:
            current["strongPositive"] = float(cfg["strongPositive"])
        if "strongNegative" in cfg:
            current["strongNegative"] = float(cfg["strongNegative"])
        if "neutralUpper" in cfg:
            current["neutralUpper"] = float(cfg["neutralUpper"])
        if "neutralLower" in cfg:
            current["neutralLower"] = float(cfg["neutralLower"])
    except (TypeError, ValueError):
        return jsonify({"error": "阈值必须为数字"}), 400
    if "mode" in cfg:
        current["mode"] = str(cfg["mode"])
    if "zscore_std" in cfg:
        current["zscore_std"] = cfg["zscore_std"]
    _save_event_config(current)
    return jsonify({"success": True, "config": current})


@app.route("/api/cme/events/<event_id>/scenarios", methods=["GET"])
def api_cme_get_scenarios(event_id):
    scenarios = [s for s in _load_scenarios() if s.get("event_id") == event_id]
    return jsonify(scenarios)


@app.route("/api/cme/events/<event_id>/scenarios", methods=["POST"])
def api_cme_add_scenario():
    """为事件生成/保存 3 情景（hawkish/upside、base、dovish/downside）。"""
    data = request.get_json(silent=True) or {}
    event_id = data.get("event_id") or ""
    events = _load_events()
    ev = next((e for e in events if e.get("id") == event_id), None)
    if ev is None:
        return jsonify({"error": "事件不存在"}), 404
    scenario_name = (data.get("scenario_name") or "").strip()
    trigger_rule = (data.get("trigger_rule") or "").strip()
    transmission = data.get("transmission") or []
    asset_impacts = data.get("asset_impacts") or []
    historical_stats = data.get("historical_stats") or {}
    if not scenario_name:
        return jsonify({"error": "scenario_name 不能为空"}), 400
    sc = {
        "id": _new_id(),
        "event_id": event_id,
        "scenario_name": scenario_name,
        "trigger_rule": trigger_rule,
        "transmission": transmission,
        "asset_impacts": asset_impacts,
        "historical_stats": historical_stats,
        "created_at": _now_ms(),
    }
    scenarios = _load_scenarios()
    scenarios.append(sc)
    _save_scenarios(scenarios)
    return jsonify({"success": True, "scenario": sc})


@app.route("/api/cme/events/<event_id>/study", methods=["GET"])
def api_cme_event_study(event_id):
    """返回该事件的历史事件研究统计（模块 2B，确定性计算，非 AI）。"""
    study = _compute_event_study(event_id)
    if "error" in study:
        return jsonify(study), 404
    return jsonify({"event_id": event_id, "study": study})


# ============================================================
# API：模块 C —— Trade Planner（V2：状态机 + 五问 + Invalidation + Scenario Payoff）
# ============================================================
@app.route("/api/cme/proposals", methods=["GET"])
def api_cme_get_proposals():
    proposals = _load_proposals()
    proposals.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    return jsonify(proposals)


@app.route("/api/cme/proposals", methods=["POST"])
def api_cme_add_proposal():
    """V2：基于已冻结事件研究创建提案。thesis / 五问 / invalidation / payoff
    全部由结构化数据确定性生成，AI 不能编造；允许人工覆盖文本字段。"""
    data = request.get_json(silent=True) or {}
    event_id = (data.get("event_id") or "").strip()
    symbol = (data.get("symbol") or "").strip()
    direction = (data.get("direction") or "").strip()
    if not event_id or not symbol or not direction:
        return jsonify({"error": "event_id / symbol / direction 不能为空"}), 400
    if direction not in ("long", "short"):
        return jsonify({"error": "direction 必须是 long 或 short"}), 400
    symbol = _resolve_symbol(symbol)
    if not symbol:
        return jsonify({"error": "不支持的合约品种"}), 400
    events = _load_events()
    ev = next((e for e in events if e.get("id") == event_id), None)
    if ev is None:
        return jsonify({"error": "事件不存在"}), 404
    scenario_key = ev.get("matched_scenario") or _match_scenario(ev.get("surprise"), event_type=ev.get("event_type"))
    if ev.get("status") not in ("RELEASED", "POST_EVENT") or not scenario_key:
        return jsonify({"error": "事件尚未发布/匹配情景，无法创建提案"}), 400
    study = _compute_event_study(event_id)
    if "error" in study:
        return jsonify({"error": study["error"]}), 400
    inst = (study.get("instruments") or {}).get(symbol) or {}
    day = (inst.get("horizons") or {}).get("1d") or {}
    if not day.get("n") or day.get("median") is None:
        return jsonify({"error": "该品种缺少 1D 历史研究数据，无法创建提案"}), 400
    try:
        qty = max(1, int(data.get("qty", 1)))
    except (TypeError, ValueError):
        qty = 1
    defaults = _proposal_default_fields(ev, study, symbol, direction, qty)
    five_questions = dict(defaults["five_questions"])
    fq = data.get("five_questions")
    if isinstance(fq, dict):
        for k in five_questions:
            if (fq.get(k) or "").strip():
                five_questions[k] = fq[k].strip()
    invalidation = dict(defaults["invalidation"])
    inv = data.get("invalidation")
    if isinstance(inv, dict):
        for k in invalidation:
            if (inv.get(k) or "").strip():
                invalidation[k] = inv[k].strip()
    proposal = {
        "id": _new_id(),
        "created_at": _now_ms(),
        "updated_at": _now_ms(),
        "status": "DRAFT",
        "event_id": event_id,
        "symbol": symbol,
        "direction": direction,
        "qty": qty,
        "origin": dict(defaults["origin"]),
        "thesis": (data.get("thesis") or "").strip() or defaults["thesis"],
        "five_questions": five_questions,
        "invalidation": invalidation,
        "scenario_payoff": _proposal_payoff(event_id, symbol, direction, qty),
        "event_data": dict(defaults["event_data"]),
        "risk_check": None,
        "post_trade_note": "",
        "review": None,
    }
    proposals = _load_proposals()
    proposals.append(proposal)
    _save_proposals(proposals)
    return jsonify({"success": True, "proposal": proposal}), 201


@app.route("/api/cme/proposals/<proposal_id>", methods=["PATCH"])
def api_cme_update_proposal(proposal_id):
    """V2：仅 DRAFT / REVIEW 状态可编辑文本字段与 qty（qty 变更会重算 payoff）。"""
    data = request.get_json(silent=True) or {}
    proposals = _load_proposals()
    for p in proposals:
        if p.get("id") != proposal_id:
            continue
        if p.get("status") not in ("DRAFT", "REVIEW"):
            return jsonify({"error": "仅 DRAFT / REVIEW 状态下可编辑提案"}), 400
        if "qty" in data:
            try:
                new_qty = max(1, int(data["qty"]))
            except (TypeError, ValueError):
                return jsonify({"error": "qty 必须是正整数"}), 400
            p["qty"] = new_qty
            p["scenario_payoff"] = _proposal_payoff(p.get("event_id"), p.get("symbol"), p.get("direction"), new_qty)
        if (data.get("thesis") or "").strip():
            p["thesis"] = data["thesis"].strip()
        if isinstance(data.get("five_questions"), dict):
            fq = p.setdefault("five_questions", {})
            for k, v in data["five_questions"].items():
                if (v or "").strip():
                    fq[k] = v.strip()
        if isinstance(data.get("invalidation"), dict):
            inv = p.setdefault("invalidation", {})
            for k, v in data["invalidation"].items():
                if (v or "").strip():
                    inv[k] = v.strip()
        p["updated_at"] = _now_ms()
        _save_proposals(proposals)
        return jsonify({"success": True, "proposal": p})
    return jsonify({"error": "proposal 不存在"}), 404


@app.route("/api/cme/proposals/<proposal_id>/status", methods=["PATCH"])
def api_cme_update_proposal_status(proposal_id):
    """V2：严格状态机校验；只有人工能推进状态，系统绝不自动下单。
    APPROVED 前强制五问填全，且 Risk Check 不得为 BLOCK。"""
    data = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "").strip()
    if new_status not in TRADE_PROPOSAL_FLOW + TRADE_PROPOSAL_TERMINAL:
        return jsonify({"error": "非法状态：%s" % new_status}), 400
    proposals = _load_proposals()
    for p in proposals:
        if p.get("id") != proposal_id:
            continue
        current = p.get("status", "DRAFT")
        if new_status == current and "post_trade_note" in data:
            p["post_trade_note"] = (data["post_trade_note"] or "").strip()
            p["updated_at"] = _now_ms()
            _save_proposals(proposals)
            return jsonify({"success": True, "proposal": p})
        if new_status not in _proposal_transitions(current):
            return jsonify({"error": "状态机不允许从 %s 迁移到 %s" % (current, new_status)}), 400
        if new_status == "APPROVED":
            fq = p.get("five_questions") or {}
            missing = [k for k in ("why", "why_now", "proves_wrong", "max_loss", "reassess_at")
                       if not (fq.get(k) or "").strip()]
            if missing:
                return jsonify({"error": "五个问题未填全，不能 APPROVE：%s" % ", ".join(missing)}), 400
            rc = p.get("risk_check") or {}
            if rc.get("result") == "BLOCK":
                return jsonify({"error": "Risk Check 结果为 BLOCK，不能 APPROVE"}), 400
        p["status"] = new_status
        p["updated_at"] = _now_ms()
        if new_status in TRADE_PROPOSAL_FLOW[3:] + TRADE_PROPOSAL_TERMINAL:
            p["status_at"] = _now_ms()
        if "post_trade_note" in data:
            p["post_trade_note"] = data["post_trade_note"]
        _save_proposals(proposals)
        return jsonify({"success": True, "proposal": p})
    return jsonify({"error": "proposal 不存在"}), 404


@app.route("/api/cme/proposals/<proposal_id>/risk-check", methods=["POST"])
def api_cme_proposal_risk_check(proposal_id):
    """SEND TO RISK CHECK：提案 → Risk Engine → PASS / WARN / BLOCK + 逐项检查。"""
    proposals = _load_proposals()
    p = next((x for x in proposals if x.get("id") == proposal_id), None)
    if p is None:
        return jsonify({"error": "proposal 不存在"}), 404
    if p.get("status") not in ("DRAFT", "REVIEW"):
        return jsonify({"error": "仅 DRAFT / REVIEW 状态可发起 Risk Check"}), 400
    checks = _pre_trade_checks(p)
    result = "PASS"
    for c in checks:
        if c["status"] == "BLOCK":
            result = "BLOCK"
            break
        if c["status"] == "WARN" and result == "PASS":
            result = "WARN"
    p["risk_check"] = {"result": result, "checks": checks, "checked_at": _now_ms()}
    p["updated_at"] = _now_ms()
    _save_proposals(proposals)
    return jsonify({"success": True, "risk_check": p["risk_check"]})


@app.route("/api/cme/proposals/<proposal_id>", methods=["DELETE"])
def api_cme_delete_proposal(proposal_id):
    proposals = _load_proposals()
    p = next((x for x in proposals if x.get("id") == proposal_id), None)
    if p is None:
        return jsonify({"error": "proposal 不存在"}), 404
    if p.get("status") not in ("DRAFT", "REVIEW", "REJECTED", "INVALIDATED", "CANCELLED"):
        return jsonify({"error": "EXECUTED / CLOSED 状态的提案不可删除，请用状态机推进"}), 400
    proposals = [x for x in proposals if x.get("id") != proposal_id]
    _save_proposals(proposals)
    return jsonify({"success": True})


# ============================================================
# 模块 D：Risk Engine + 赛制运营
# ============================================================
# 交易日推导：CME 赛制禁止按本地午夜重置，须按 America/Chicago 或人工指定 trading_date。
try:
    from zoneinfo import ZoneInfo
    _CME_ZONE = ZoneInfo("America/Chicago")
except Exception:
    _CME_ZONE = None


def _num(v, nd=2):
    try:
        return format(float(v), ",.{}f".format(nd))
    except (TypeError, ValueError):
        return "n/a"


def _current_trading_date(cfg=None):
    cfg = cfg or _load_risk_config()
    if cfg.get("trading_date"):
        return str(cfg["trading_date"])[:10]
    if _CME_ZONE is not None:
        return datetime.now(_CME_ZONE).strftime("%Y-%m-%d")
    return time.strftime("%Y-%m-%d", time.localtime())


def _daily_pnl_stats(cfg=None):
    """按 Trading Day 统计：当日已实现 PnL、佣金、成交合约数。
    Contracts Today 按实际成交 qty 计数，Entry + Exit 都计入（不足限额按赛制罚 $1,000）。"""
    cfg = cfg or _load_risk_config()
    trading_date = _current_trading_date(cfg)
    realized = 0.0
    fees = 0.0
    contracts = 0
    for j in _load_journal():
        if not (j.get("entry_time") or "").startswith(trading_date):
            continue
        try:
            realized += float(j.get("pnl") or 0)
        except (TypeError, ValueError):
            pass
        try:
            qty = float(j.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            fees += qty * CME_COMMISSION_PER_SIDE * 2
            contracts += int(qty)
    unrealized = 0.0
    for pos in _load_positions():
        try:
            unrealized += float(pos.get("qty") or 0) * (float(pos.get("mark_price") or 0) - float(pos.get("avg_price") or 0))
        except (TypeError, ValueError):
            pass
    daily_pnl = round(realized + unrealized, 2)
    return {
        "trading_date": trading_date,
        "realized_pnl_today": round(realized, 2),
        "fees_today": round(fees, 2),
        "unrealized_pnl": round(unrealized, 2),
        "daily_pnl": daily_pnl,
        "today_contracts": contracts,
    }


def _risk_band(daily_loss_pct):
    """内部风险带（规格书 5.3）：
    0-8 SAFE / 8-12 CAUTION / 12-16 REDUCE RISK / 16-18 HIGH RISK /
    18-20 CRITICAL / >=20 OFFICIAL LOCK RISK。"""
    if daily_loss_pct < 8:
        return "SAFE"
    if daily_loss_pct < 12:
        return "CAUTION"
    if daily_loss_pct < 16:
        return "REDUCE RISK"
    if daily_loss_pct < 18:
        return "HIGH RISK"
    if daily_loss_pct < 20:
        return "CRITICAL"
    return "OFFICIAL LOCK RISK"


def _pre_trade_checks(proposal):
    """SEND TO RISK CHECK —— 下单前的 10 项确定性检查（非 AI）。
    返回 [{name, status: PASS|WARN|BLOCK, message}]；任一 BLOCK → 整体 BLOCK。"""
    cfg = _load_risk_config()
    stats = _daily_pnl_stats(cfg)
    checks = []
    symbol = proposal.get("symbol")
    try:
        qty = max(1, int(proposal.get("qty") or 1))
    except (TypeError, ValueError):
        qty = 1
    spec = CME_CONTRACT_SPECS.get(symbol)
    payoff = proposal.get("scenario_payoff") or {}
    risk = _compute_risk()
    equity = float(cfg.get("account_equity", 1000000.0))
    net_equity = float(risk.get("net_equity") or equity)

    # 1. Competition currently open?
    if cfg.get("competition_open", True):
        checks.append({"name": "Competition Status", "status": "PASS", "message": "Competition window is open."})
    else:
        checks.append({"name": "Competition Status", "status": "BLOCK", "message": "Competition is closed; no new entries allowed."})

    # 2. Final-day liquidation window?
    if cfg.get("final_day_liquidation"):
        checks.append({"name": "Final-Day Liquidation", "status": "BLOCK", "message": "Final-day liquidation window: close only, no new entries."})
    else:
        checks.append({"name": "Final-Day Liquidation", "status": "PASS", "message": "Not in final-day liquidation window."})

    # 3. Contract near expiry?
    if cfg.get("contract_near_expiry"):
        checks.append({"name": "Contract Expiry", "status": "WARN", "message": "Contract near expiry; rollover risk."})
    else:
        checks.append({"name": "Contract Expiry", "status": "PASS", "message": "Contract is not near expiry."})

    # 4. Margin sufficient after proposed trade?
    if spec:
        add_margin = float(spec.get("margin_per_contract", 0)) * qty
        total_margin = float(risk.get("margin_used") or 0) + add_margin
        if total_margin >= net_equity:
            checks.append({"name": "Margin Sufficiency", "status": "BLOCK",
                           "message": "Margin after trade $%s >= net equity $%s." % (_num(total_margin), _num(net_equity))})
        else:
            checks.append({"name": "Margin Sufficiency", "status": "PASS",
                           "message": "Margin after trade $%s within net equity $%s." % (_num(total_margin), _num(net_equity))})
    else:
        checks.append({"name": "Margin Sufficiency", "status": "WARN", "message": "Unknown contract spec; margin not validated."})

    # 5. Estimated worst-case trade loss acceptable?
    bear = payoff.get("bear") or {}
    bear_pnl = bear.get("pnl")
    if bear_pnl is not None:
        loss_ratio = abs(float(bear_pnl)) / net_equity * 100.0 if net_equity else 100.0
        if loss_ratio > 5:
            checks.append({"name": "Worst-Case Loss", "status": "WARN",
                           "message": "Bear-case loss $%s is %.1f%% of net equity." % (_num(bear_pnl), loss_ratio)})
        else:
            checks.append({"name": "Worst-Case Loss", "status": "PASS",
                           "message": "Bear-case loss $%s (%.1f%% of net equity) acceptable." % (_num(bear_pnl), loss_ratio)})
    else:
        checks.append({"name": "Worst-Case Loss", "status": "WARN", "message": "No bear-case P&L computed."})

    # 6. Daily loss buffer sufficient?
    max_loss_pct = float(cfg.get("max_daily_loss_pct", 20.0))
    daily_loss_pct = max(0.0, -stats["daily_pnl"]) / equity * 100.0 if equity else 0.0
    buffer_pct = max_loss_pct - daily_loss_pct
    if buffer_pct <= 0:
        checks.append({"name": "Daily Loss Buffer", "status": "BLOCK",
                       "message": "Daily loss already at/over the %.0f%% official lock line." % max_loss_pct})
    elif buffer_pct < 4:
        checks.append({"name": "Daily Loss Buffer", "status": "WARN",
                       "message": "Only %.1f%% loss buffer left before the %.0f%% lock." % (buffer_pct, max_loss_pct)})
    else:
        checks.append({"name": "Daily Loss Buffer", "status": "PASS",
                       "message": "%.1f%% of daily loss buffer remaining." % buffer_pct})

    # 7. Commission included?
    if payoff.get("commission_total"):
        checks.append({"name": "Commission", "status": "PASS",
                       "message": "Commissions $%s deducted in scenario payoff." % _num(payoff["commission_total"])})
    else:
        checks.append({"name": "Commission", "status": "WARN", "message": "Commission not reflected in payoff."})

    # 8. Portfolio concentration?
    conc_after = float(risk.get("concentration_pct") or 0)
    if conc_after > float(cfg.get("max_concentration_pct", 40.0)):
        checks.append({"name": "Concentration", "status": "WARN",
                       "message": "Single-symbol concentration %.1f%% exceeds %.0f%% limit." % (conc_after, cfg.get("max_concentration_pct", 40.0))})
    else:
        checks.append({"name": "Concentration", "status": "PASS",
                       "message": "Concentration %.1f%% within limit." % conc_after})

    # 9. Existing correlated exposure?
    same = [p for p in _load_positions() if p.get("symbol") == symbol]
    if same:
        checks.append({"name": "Correlated Exposure", "status": "WARN",
                       "message": "Already holding %d open position(s) in %s." % (len(same), symbol)})
    else:
        checks.append({"name": "Correlated Exposure", "status": "PASS", "message": "No existing exposure in %s." % symbol})

    # 10. Contracts-today status?
    max_day = int(cfg.get("max_contracts_per_day", 10))
    after = stats["today_contracts"] + qty
    if after > max_day:
        checks.append({"name": "Contracts Today", "status": "BLOCK",
                       "message": "Contracts today %d + %d > limit %d; $1,000 penalty rule applies." % (stats["today_contracts"], qty, max_day)})
    elif after == max_day:
        checks.append({"name": "Contracts Today", "status": "WARN",
                       "message": "Contracts today will hit the %d/day limit." % max_day})
    else:
        checks.append({"name": "Contracts Today", "status": "PASS",
                       "message": "Contracts today %d/%d after this fill." % (after, max_day)})

    return checks


# ---- V2.1 §6 / §18：Position Sizing Engine（确定性引擎；AI 只能解释结果，不能发明数字）----
def _position_direction(pos):
    """从持仓 qty 的符号推断方向（正 = long，负 = short）。"""
    try:
        q = float(pos.get("qty") or 0)
    except (TypeError, ValueError):
        q = 0.0
    return "short" if q < 0 else "long"


def _macro_themes(symbol, direction):
    """返回某品种/方向归属的宏观主题集合；持仓可用 macro_themes 字段显式覆盖。"""
    key = _resolve_symbol(symbol) or (symbol or "")
    spec = CME_MACRO_THEMES.get(key) or {}
    dirn = "short" if str(direction or "").lower() in ("short", "sell", "s") else "long"
    return set(spec.get(dirn) or ())


def _sizing_multiplier_map(cfg, key, base):
    """读取可覆盖的乘数表（§6.2：所有 multiplier 必须可配置，不得硬编码）。"""
    out = dict(base)
    overrides = (cfg.get("sizing_multipliers") or {}).get(key) or {}
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            try:
                out[str(k).strip().upper()] = float(v)
            except (TypeError, ValueError):
                continue
    return out


def _compute_position_sizing(symbol, direction="long", entry_price=None, stop_price=None,
                             stop_pct=None, event_id=None, evidence=None, confirmation=None,
                             qty=None, proposal=None, cfg=None):
    """V2.1 §6 / §18 Position Sizing Engine（确定性；AI 只负责用通俗语言解释这些数字）。

    计算链：
      Risk Budget（权益 × risk_budget_pct）
      → Risk per Contract（Price Distance ÷ Tick Size × Tick Value + Commission + Slippage）
      → Risk-Based Max（向下取整）
      → Evidence-Adjusted Max（× EVIDENCE_MULTIPLIERS）
      → Concentration-Adjusted Max（宏观主题重叠时 × CONCENTRATION_OVERLAP_MULTIPLIER）
      → Final Max = MIN(Concentration-Adjusted, Margin-Based, Daily-Loss-Based, Contract-Limit)
      → Suggested Working Range
    """
    cfg = cfg or _load_risk_config()
    proposal = proposal or {}
    raw_symbol = symbol or proposal.get("symbol")
    code = _resolve_symbol(raw_symbol) or (raw_symbol or "")
    spec = CME_CONTRACT_SPECS.get(code)
    if not spec:
        return {"ok": False, "error": "未知合约：%s" % (raw_symbol or "—"),
                "supported": sorted(CME_CONTRACT_SPECS.keys())}
    dirn = direction or proposal.get("direction") or "long"
    dirn = "short" if str(dirn).strip().lower() in ("short", "sell", "s") else "long"

    risk = _compute_risk()
    stats = _daily_pnl_stats(cfg)
    equity = float(cfg.get("account_equity", 1000000.0) or 0.0)
    net_equity = float(risk.get("net_equity") or equity)
    risk_budget_pct = float(cfg.get("risk_budget_pct", 0.30) or 0.0)
    risk_budget_usd = round(equity * risk_budget_pct / 100.0, 2)

    tick_size = float(spec["tick_size"]) or 0.0000001
    tick_value = float(spec["tick_value"])
    margin_per_contract = float(spec.get("margin_per_contract") or 0.0)
    # 合约乘数（来自合约规格，非 AI 生成，§6.14）：每 1.0 价格变动对应的美元价值。
    contract_multiplier = round(tick_value / tick_size, 6) if tick_size else 0.0

    # 1) 入场价：显式传入 > 同品种持仓最新 mark > 合约参考价
    try:
        entry = float(entry_price) if entry_price not in (None, "") else None
    except (TypeError, ValueError):
        entry = None
    if not entry:
        marks = []
        for p in _load_positions():
            if _resolve_symbol(p.get("symbol")) == code:
                try:
                    m = float(p.get("mark_price") or 0)
                except (TypeError, ValueError):
                    m = 0.0
                if m:
                    marks.append(m)
        entry = marks[-1] if marks else float(spec["reference_price"])

    # 2) 止损距离：显式止损价 > 显式止损百分比 > 历史研究反向四分位 > 配置默认值
    stop_source = "configured default stop percentage"
    stop_used = None
    try:
        sp = float(stop_price) if stop_price not in (None, "") else None
    except (TypeError, ValueError):
        sp = None
    if sp:
        stop_used = sp
        stop_distance = abs(entry - sp)
        stop_source = "explicit stop price"
    else:
        spct = None
        try:
            spct = float(stop_pct) if stop_pct not in (None, "") else None
        except (TypeError, ValueError):
            spct = None
        if spct is not None:
            stop_source = "explicit stop percentage"
        elif event_id:
            study = _compute_event_study(event_id)
            inst = (study.get("instruments") or {}).get(code) or {}
            day = (inst.get("horizons") or {}).get("1d") or {}
            q = day.get("q25") if dirn == "long" else day.get("q75")
            try:
                spct = abs(float(q)) if q is not None else None
            except (TypeError, ValueError):
                spct = None
            if spct is not None:
                stop_source = "historical 1D adverse quartile"
        if spct is None:
            spct = float(cfg.get("default_stop_pct", 0.50) or 0.50)
        stop_distance = abs(entry) * float(spct) / 100.0
        stop_used = round(entry - stop_distance, 6) if dirn == "long" else round(entry + stop_distance, 6)
    stop_distance_pct = round(stop_distance / abs(entry) * 100.0, 4) if entry else 0.0

    # 3) 每手风险 = 价格距离 ÷ Tick Size × Tick Value + 往返佣金 + 滑点缓冲（§6.3）
    slippage_ticks = float(cfg.get("slippage_ticks", 0.0) or 0.0)
    slippage_buffer = round(slippage_ticks * tick_value, 2)
    commission_round_trip = round(CME_COMMISSION_PER_SIDE * 2, 2)
    risk_per_contract = round(stop_distance / tick_size * tick_value + commission_round_trip + slippage_buffer, 2)

    # 4) Risk-Based Max（向下取整，§6.4）
    if risk_per_contract > 0:
        risk_based_max = max(0, int(math.floor(risk_budget_usd / risk_per_contract)))
    else:
        risk_based_max = max(0, int(cfg.get("max_contracts_per_day", 10) or 10))

    # 5) Evidence-Adjusted Max（§6.6）
    ev_map = _sizing_multiplier_map(cfg, "evidence", EVIDENCE_MULTIPLIERS)
    ev_level = (evidence or "").strip().upper() if isinstance(evidence, str) else ""
    ev_source = "manual"
    if not ev_level and event_id:
        study = _compute_event_study(event_id)
        inst = (study.get("instruments") or {}).get(code) or {}
        day = (inst.get("horizons") or {}).get("1d") or {}
        ev_level = str(day.get("evidence") or "").strip().upper()
        ev_source = "historical event study"
    if not ev_level:
        ev_level = "MEDIUM"
        ev_source = "default (no historical sample provided)"
    ev_mult = float(ev_map.get(ev_level, ev_map.get("MEDIUM", 0.75)))
    evidence_adjusted_max = max(0, int(math.floor(risk_based_max * ev_mult)))

    # 6) 市场确认乘数（§6.7）——仅作因子披露，不重复扣减 Final Max（§18 验收口径）
    conf_map = _sizing_multiplier_map(cfg, "confirmation", CONFIRMATION_MULTIPLIERS)
    conf_status = (confirmation or proposal.get("market_confirmation") or "").strip().upper()
    if not conf_status:
        conf_status = "UNSPECIFIED"
        conf_mult = 1.00
    else:
        conf_mult = float(conf_map.get(conf_status, 1.00))

    # 7) Concentration-Adjusted Max（§6.10：宏观主题重叠）
    try:
        overlap_mult = float((cfg.get("sizing_multipliers") or {}).get("concentration_overlap",
                                                                     CONCENTRATION_OVERLAP_MULTIPLIER))
    except (TypeError, ValueError):
        overlap_mult = CONCENTRATION_OVERLAP_MULTIPLIER
    new_themes = _macro_themes(code, dirn)
    overlap_rows = []
    for p in _load_positions():
        p_themes = set(p.get("macro_themes") or []) or _macro_themes(p.get("symbol"), _position_direction(p))
        shared = sorted(new_themes & p_themes)
        if shared:
            overlap_rows.append({"symbol": p.get("symbol"), "direction": _position_direction(p),
                                 "shared_themes": shared})
    if overlap_rows:
        concentration_adjusted_max = max(0, int(math.floor(evidence_adjusted_max * overlap_mult)))
        concentration_status = "CAUTION"
    else:
        concentration_adjusted_max = evidence_adjusted_max
        concentration_status = "PASS"

    # 8) Margin-Based Max（§6.8）
    headroom = float(risk.get("headroom") or 0.0)
    if margin_per_contract > 0:
        margin_based_max = max(0, int(math.floor(max(0.0, headroom) / margin_per_contract)))
    else:
        margin_based_max = concentration_adjusted_max

    # 9) Daily-Loss-Based Max（§6.9）
    max_daily_loss_pct = float(cfg.get("max_daily_loss_pct", 20.0) or 20.0)
    daily_loss_limit_usd = round(equity * max_daily_loss_pct / 100.0, 2)
    daily_loss_used = round(max(0.0, -float(stats.get("daily_pnl") or 0.0)), 2)
    daily_loss_remaining = round(max(0.0, daily_loss_limit_usd - daily_loss_used), 2)
    if risk_per_contract > 0:
        daily_loss_based_max = max(0, int(math.floor(daily_loss_remaining / risk_per_contract)))
    else:
        daily_loss_based_max = concentration_adjusted_max

    # 10) Contract-Limit Max（赛制每日 10 张上限）
    max_day = int(cfg.get("max_contracts_per_day", 10) or 10)
    contract_limit_max = max(0, max_day - int(stats.get("today_contracts") or 0))

    # 11) Final Max = MIN(所有上限)（§6.11）
    caps = (
        ("集中度调整上限", concentration_adjusted_max),
        ("保证金上限", margin_based_max),
        ("单日亏损上限", daily_loss_based_max),
        ("合约数上限", contract_limit_max),
    )
    final_max = max(0, min(v for _, v in caps))
    binding = next((n for n, v in caps if v == final_max), caps[0][0])

    # 12) Suggested Working Range：上限为 Final Max，下限为其 2/3（§6.12 案例：Final 3 → 2–3）
    if final_max <= 0:
        range_low = range_high = 0
    else:
        range_high = final_max
        range_low = max(1, int(math.ceil(final_max * 2.0 / 3.0)))
        if range_low > range_high:
            range_low = range_high
    suggested_label = "%d" % range_high if range_low == range_high else "%d–%d" % (range_low, range_high)

    # 13) 当前选中手数 + 预估亏损 / 账户影响
    try:
        selected_qty = int(qty if qty not in (None, "") else (proposal.get("qty") or 0))
    except (TypeError, ValueError):
        selected_qty = 0
    loss_qtys = sorted({q for q in (range_low, range_high, final_max, risk_based_max) if q and q > 0})
    estimated_loss = [{"qty": q, "loss": round(-q * risk_per_contract, 2)} for q in loss_qtys]
    ref_qty = selected_qty if selected_qty > 0 else range_high
    account_impact_pct = round(ref_qty * risk_per_contract / equity * 100.0, 4) if equity else 0.0

    margin_required = round(ref_qty * margin_per_contract, 2)
    if net_equity and margin_required >= net_equity:
        margin_status = "BLOCK"
    elif net_equity and margin_required / net_equity * 100.0 > 80:
        margin_status = "CAUTION"
    else:
        margin_status = "PASS"

    if overlap_rows:
        why_not_more = ("The risk budget alone would allow up to %d contract(s), but the portfolio already "
                        "holds exposure to the same macro theme (%s), so the engine reduced the suggested size."
                        % (risk_based_max, ", ".join(sorted({t for r in overlap_rows for t in r["shared_themes"]}))))
    elif final_max < risk_based_max:
        why_not_more = ("The risk budget alone would allow up to %d contract(s); the %s reduced it to %d."
                        % (risk_based_max, binding, final_max))
    else:
        why_not_more = ("The risk budget allows up to %d contract(s), and no other limit reduced it further."
                        % risk_based_max)

    warnings = []
    if overlap_rows:
        warnings.append("Existing portfolio is already exposed to the same macro thesis (%s)."
                        % ", ".join(sorted({t for r in overlap_rows for t in r["shared_themes"]})))
    if final_max <= 0:
        warnings.append("No position size is permitted under the current risk limits.")
    elif final_max < evidence_adjusted_max:
        warnings.append("Suggested size is capped below the evidence-adjusted maximum by %s." % binding)
    if conf_status == "NO TRADE":
        warnings.append("Market confirmation status is NO TRADE.")
    if margin_status == "BLOCK":
        warnings.append("Margin required would exceed net equity.")
    if selected_qty > final_max:
        warnings.append("Selected quantity %d exceeds the Final Maximum of %d contract(s)."
                        % (selected_qty, final_max))

    # 14) What-if 每手基准值（§6.15）：全部与手数线性相关，前端滑块可即时换算。
    notional_per_contract = round(entry * contract_multiplier, 2)
    scenario_per_contract = None
    if event_id:
        sp = _proposal_payoff(event_id, code, dirn, 1)
        if sp:
            scenario_per_contract = {
                "bear": sp["bear"]["pnl"],
                "base": sp["base"]["pnl"],
                "bull": sp["bull"]["pnl"],
            }
    what_if = {
        "stop_risk_per_contract": round(-risk_per_contract, 2),
        "margin_per_contract": margin_per_contract,
        "commission_per_contract": commission_round_trip,
        "notional_per_contract": notional_per_contract,
        "scenario_per_contract": scenario_per_contract,
    }

    # V2.1 Contract Context：当前持仓（同品种净数量，供 9 字段展示）
    current_position = 0
    for p in _load_positions():
        if _resolve_symbol(p.get("symbol")) == code:
            try:
                current_position += float(p.get("qty") or 0)
            except (TypeError, ValueError):
                pass

    months = CME_CONTRACT_MONTHS.get(code, [])
    active_month = next((m for m in months if m.get("active")), months[0] if months else None)

    return {
        "ok": True,
        "symbol": code,
        "name": spec.get("name", code),
        "direction": dirn,
        "contract": {
            "instrument": "%s (%s)" % (spec.get("name", code), code),
            "contract_type": CME_CONTRACT_TYPE_LABELS.get(code, "Futures"),
            "tick_size": tick_size,
            "tick_value": tick_value,
            "contract_multiplier": contract_multiplier,
            "contract_size": CME_CONTRACT_TYPE_LABELS.get(code, "Futures"),
            "contract_month": (active_month or {}).get("month"),
            "contract_code": (active_month or {}).get("code"),
            "expiry": (active_month or {}).get("expiry"),
            "months": months,
            "current_position": int(current_position) if current_position == int(current_position) else current_position,
            "reference_price": float(spec["reference_price"]),
            "margin_per_contract": margin_per_contract,
            "commission_per_side": CME_COMMISSION_PER_SIDE,
            "commission_round_trip": commission_round_trip,
            "slippage_ticks": slippage_ticks,
            "slippage_buffer": slippage_buffer,
        },
        "account": {
            "account_equity": equity,
            "net_equity": round(net_equity, 2),
            "risk_budget_pct": risk_budget_pct,
            "risk_budget_usd": risk_budget_usd,
            "max_daily_loss_pct": max_daily_loss_pct,
            "daily_loss_limit_usd": daily_loss_limit_usd,
            "daily_loss_used_usd": daily_loss_used,
            "daily_loss_remaining_usd": daily_loss_remaining,
            "margin_used": float(risk.get("margin_used") or 0.0),
            "headroom": round(headroom, 2),
        },
        "levels": {
            "entry": entry,
            "stop": stop_used,
            "stop_distance": round(stop_distance, 6),
            "stop_distance_pct": stop_distance_pct,
            "stop_source": stop_source,
            "risk_per_contract": risk_per_contract,
        },
        "evidence": {"level": ev_level, "multiplier": ev_mult,
                     "adjusted_max": evidence_adjusted_max, "source": ev_source},
        "confirmation": {"status": conf_status, "multiplier": conf_mult,
                         "adjusted_max": int(math.floor(evidence_adjusted_max * conf_mult)),
                         "applied_to_final": False},
        "concentration": {"status": concentration_status, "overlap_multiplier": overlap_mult,
                          "overlaps": overlap_rows,
                          "adjusted_max": concentration_adjusted_max,
                          "limit_pct": float(cfg.get("max_concentration_pct", 40.0) or 40.0)},
        "limits": {
            "risk_based_max": risk_based_max,
            "evidence_adjusted_max": evidence_adjusted_max,
            "concentration_adjusted_max": concentration_adjusted_max,
            "margin_based_max": margin_based_max,
            "daily_loss_based_max": daily_loss_based_max,
            "contract_limit_max": contract_limit_max,
            "final_max": final_max,
            "binding_constraint": binding,
        },
        "suggested": {"low": range_low, "high": range_high, "label": suggested_label},
        "selected_qty": selected_qty,
        "selected_in_range": bool(selected_qty and range_low <= selected_qty <= range_high),
        "selected_exceeds_final_max": bool(selected_qty > final_max),
        "estimated_loss": estimated_loss,
        "account_impact_pct": account_impact_pct,
        "margin_required": margin_required,
        "margin_status": margin_status,
        "what_if": what_if,
        "warnings": warnings,
        "simple_view": {
            "question": "How much should we consider trading?",
            "suggested_label": ("%s %s" % (suggested_label, code)) if final_max > 0 else "No position",
            "why_not_more": why_not_more,
            "max_risk_limit": "%d %s" % (risk_based_max, code),
            "max_risk_limit_note": "Maximum risk-based size is a risk ceiling, not a recommendation to use full size.",
            "estimated_loss": estimated_loss,
            "account_impact": ("%d contract(s) would risk approximately %.3f%% of current equity."
                               % (ref_qty, account_impact_pct)) if ref_qty else "n/a",
            "margin": margin_status,
            "portfolio_concentration": concentration_status,
        },
        "professional": {
            "account_equity": equity,
            "risk_budget_pct": risk_budget_pct,
            "risk_budget_usd": risk_budget_usd,
            "entry": entry,
            "stop": stop_used,
            "stop_distance": round(stop_distance, 6),
            "tick_size": tick_size,
            "tick_value": tick_value,
            "contract_multiplier": contract_multiplier,
            "risk_per_contract": risk_per_contract,
            "commission": commission_round_trip,
            "slippage_buffer": slippage_buffer,
            "margin_per_contract": margin_per_contract,
            "risk_based_max": risk_based_max,
            "margin_based_max": margin_based_max,
            "daily_loss_based_max": daily_loss_based_max,
            "concentration_adjusted_max": concentration_adjusted_max,
            "contract_limit_max": contract_limit_max,
            "evidence_multiplier": ev_mult,
            "confirmation_multiplier": conf_mult,
            "final_max": final_max,
            "suggested_range": suggested_label,
        },
        "source_ids": {"event_id": event_id or proposal.get("event_id"),
                       "proposal_id": proposal.get("id")},
        "computed_at": _now_ms(),
    }


@app.route("/api/cme/position-sizing", methods=["GET", "POST"])
def api_cme_position_sizing():
    """V2.1 §6/§18 Position Sizing Engine 端点（确定性输出，供 UI 与 AI 引用）。"""
    data = request.get_json(silent=True) or {} if request.method == "POST" else request.args.to_dict()
    proposal_id = (data.get("proposal_id") or "").strip()
    proposal = None
    if proposal_id:
        proposal = next((p for p in _load_proposals() if p.get("id") == proposal_id), None)
        if proposal is None:
            return jsonify({"ok": False, "error": "proposal 不存在"}), 404
    symbol = (data.get("symbol") or "").strip() or (proposal or {}).get("symbol")
    if not symbol:
        return jsonify({"ok": False, "error": "symbol 不能为空"}), 400
    ev_id = (data.get("event_id") or "").strip()
    if not ev_id and proposal:
        origin = proposal.get("origin")
        if isinstance(origin, dict):
            ev_id = (origin.get("event_id") or "").strip()
    result = _compute_position_sizing(
        symbol=symbol,
        direction=data.get("direction") or (proposal or {}).get("direction"),
        entry_price=data.get("entry_price"),
        stop_price=data.get("stop_price"),
        stop_pct=data.get("stop_pct"),
        event_id=ev_id,
        evidence=data.get("evidence"),
        confirmation=data.get("confirmation") or (proposal or {}).get("market_confirmation"),
        qty=data.get("qty") or (proposal or {}).get("qty"),
        proposal=proposal,
    )
    return jsonify(result), (200 if result.get("ok") else 400)


# ============================================================
# API：模块 D —— Risk Engine + 赛制运营
# ============================================================
def _compute_risk():
    """汇总组合风险：权益、保证金、盈亏、集中度、当日 PnL、风险带、赛制状态。"""
    cfg = _load_risk_config()
    positions = _load_positions()
    equity = float(cfg.get("account_equity", 1000000.0))
    margin_used = 0.0
    unrealized = 0.0
    gross_exposure = 0.0
    for pos in positions:
        qty = float(pos.get("qty", 0) or 0)
        avg = float(pos.get("avg_price", 0) or 0)
        mark = float(pos.get("mark_price", 0) or 0)
        margin_used += float(pos.get("margin", 0) or (abs(qty) * avg * cfg.get("margin_pct", 10.0) / 100.0))
        unrealized += qty * (mark - avg)
        gross_exposure += abs(qty) * mark
    net_equity = equity + unrealized
    margin_util = round(margin_used / equity * 100.0, 2) if equity else 0.0
    # 集中度：最大单品种 exposure 占比
    conc = 0.0
    if positions and gross_exposure > 0:
        conc = round(max((abs(float(p.get("qty", 0)) * float(p.get("mark_price", 0) or 0)) / gross_exposure * 100.0)
                         for p in positions), 2)
    stats = _daily_pnl_stats(cfg)
    daily_loss_pct = round(max(0.0, -stats["daily_pnl"]) / equity * 100.0, 2) if equity else 0.0
    return {
        "account_equity": equity,
        "net_equity": round(net_equity, 2),
        "margin_used": round(margin_used, 2),
        "margin_utilization_pct": margin_util,
        "headroom": round(net_equity - margin_used, 2),
        "unrealized_pnl": round(unrealized, 2),
        "gross_exposure": round(gross_exposure, 2),
        "concentration_pct": conc,
        "daily_pnl": stats["daily_pnl"],
        "realized_pnl_today": stats["realized_pnl_today"],
        "fees_today": stats["fees_today"],
        "daily_loss_pct": daily_loss_pct,
        "risk_band": _risk_band(daily_loss_pct),
        "today_contracts": stats["today_contracts"],
        "trading_date": stats["trading_date"],
        "max_contracts_per_day": cfg.get("max_contracts_per_day", 10),
        "max_concentration_pct": cfg.get("max_concentration_pct", 40.0),
        "max_daily_loss_pct": cfg.get("max_daily_loss_pct", 20.0),
        "competition_open": cfg.get("competition_open", True),
        "final_day_liquidation": cfg.get("final_day_liquidation", False),
        "contract_near_expiry": cfg.get("contract_near_expiry", False),
        "competition_timezone": cfg.get("competition_timezone", "America/Chicago"),
        "warnings": [],
    }


@app.route("/api/cme/risk", methods=["GET"])
def api_cme_risk():
    risk = _compute_risk()
    warnings = []
    if not risk["competition_open"]:
        warnings.append("赛程未开始或已结束，禁止新开仓")
    if risk["final_day_liquidation"]:
        warnings.append("最后交易日清仓窗口：仅允许平仓")
    if risk["margin_utilization_pct"] > 80:
        warnings.append("保证金利用率超过 80%")
    if risk["concentration_pct"] > risk["max_concentration_pct"]:
        warnings.append("单品种集中度超过红线 %.0f%%" % risk["max_concentration_pct"])
    if risk["risk_band"] == "OFFICIAL LOCK RISK":
        warnings.append("单日亏损已达 %.0f%% 官方锁定线：当日禁止新开仓" % risk["max_daily_loss_pct"])
    elif risk["risk_band"] == "CRITICAL":
        warnings.append("单日亏损 18-20%：高风险区，仅允许对冲/平仓")
    elif risk["risk_band"] == "HIGH RISK":
        warnings.append("单日亏损 16-18%：禁止加仓")
    elif risk["risk_band"] == "REDUCE RISK":
        warnings.append("单日亏损 12-16%：建议降低仓位")
    elif risk["risk_band"] == "CAUTION":
        warnings.append("单日亏损 8-12%：保持谨慎")
    if risk["today_contracts"] >= risk["max_contracts_per_day"]:
        warnings.append("今日合约数已达上限 %d/%d" % (risk["today_contracts"], risk["max_contracts_per_day"]))
    risk["warnings"] = warnings
    return jsonify(risk)


@app.route("/api/cme/risk-config", methods=["GET"])
def api_cme_get_risk_config():
    return jsonify(_load_risk_config())


@app.route("/api/cme/risk-config", methods=["POST"])
def api_cme_update_risk_config():
    data = request.get_json(silent=True) or {}
    cfg = _load_risk_config()

    def _to_bool(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    for key, cast in (
        ("account_equity", float), ("max_contracts_per_day", int),
        ("max_concentration_pct", float), ("max_daily_loss_pct", float),
        ("margin_pct", float), ("competition_open", _to_bool),
        ("final_day_liquidation", _to_bool), ("contract_near_expiry", _to_bool),
        ("competition_timezone", str), ("trading_date", str),
    ):
        if key in data and data[key] is not None and data[key] != "":
            try:
                cfg[key] = cast(data[key])
            except (TypeError, ValueError):
                return jsonify({"error": "字段 %s 的值非法" % key}), 400
    _save_risk_config(cfg)
    return jsonify({"success": True, "config": cfg})


@app.route("/api/cme/positions", methods=["GET"])
def api_cme_get_positions():
    return jsonify(_load_positions())


@app.route("/api/cme/positions", methods=["POST"])
def api_cme_add_position():
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip()
    qty = data.get("qty")
    if not symbol or qty is None:
        return jsonify({"error": "symbol 和 qty 不能为空"}), 400
    pos = {
        "symbol": symbol,
        "qty": float(qty),
        "avg_price": float(data.get("avg_price") or 0),
        "mark_price": float(data.get("mark_price") or 0),
        "unrealized_pnl": float(data.get("unrealized_pnl") or 0),
        "margin": float(data.get("margin") or 0),
        "opened_at": data.get("opened_at") or time.strftime("%Y-%m-%d %H:%M", time.localtime()),
    }
    positions = _load_positions()
    positions.append(pos)
    _save_positions(positions)
    return jsonify({"success": True, "position": pos})


@app.route("/api/cme/positions/<int:index>", methods=["DELETE"])
def api_cme_delete_position(index):
    positions = _load_positions()
    if index < 0 or index >= len(positions):
        return jsonify({"error": "索引越界"}), 404
    positions.pop(index)
    _save_positions(positions)
    return jsonify({"success": True})


@app.route("/api/cme/journal", methods=["GET"])
def api_cme_get_journal():
    journal = _load_journal()
    journal.sort(key=lambda j: j.get("entry_time", ""), reverse=True)
    return jsonify(journal)


@app.route("/api/cme/journal", methods=["POST"])
def api_cme_add_journal():
    data = request.get_json(silent=True) or {}
    journal = _load_journal()
    entry = {
        "id": _new_id(),
        "trade_id": data.get("trade_id") or "",
        "proposal_id": data.get("proposal_id") or "",
        "symbol": (data.get("symbol") or "").strip(),
        "direction": (data.get("direction") or "").strip(),
        "entry_time": data.get("entry_time") or time.strftime("%Y-%m-%d %H:%M", time.localtime()),
        "exit_time": data.get("exit_time") or "",
        "entry_price": data.get("entry_price"),
        "exit_price": data.get("exit_price"),
        "qty": data.get("qty"),
        "pnl": data.get("pnl"),
        "thesis_result": (data.get("thesis_result") or "").strip(),
        "error_tags": data.get("error_tags") or [],
        "review": (data.get("review") or "").strip(),
    }
    journal.append(entry)
    _save_journal(journal)
    return jsonify({"success": True, "entry": entry})


@app.route("/api/cme/journal/<journal_id>", methods=["DELETE"])
def api_cme_delete_journal(journal_id):
    journal = _load_journal()
    journal = [j for j in journal if j.get("id") != journal_id]
    _save_journal(journal)
    return jsonify({"success": True})


# ============================================================
# API：备份导出 / 还原导入（双保险：换平台、误删、云端异常都可恢复）
# ============================================================
@app.route("/api/cme/export", methods=["GET"])
def api_cme_export():
    """导出 CME 小窝全部数据为单个 JSON。"""
    payload = {}
    for name in _CME_COLLECTIONS:
        if name == "risk_config":
            payload[name] = _load_risk_config()
        else:
            payload[name] = _cme_load(name, [])
    return jsonify({
        "app": "parite",
        "module": "cme",
        "version": 1,
        "exported_at": _now_ms(),
        "data": payload,
    })


@app.route("/api/cme/import", methods=["POST"])
def api_cme_import():
    """从导出的 JSON 还原全部数据（覆盖写入）。"""
    data = request.get_json(silent=True) or {}
    payload = data.get("data") or data.get("export") or {}
    if not isinstance(payload, dict) or not payload:
        return jsonify({"error": "导入内容为空或格式不正确"}), 400
    restored = {}
    for name in _CME_COLLECTIONS:
        if name in payload and payload[name]:
            _cme_save(name, payload[name])
            restored[name] = len(payload[name]) if isinstance(payload[name], (list, dict)) else 1
    return jsonify({"success": True, "restored": restored})


# 演示数据中文名（前端提示条展示用）
_CME_DEMO_LABELS = {
    "snapshots": "行情快照",
    "signals": "Macro Score 信号",
    "events": "经济事件",
    "scenarios": "事件情景推演",
    "event_config": "事件阈值配置",
    "proposals": "交易提案",
    "positions": "持仓",
    "journal": "交易日志",
    "risk_config": "风控参数",
}


@app.route("/api/cme/demo-status", methods=["GET"])
def api_cme_demo_status():
    """告知前端当前哪些功能正在展示演示数据（页面顶部提示条用）。"""
    active = [n for n in _CME_COLLECTIONS if _cme_is_demo(n)]
    return jsonify({
        "demo": bool(active),
        "collections": active,
        "labels": [_CME_DEMO_LABELS.get(n, n) for n in active],
    })


# ============================================================
# AI 助手 API（配置管理 + 问答代理）
# ============================================================
def _ai_config_path():
    """返回 ai_config.json 的绝对路径"""
    return os.path.join(_data_dir(), "ai_config.json")


def _load_ai_config():
    """读取 AI 配置（多模型）。

    优先级：环境变量 > Upstash 云端 > 本地文件 > 默认值。
    数据结构：{"active": "<provider_id>", "providers": [{id,name,type,base_url,api_key,model}]}
    """
    import json as _json
    default_provider = {
        "id": "default",
        "name": "DeepSeek",
        "type": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
    }
    cfg = {"active": "default", "providers": [dict(default_provider)]}

    # 1. 本地文件（开发环境；兼容旧版单模型格式并自动迁移）
    path = _ai_config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            if isinstance(data.get("providers"), list) and data["providers"]:
                cfg["active"] = data.get("active", "") or ""
                cfg["providers"] = data["providers"]
            else:
                legacy = dict(default_provider)
                for k in ("base_url", "api_key", "model"):
                    if data.get(k):
                        legacy[k] = data[k]
                cfg = {"active": "default", "providers": [legacy]}
        except Exception:
            pass

    # 2. Upstash 云端（Vercel 无状态环境下的持久化层）
    cloud = _kv_get("parite:ai_config")
    if isinstance(cloud, dict) and isinstance(cloud.get("providers"), list) and cloud["providers"]:
        cfg["active"] = cloud.get("active", "") or ""
        cfg["providers"] = cloud["providers"]

    # 3. 环境变量覆盖（最高优先级，作用于默认模型）
    if os.environ.get("DEEPSEEK_API_KEY"):
        cfg["providers"][0]["api_key"] = os.environ["DEEPSEEK_API_KEY"]
    if os.environ.get("AI_API_KEY"):
        cfg["providers"][0]["api_key"] = os.environ["AI_API_KEY"]
    if os.environ.get("AI_BASE_URL"):
        cfg["providers"][0]["base_url"] = os.environ["AI_BASE_URL"]
    if os.environ.get("AI_MODEL"):
        cfg["providers"][0]["model"] = os.environ["AI_MODEL"]

    # 4. 校验 active 指向有效模型
    if cfg["active"] not in [p.get("id") for p in cfg["providers"]]:
        cfg["active"] = cfg["providers"][0].get("id", "default")
    return cfg


def _save_ai_config(cfg):
    import json as _json
    with open(_ai_config_path(), "w", encoding="utf-8") as f:
        _json.dump(cfg, f, ensure_ascii=False, indent=2)
    _kv_set("parite:ai_config", cfg)


def _mask_api_key(key):
    key = key or ""
    if len(key) > 8:
        return key[:4] + "*" * (len(key) - 8) + key[-4:]
    return ("*" * len(key)) if key else ""


def _active_provider(cfg):
    providers = cfg.get("providers") or []
    if not providers:
        return None
    for p in providers:
        if p.get("id") == cfg.get("active"):
            return p
    return providers[0]


def _find_provider(cfg, provider_id):
    for p in cfg.get("providers") or []:
        if p.get("id") == provider_id:
            return p
    return None


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """管理员登录"""
    cfg = _load_admin_config()
    admin_pwd = cfg.get("admin_password", "")
    # 如果未设置管理员密码，直接登录
    if not admin_pwd:
        session["is_admin"] = True
        return redirect(url_for("ai_config"))
    if request.method == "POST":
        pwd = (request.form.get("password") or "").strip()
        if pwd == admin_pwd:
            session["is_admin"] = True
            return redirect(url_for("ai_config"))
        return render_template("admin_login.html", active="", error="密码错误",
                               currency_nav=DATA.CURRENCY_NAV)
    return render_template("admin_login.html", active="", error=None,
                           currency_nav=DATA.CURRENCY_NAV)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


@app.route("/ai-config")
def ai_config():
    """AI 助手配置页面（需要管理员登录）"""
    cfg = _load_admin_config()
    admin_pwd = cfg.get("admin_password", "")
    # 未设置管理员密码时视为管理员（允许首次设置密码与邮箱授权码）
    is_admin = (not admin_pwd) or _is_admin()
    if admin_pwd and not _is_admin():
        return redirect(url_for("admin_login"))
    return render_template("ai_config.html", active="ai_config", is_admin=is_admin,
                           admin_config=cfg, currency_nav=DATA.CURRENCY_NAV)


@app.route("/api/ai/config", methods=["GET"])
def api_get_ai_config():
    """读取 AI 配置列表（api_key 脱敏显示）"""
    cfg = _load_ai_config()
    providers = []
    for p in cfg.get("providers") or []:
        providers.append({
            "id": p.get("id", ""),
            "name": p.get("name", ""),
            "type": p.get("type", "openai"),
            "base_url": p.get("base_url", ""),
            "api_key": _mask_api_key(p.get("api_key", "")),
            "model": p.get("model", ""),
            "has_key": bool(p.get("api_key", "")),
        })
    active = _active_provider(cfg)
    return jsonify({
        "providers": providers,
        "active": cfg.get("active", ""),
        "has_key": bool(active and active.get("api_key")),
    })


@app.route("/api/ai/config", methods=["POST"])
def api_save_ai_config():
    """保存多模型 AI 配置（需要管理员权限）"""
    # 管理员密码已设置时，必须登录才能修改
    cfg = _load_admin_config()
    if cfg.get("admin_password") and not _is_admin():
        return jsonify({"error": "需要管理员权限，请先登录", "need_login": True}), 403

    data = request.get_json(silent=True) or {}
    providers = data.get("providers")
    if not isinstance(providers, list) or not providers:
        return jsonify({"error": "至少需要一个模型配置"}), 400

    existing = _load_ai_config()
    existing_map = {p.get("id"): p for p in existing.get("providers") or []}
    cleaned = []
    for i, p in enumerate(providers):
        pid = (p.get("id") or "").strip() or ("model_" + str(i + 1))
        name = (p.get("name") or "").strip() or pid
        ptype = (p.get("type") or "openai").strip() or "openai"
        base_url = (p.get("base_url") or "").strip().rstrip("/")
        model = (p.get("model") or "").strip()
        api_key = (p.get("api_key") or "").strip()
        if not base_url or not model:
            return jsonify({"error": f"模型「{name}」的 API 地址和模型名称不能为空"}), 400
        # 密钥留空（含脱敏星号）时保留原密钥
        if not api_key or set(api_key) == {"*"}:
            api_key = (existing_map.get(pid) or {}).get("api_key", "")
        cleaned.append({
            "id": pid,
            "name": name,
            "type": ptype,
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
        })

    active = (data.get("active") or "").strip()
    if active not in [p["id"] for p in cleaned]:
        active = cleaned[0]["id"]

    new_cfg = {"active": active, "providers": cleaned}
    try:
        _save_ai_config(new_cfg)
    except Exception as e:
        return jsonify({"error": f"保存失败：{e}"}), 500

    return jsonify({"success": True, "message": "配置已保存"})


# ============================================================
# 管理员配置 API（邮箱授权码、管理员密码）
# ============================================================
@app.route("/api/admin/config", methods=["POST"])
def api_save_admin_config():
    """保存管理员配置（仅管理员可操作）"""
    if not _is_admin():
        # 若未设管理员密码，允许首次设置
        existing = _load_admin_config()
        if existing.get("admin_password"):
            return jsonify({"error": "需要管理员权限"}), 403
    data = request.get_json(silent=True) or {}
    existing = _load_admin_config()
    # 仅更新提供的字段
    if "admin_password" in data:
        pwd = (data["admin_password"] or "").strip()
        if pwd:
            existing["admin_password"] = pwd
    if "mail_auth_code" in data:
        existing["mail_auth_code"] = (data["mail_auth_code"] or "").strip()
    if "mail_address" in data:
        addr = (data["mail_address"] or "").strip()
        if addr:
            existing["mail_address"] = addr
    _save_admin_config(existing)
    return jsonify({"success": True, "message": "管理员配置已保存"})


@app.route("/api/admin/mail-test", methods=["POST"])
def api_mail_test():
    """测试邮件发送"""
    if not _is_admin():
        return jsonify({"error": "需要管理员权限"}), 403
    ok, msg = _send_feedback_mail({
        "category": "测试邮件",
        "content": "这是一封来自 Parité 平台的测试邮件，验证 SMTP 配置是否正确。",
        "contact": "系统",
        "time": _json.dumps({"note": "test"}, ensure_ascii=False),
    })
    if ok:
        return jsonify({"success": True, "message": msg})
    return jsonify({"error": msg}), 200


def _call_openai(provider, system_prompt, user_content, temperature=0.3):
    """调用 OpenAI 兼容的 /chat/completions 接口（DeepSeek / GPT / 通义等）"""
    import json as _json
    import urllib.request
    import urllib.error
    base_url = (provider.get("base_url") or "https://api.deepseek.com/v1").rstrip("/")
    url = base_url + "/chat/completions"
    payload = {
        "model": provider.get("model", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
    }
    req = urllib.request.Request(
        url,
        data=_json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + (provider.get("api_key") or ""),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=150) as resp:
        result = _json.loads(resp.read().decode("utf-8"))
    return (
        result.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )


def _call_anthropic(provider, system_prompt, user_content, temperature=0.3):
    """调用 Anthropic 原生 /messages 接口（Claude 系列）"""
    import json as _json
    import urllib.request
    import urllib.error
    base_url = (provider.get("base_url") or "https://api.anthropic.com/v1").rstrip("/")
    url = base_url + "/messages"
    payload = {
        "model": provider.get("model", "claude-sonnet-4-5"),
        "max_tokens": 4096,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}],
    }
    req = urllib.request.Request(
        url,
        data=_json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": provider.get("api_key") or "",
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=150) as resp:
        result = _json.loads(resp.read().decode("utf-8"))
    parts = result.get("content", []) or []
    return "".join(c.get("text", "") for c in parts if c.get("type") == "text").strip()


def _call_provider(provider, system_prompt, user_content, temperature=0.3):
    """按模型类型分发请求"""
    ptype = (provider.get("type") or "openai").lower()
    if ptype == "anthropic":
        return _call_anthropic(provider, system_prompt, user_content, temperature)
    return _call_openai(provider, system_prompt, user_content, temperature)


@app.route("/api/ai/ask", methods=["POST"])
def api_ai_ask():
    """AI 问答代理：按模型类型调用 OpenAI / Anthropic 接口"""
    import json as _json
    import urllib.request
    import urllib.error

    cfg = _load_ai_config()
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    context = (data.get("context") or "").strip()
    provider_id = (data.get("provider") or "").strip()

    provider = _find_provider(cfg, provider_id)
    if provider is None:
        provider = _active_provider(cfg)
    if not provider:
        return jsonify({"error": "请先配置 AI 模型", "need_config": True}), 200
    if not (provider.get("api_key") or ""):
        return jsonify({"error": f"模型「{provider.get('name','')}」未配置 API 密钥，请先前往 AI 配置页面设置", "need_config": True}), 200

    if not question and not context:
        return jsonify({"error": "问题不能为空"}), 400
    if not question:
        question = context
        context = ""

    # 系统提示词：外汇研究助手
    system_prompt = (
        "你是 Parité 多货币外汇研究平台的 AI 研究助手，专注于外汇市场、货币政策、"
        "汇率分析、利率与汇率关系等领域。请用专业、准确、简洁的中文回答用户的提问。"
        "如涉及数据或结论，请说明依据；若问题超出外汇研究领域，可简要提示并尽量给出有帮助的回答。"
    )

    # 拼接用户消息：如有选中文字作为上下文，则附加
    if context:
        user_content = f"参考以下内容：\n{context}\n\n问题：{question}"
    else:
        user_content = question

    try:
        answer = _call_provider(provider, system_prompt, user_content)
        if not answer:
            return jsonify({"error": "AI 返回内容为空"}), 200
        return jsonify({"answer": answer})
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
            err_msg = _json.loads(err_body).get("error", {}).get("message", err_body)
        except Exception:
            err_msg = f"HTTP {e.code}"
        return jsonify({"error": f"AI 接口返回错误：{err_msg}"}), 200
    except Exception as e:
        return jsonify({"error": f"请求失败：{e}"}), 200


# ============================================================
# 阶段 5 —— AI RESEARCH ANALYST（Context Builder + 结构化研究回答）
# 架构：User Question → Context Builder → Provider → 固定 JSON 结构
# AI 只解释确定性数据，绝不编造数字、绝不决定手数（MODULE 5 / V2.1 §12 §13）
# ============================================================
CME_AI_STALE_MS = 36 * 3600 * 1000          # 快照/信号超过 36 小时视为过期
CME_AI_MISSING = "Missing: %s"

# V2.1 §13 的 7 段固定结构
CME_AI_SECTION_KEYS = (
    "simple_view",
    "why",
    "market_confirmation",
    "suggested_direction",
    "position_size_context",
    "main_risk",
    "what_to_watch",
)
# V2 MODULE 5 §6.2 的附加字段（用于快捷按钮的支撑/反方/失效条件渲染）
CME_AI_EXTRA_KEYS = (
    "base_view", "supporting_factors", "counter_factors",
    "historical_context", "invalidation", "what_to_watch_next",
    "evidence_quality", "missing_data",
)

# ============================================================
# V2.2 —— 多模型路由 · 分析缓存 · 成本控制
# LEVEL 0 NO LLM / LEVEL 1 DeepSeek（默认）/ LEVEL 2 GPT Terra
# LEVEL 3A Claude（独立复核）/ LEVEL 3B GPT Sol（深度分析）
# ============================================================
CME_AI_LEVELS = {
    "quick": {
        "level": 1, "label": "快速分析 Quick Analysis", "role": "日常研究助手",
        "target": "deepseek", "cost_usd": 0.08,
        "note": "日常研究助手（默认，≈80–90% 调用），保持 36 小时数据新鲜度即可",
    },
    "final": {
        "level": 2, "label": "终极分析 Final Analysis", "role": "主交易分析师",
        "target": "gpt", "cost_usd": 0.74,
        "note": "主交易分析师：生成交易提案前的最终版分析",
    },
    "review": {
        "level": 3, "label": "独立复核 Independent Review", "role": "独立复核",
        "target": "claude", "cost_usd": 0.22,
        "note": "独立复核：找分歧与盲点（RECOMMEND_ONLY 默认，需人工点击）",
    },
    "deep": {
        "level": 3, "label": "深度分析 Deep Analysis", "role": "深度推演",
        "target": "sol", "cost_usd": 1.20,
        "note": "深度分析：仅在复杂场景手动触发（更多 ▼ 菜单内）",
    },
}
CME_AI_PREMIUM_LEVELS = {"final", "review", "deep"}
CME_AI_PREMIUM_COOLDOWN_MS = 15 * 60 * 1000   # premiumCooldownMinutes = 15
CME_AI_MAX_PREMIUM_PER_PROPOSAL = 1           # Claude 触发时允许 2；Sol 不计入
CME_AI_MISSING_GATE = 6                        # 缺失项 ≥ 该阈值 → INSUFFICIENT DATA
CME_AI_INSUFFICIENT_MSG = (
    "数据不足 — 缺少关键输入（%s）。请先补录行情快照/事件/提案后重试；"
    "更贵的模型也不能把缺失数据变成真实数据。"
)


def _cme_ai_match_provider(providers, keyword):
    """按关键词（deepseek/gpt/claude/sol 等）模糊匹配已配置模型。"""
    if not keyword:
        return None
    kw = str(keyword).lower()
    for p in providers or []:
        hay = " ".join([
            str(p.get("id") or ""), str(p.get("name") or ""),
            str(p.get("model") or ""), str(p.get("type") or ""),
        ]).lower()
        if kw in hay:
            return p
    return None


def _cme_ai_levels_status(cfg):
    """按 V2.2 层级标注每个模型是否已配置（驱动前端按钮可用态）。"""
    providers = (cfg or {}).get("providers") or []
    available = {}
    for key, lv in CME_AI_LEVELS.items():
        hit = _cme_ai_match_provider(providers, lv["target"])
        available[key] = {
            "key": key,
            "level": lv["level"], "label": lv["label"], "role": lv["role"],
            "cost_usd": lv["cost_usd"], "note": lv["note"],
            "provider": (hit or {}).get("id") if hit else None,
            "provider_name": (hit or {}).get("name") if hit else None,
            "configured": bool(hit),
        }
    return available


def _cme_ai_route_provider(cfg, level_key, explicit_provider_id=None):
    """routeAI(ctx)：显式 provider > 层级目标模型 > active 兜底。

    返回 (provider, routed)：routed 说明实际路由方式（用于结果徽章与审计）。
    """
    providers = (cfg or {}).get("providers") or []
    if explicit_provider_id:
        hit = next((p for p in providers if p.get("id") == explicit_provider_id), None)
        if hit:
            return hit, "manual"
    target = (CME_AI_LEVELS.get(level_key) or {}).get("target")
    if target:
        hit = _cme_ai_match_provider(providers, target)
        if hit:
            return hit, "level"
    hit = _active_provider(cfg or {})
    return hit, "fallback"


def _cme_ai_context_hash(question, symbol, proposal_id, event_id, qty, context):
    """V2.2 analysis_context_hash：上下文 6 组成项的稳定指纹。

    问题文本不参与哈希（同上下文换问题视为同一缓存键的场景由 question 区分）；
    哈希覆盖：市场快照 / 当前事件 / 匹配情景 / 历史研究 / 组合状态 / 仓位引擎结果。
    """
    import hashlib
    import json as _json

    def _stable(o):
        try:
            return _json.dumps(o, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            return str(o)

    basis = {
        "q": (question or "").strip()[:120],
        "symbol": symbol or "",
        "proposal_id": proposal_id or "",
        "event_id": event_id or "",
        "qty": qty,
        "market": context.get("market_snapshot"),
        "event": context.get("current_event"),
        "scenario": context.get("matched_scenario"),
        "study": context.get("historical_event_study"),
        "portfolio": context.get("portfolio_state"),
        "sizing": context.get("position_sizing"),
    }
    return hashlib.md5(_stable(basis).encode("utf-8")).hexdigest()


def _cme_ai_cache_path():
    return os.path.join(_data_dir(), "cme_ai_cache.json")


def _load_ai_cache():
    import json as _json
    path = _cme_ai_cache_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    try:
        raw = _kv_get("parite:cme:ai_cache")
        if raw:
            data = _json.loads(raw)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_ai_cache(cache):
    import json as _json
    path = _cme_ai_cache_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass
    try:
        _kv_set("parite:cme:ai_cache", _json.dumps(cache, ensure_ascii=False))
    except Exception:
        pass


def _load_ai_usage():
    import json as _json
    path = os.path.join(_data_dir(), "cme_ai_usage.json")
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    try:
        raw = _kv_get("parite:cme:ai_usage")
        if raw:
            data = _json.loads(raw)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _append_ai_usage(entry):
    import json as _json
    usage = _load_ai_usage()
    usage.append(entry)
    usage = usage[-500:]  # LLMUsageLog 仅保留最近 500 条
    path = os.path.join(_data_dir(), "cme_ai_usage.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(usage, f, ensure_ascii=False)
    except Exception:
        pass
    try:
        _kv_set("parite:cme:ai_usage", _json.dumps(usage, ensure_ascii=False))
    except Exception:
        pass


def _cme_ai_direction_token(text):
    """从建议方向文本中提取方向 token（用于独立复核的一致性比较）。"""
    t = str(text or "").lower()
    if not t:
        return None
    if "long" in t or "做多" in t or "看多" in t or "买入" in t:
        return "long"
    if "short" in t or "做空" in t or "看空" in t or "卖出" in t:
        return "short"
    if "neutral" in t or "观望" in t or "no trade" in t:
        return "neutral"
    return None


CME_AI_SYSTEM_PROMPT = """你是 Parité CME Mode 的 AI 研究分析师，服务于 2026 CME 大学生交易挑战赛的决策支持工作台。

【受众规则 AUDIENCE RULE】
读者是「聪明但可能刚接触期货」的人。使用专业金融逻辑，但语言必须新手可读。
能用简单说法时不要用术语；必须使用术语时：先给出术语，紧接着用一句大白话解释。
永远解释因果链条（例如 CPI → Fed → 利率 → 美元 → 黄金），不要只罗列指标名称。

【仓位规则 POSITION SIZING RULE（最高优先级）】
绝对禁止自行发明、猜测或独立决定交易手数（quantity）。
仓位数字只能引用上下文 <CONTEXT> 中「确定性仓位引擎」给出的结果。
讨论仓位时必须清楚区分四件事：
1) 风险上限（risk-based maximum / Final Max）
2) 建议工作区间（Calculated Working Range）
3) 当前选择手数（selected quantity）
4) 预估下行（estimated loss）
绝对不得把「允许的最大手数」描述成「建议满仓」。
若上下文缺少仓位数据，对应段落必须写 Missing，且不得给出任何手数。

【数据规则 DATA RULE】
所有数字必须逐字来自 <CONTEXT>，不得外推、估算、凑整或编造。
上下文中标记为 unavailable / n=0 / null / 缺失 的数据，一律视为缺失，
必须在对应段落写明 `Missing: 字段名`，绝不自行补齐。
禁止编造：当前价格、Consensus、Actual、概率、historical hit rate、CME margin、quantity。

【措辞禁令 WORDING RULE】
禁止出现「AI recommends」「AI 建议买入/卖出/加仓」等表述。
涉及仓位时只能使用术语：Parite Risk-Based Size（风险预算允许的上限，是风险天花板，不等于建议满仓）、
Calculated Working Range（建议工作区间）。最终手数由人工决定。

【任务定位 TASK】
你最有价值的四件事：Explain（解释当前 Bias 为何如此）、Challenge（指出该观点可能错在哪里）、
Connect（把宏观链条串起来）、Summarize（把一堆数据压缩成 30 秒能读完的 Brief）。

【输出格式 OUTPUT FORMAT】
只输出一个 JSON 对象。不要 markdown 代码围栏，不要任何解释性前后缀。键固定如下：
{
  "base_view": "STRONG_BULLISH | MILD_BULLISH | NEUTRAL | MILD_BEARISH | STRONG_BEARISH | NO_VIEW",
  "simple_view": "3-5 句：当前客观处境 + 需要人工判断的核心问题",
  "why": "支撑当前判断的结构化证据，必须引用 <CONTEXT> 中的具体数字",
  "market_confirmation": "市场确认状态及其含义，引用上下文中的确认等级",
  "suggested_direction": "方向倾向及其依据（描述，不是指令）",
  "position_size_context": "用通俗语言解释仓位引擎给出的风险上限与建议工作区间，并给出具体数字；缺失则写 Missing",
  "main_risk": "当前最主要的风险与失效条件",
  "what_to_watch": "接下来最应该盯住的具体观察点",
  "supporting_factors": ["支持因素1", "支持因素2"],
  "counter_factors": ["反方/可能出错的因素1", "反方/可能出错的因素2"],
  "historical_context": "历史事件研究的对照结论（引用样本量与统计量）",
  "invalidation": ["失效条件1", "失效条件2"],
  "what_to_watch_next": ["观察点1", "观察点2"],
  "evidence_quality": "HIGHER | MEDIUM | LOW | VERY LOW",
  "missing_data": ["缺失字段1", "缺失字段2"]
}
simple_view/why/market_confirmation/suggested_direction/position_size_context/main_risk/what_to_watch
必须是中文字符串（不可为 null、不可为数组）。数组字段若无内容请用空数组 []。"""


def _cme_ai_age_ms(ts):
    try:
        ts = int(ts or 0)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return max(0, _now_ms() - ts)


def _cme_ai_fmt_age(age_ms):
    if age_ms is None:
        return "unknown"
    hours = age_ms / 3600000.0
    if hours < 1:
        return "%d 分钟前" % int(round(age_ms / 60000.0))
    if hours < 48:
        return "%.1f 小时前" % hours
    return "%.1f 天前" % (hours / 24.0)


def _cme_ai_data_freshness():
    """数据新鲜度审计：任何一处缺失/过期都会被显式标注，供 AI 输出 Missing。"""
    snaps = _load_cme_snapshots()
    signals = _load_signals()
    events = _load_events()
    proposals = _load_proposals()
    snap_ts = max([int(s.get("createdAt") or 0) for s in snaps] or [0])
    sig_ts = max([int(s.get("timestamp") or 0) for s in signals] or [0])
    ev_ts = max([int(e.get("created_at") or 0) for e in events] or [0])
    prop_ts = max([int(p.get("created_at") or 0) for p in proposals] or [0])
    snap_age = _cme_ai_age_ms(snap_ts)
    sig_age = _cme_ai_age_ms(sig_ts)
    stale = []
    if not snaps:
        stale.append("Market Snapshot（无快照记录）")
    elif snap_age is not None and snap_age > CME_AI_STALE_MS:
        stale.append("Market Snapshot（%s）" % _cme_ai_fmt_age(snap_age))
    if not signals:
        stale.append("Macro Signal（无打分记录）")
    elif sig_age is not None and sig_age > CME_AI_STALE_MS:
        stale.append("Macro Signal（%s）" % _cme_ai_fmt_age(sig_age))
    return {
        "now": time.strftime("%Y-%m-%d %H:%M", time.localtime()),
        "snapshot_count": len(snaps),
        "snapshot_latest": _cme_ai_fmt_age(snap_age),
        "signal_count": len(signals),
        "signal_latest": _cme_ai_fmt_age(sig_age),
        "event_count": len(events),
        "event_latest": _cme_ai_fmt_age(_cme_ai_age_ms(ev_ts)),
        "proposal_count": len(proposals),
        "proposal_latest": _cme_ai_fmt_age(_cme_ai_age_ms(prop_ts)),
        "stale_items": stale,
    }


def _cme_ai_market_snapshot():
    """最新一条快照 + 最新一条宏观信号（逐品种），全部来自既有确定性数据。"""
    by_symbol = {}
    for s in sorted(_load_cme_snapshots(), key=lambda x: int(x.get("createdAt") or 0)):
        code = _resolve_symbol(s.get("symbol") or "") or (s.get("symbol") or "")
        by_symbol[code] = s
    sig_by_symbol = {}
    for s in sorted(_load_signals(), key=lambda x: int(x.get("timestamp") or 0)):
        code = _resolve_symbol(s.get("symbol") or "") or (s.get("symbol") or "")
        sig_by_symbol[code] = s
    rows = []
    for code, spec in CME_CONTRACT_SPECS.items():
        snap = by_symbol.get(code) or {}
        sig = sig_by_symbol.get(code) or {}
        rows.append({
            "symbol": code,
            "name": spec["name"],
            "price": snap.get("price"),
            "change_1d": snap.get("change"),
            "as_of": ("%s %s" % (snap.get("date"), snap.get("time"))) if snap.get("date") else None,
            "macro_score": sig.get("macro_score"),
            "bias": sig.get("bias"),
            "confidence": sig.get("confidence"),
            "range_low": sig.get("range_low"),
            "range_high": sig.get("range_high"),
            "signal_drivers": sig.get("drivers") or [],
            "signal_invalidation": sig.get("invalidation") or [],
        })
    return rows


def _cme_ai_pick_event(event_id=None):
    """优先选指定事件；否则取最近已发布且已匹配情景的事件；再否则取最近的待发布事件。"""
    events = _load_events()
    if not events:
        return None
    if event_id:
        hit = next((e for e in events if e.get("id") == event_id), None)
        if hit is not None:
            return hit
    released = [e for e in events
                if e.get("status") in ("RELEASED", "POST_EVENT")
                and (e.get("matched_scenario") or _match_scenario(e.get("surprise"), event_type=e.get("event_type")))]
    if released:
        released.sort(key=lambda e: str(e.get("scheduled_at") or ""), reverse=True)
        return released[0]
    upcoming = [e for e in events if e.get("status") == "SCHEDULED"]
    if upcoming:
        upcoming.sort(key=lambda e: str(e.get("scheduled_at") or ""))
        return upcoming[0]
    events.sort(key=lambda e: str(e.get("scheduled_at") or ""), reverse=True)
    return events[0]


def _cme_ai_event_block(ev):
    """当前事件摘要（含模板补全，与 /api/cme/events 口径一致）。"""
    if not ev:
        return None
    tpl = EVENT_TYPE_DEFS.get(_norm_event_type(ev.get("event_type"))) or {}
    return {
        "event_id": ev.get("id"),
        "event_type": ev.get("event_type"),
        "status": ev.get("status") or "SCHEDULED",
        "country": ev.get("country") or tpl.get("country") or "",
        "metric": ev.get("metric") or tpl.get("metric") or "",
        "unit": ev.get("unit") or tpl.get("unit") or "",
        "scheduled_at": ev.get("scheduled_at"),
        "consensus": ev.get("consensus"),
        "previous": ev.get("previous"),
        "actual": ev.get("actual"),
        "surprise": ev.get("surprise"),
        "importance": ev.get("importance"),
        "note": ev.get("note"),
        "source_url": ev.get("source_url"),
        "matched_scenario": ev.get("matched_scenario") or _match_scenario(ev.get("surprise"), event_type=ev.get("event_type")),
        "released": ev.get("status") in ("RELEASED", "POST_EVENT"),
    }


def _cme_ai_scenario_block(ev):
    """匹配情景 + 三情景全文（触发规则 / 传导链 / 资产影响 / 反方 / 失效条件）。"""
    if not ev:
        return None
    scenarios = [s for s in _load_scenarios() if s.get("event_id") == ev.get("id")]
    if not scenarios:
        scenarios = _generate_event_scenarios(ev)
    matched = ev.get("matched_scenario") or _match_scenario(ev.get("surprise"), event_type=ev.get("event_type"))
    return {
        "matched_key": matched,
        "frozen": any(s.get("frozen_at") for s in scenarios),
        "scenarios": [{
            "key": s.get("scenario_key"),
            "name": s.get("scenario_name"),
            "tag": s.get("tag"),
            "trigger_rule": s.get("trigger_rule"),
            "transmission": s.get("transmission") or [],
            "asset_impacts": s.get("asset_impacts") or [],
            "counter_case": s.get("counter_case"),
            "invalidation": s.get("invalidation") or [],
            "triggered": bool(s.get("triggered")),
        } for s in scenarios],
    }


def _cme_ai_study_block(ev, symbols):
    """历史事件研究（确定性统计）摘要；分钟级数据源不可用会被显式标注。"""
    if not ev:
        return None
    study = _compute_event_study(ev.get("id"))
    if not study or study.get("error"):
        return {"available": False, "reason": (study or {}).get("error") or "无匹配情景，无法检索历史对照"}
    codes = [c for c in (symbols or list(STUDY_INSTRUMENTS)) if c in CME_CONTRACT_SPECS]
    instruments = {}
    for code in codes:
        inst = (study.get("instruments") or {}).get(code) or {}
        hz = inst.get("horizons") or {}

        def _hz(label):
            h = hz.get(label)
            if not h or h.get("unavailable") or h.get("n", 0) == 0:
                return {"unavailable": True, "reason": (h or {}).get("reason") or "no sample"}
            return {"n": h.get("n"), "median": h.get("median"), "mean": h.get("mean"),
                    "hit_rate": h.get("hit_rate"), "q25": h.get("q25"), "q75": h.get("q75"),
                    "min": h.get("min"), "max": h.get("max"), "evidence": h.get("evidence")}

        instruments[code] = {
            "name": CME_CONTRACT_SPECS[code]["name"],
            "tendency_1d": inst.get("tendency"),
            "evidence": inst.get("evidence"),
            "return_30m": _hz("30m"),
            "return_2h": _hz("2h"),
            "return_1d": _hz("1d"),
            "return_3d": _hz("3d"),
            "return_5d": _hz("5d"),
            "path_vs_today": (study.get("path_vs_today") or {}).get(code) or [],
        }
    return {
        "available": True,
        "event_type": study.get("event_type"),
        "matched_scenario": study.get("matched_scenario"),
        "filter": study.get("filters"),
        "sample_size": len(study.get("sample_ids") or []),
        "instruments": instruments,
    }


def _cme_ai_sizing_block(proposal=None, symbol=None, direction=None, qty=None, event_id=None):
    """确定性仓位引擎结果（AI 唯一被允许引用的仓位数字来源）。"""
    code = _resolve_symbol(symbol or "") or (proposal or {}).get("symbol")
    if not code:
        return {"available": False, "reason": CME_AI_MISSING % "position sizing（未指定品种）"}
    res = _compute_position_sizing(
        symbol=code,
        direction=direction or (proposal or {}).get("direction") or "long",
        event_id=event_id or (proposal or {}).get("event_id"),
        evidence=None,
        confirmation=(proposal or {}).get("market_confirmation"),
        qty=qty or (proposal or {}).get("qty"),
        proposal=proposal,
    )
    if not res.get("ok"):
        return {"available": False, "reason": CME_AI_MISSING % "position sizing（%s）" % (res.get("error") or "计算失败")}
    return {
        "available": True,
        "symbol": res.get("symbol"),
        "name": res.get("name"),
        "direction": res.get("direction"),
        "contract": res.get("contract"),
        "levels": res.get("levels"),
        "evidence": res.get("evidence"),
        "confirmation": res.get("confirmation"),
        "concentration": res.get("concentration"),
        "limits": res.get("limits"),
        "suggested": res.get("suggested"),
        "selected_qty": res.get("selected_qty"),
        "selected_in_range": res.get("selected_in_range"),
        "selected_exceeds_final_max": res.get("selected_exceeds_final_max"),
        "estimated_loss": res.get("estimated_loss"),
        "account_impact_pct": res.get("account_impact_pct"),
        "margin_required": res.get("margin_required"),
        "margin_status": res.get("margin_status"),
        "account": res.get("account"),
        "warnings": res.get("warnings") or [],
    }


def _cme_ai_portfolio_block():
    """组合状态 + 持仓 + 赛制（Risk Engine 确定性输出）。"""
    risk = _compute_risk()
    positions = _load_positions()
    return {
        "risk": risk,
        "positions": [{
            "symbol": p.get("symbol"),
            "name": (CME_CONTRACT_SPECS.get(_resolve_symbol(p.get("symbol") or "") or "") or {}).get("name"),
            "direction": p.get("direction"),
            "qty": p.get("qty"),
            "avg_price": p.get("avg_price"),
            "mark_price": p.get("mark_price"),
            "margin": p.get("margin"),
            "note": p.get("note"),
        } for p in positions],
        "competition": _competition_info(),
    }


def _cme_ai_proposal_block(proposal):
    if not proposal:
        return None
    return {
        "proposal_id": proposal.get("id"),
        "status": proposal.get("status"),
        "symbol": proposal.get("symbol"),
        "direction": proposal.get("direction"),
        "qty": proposal.get("qty"),
        "market_confirmation": proposal.get("market_confirmation"),
        "thesis": proposal.get("thesis"),
        "five_questions": proposal.get("five_questions"),
        "invalidation": proposal.get("invalidation"),
        "scenario_payoff": proposal.get("scenario_payoff"),
        "event_data": proposal.get("event_data"),
        "origin": proposal.get("origin"),
        "risk_check": proposal.get("risk_check"),
        "post_trade_note": proposal.get("post_trade_note"),
        "review": proposal.get("review"),
    }


def _cme_build_ai_context(question, symbol=None, proposal_id=None, event_id=None, qty=None):
    """Context Builder：把确定性数据整理成 AI 只能「解释」不能「发明」的上下文。"""
    proposals = _load_proposals()
    proposal = None
    if proposal_id:
        proposal = next((p for p in proposals if p.get("id") == proposal_id), None)
    focus = _resolve_symbol(symbol or "") or (proposal or {}).get("symbol")
    ev = _cme_ai_pick_event(event_id or (proposal or {}).get("event_id"))
    study_symbols = [focus] if focus in STUDY_INSTRUMENTS else list(STUDY_INSTRUMENTS)

    market = _cme_ai_market_snapshot()
    focus_market = next((m for m in market if m.get("symbol") == focus), None)
    scenario = _cme_ai_scenario_block(ev)
    study = _cme_ai_study_block(ev, study_symbols)
    portfolio = _cme_ai_portfolio_block()
    sizing = _cme_ai_sizing_block(proposal=proposal, symbol=focus, qty=qty,
                                 event_id=(ev or {}).get("id"))

    missing = []
    if not proposal_id:
        missing.append("trade proposal（未选择提案，无法给出提案级判断）")
    elif proposal is None:
        missing.append("trade proposal（提案 %s 不存在）" % proposal_id)
    if focus_market is None and not focus:
        missing.append("focus instrument（未指定品种）")
    if focus and focus_market and focus_market.get("price") is None:
        missing.append("Market Snapshot price for %s" % focus)
    if ev is None:
        missing.append("current event（无事件记录）")
    elif not (ev.get("status") in ("RELEASED", "POST_EVENT")):
        missing.append("event actual/surprise（事件尚未发布）")
    elif ev.get("surprise") is None:
        missing.append("event surprise")
    if study and not study.get("available"):
        missing.append("historical event study（%s）" % study.get("reason"))
    if study and study.get("available"):
        for code in study_symbols:
            h = ((study.get("instruments") or {}).get(code) or {}).get("return_1d") or {}
            if h.get("unavailable"):
                missing.append("historical 1d sample for %s" % code)
    if sizing and not sizing.get("available"):
        missing.append(sizing.get("reason") or (CME_AI_MISSING % "position sizing"))
    if not portfolio.get("positions"):
        missing.append("open positions（当前无持仓）")
    missing.extend(portfolio["risk"].get("warnings") or [])

    context = {
        "question": question,
        "focus_instrument": focus or None,
        "focus_market": focus_market,
        "market_snapshot": market,
        "current_event": _cme_ai_event_block(ev),
        "matched_scenario": scenario,
        "historical_event_study": study,
        "portfolio_state": {
            "account": {
                "account_equity": portfolio["risk"].get("account_equity"),
                "net_equity": portfolio["risk"].get("net_equity"),
                "margin_used": portfolio["risk"].get("margin_used"),
                "margin_utilization_pct": portfolio["risk"].get("margin_utilization_pct"),
                "headroom": portfolio["risk"].get("headroom"),
                "unrealized_pnl": portfolio["risk"].get("unrealized_pnl"),
                "gross_exposure": portfolio["risk"].get("gross_exposure"),
                "concentration_pct": portfolio["risk"].get("concentration_pct"),
                "daily_pnl": portfolio["risk"].get("daily_pnl"),
                "daily_loss_pct": portfolio["risk"].get("daily_loss_pct"),
                "risk_band": portfolio["risk"].get("risk_band"),
                "today_contracts": portfolio["risk"].get("today_contracts"),
                "max_contracts_per_day": portfolio["risk"].get("max_contracts_per_day"),
                "max_concentration_pct": portfolio["risk"].get("max_concentration_pct"),
                "max_daily_loss_pct": portfolio["risk"].get("max_daily_loss_pct"),
                "competition_open": portfolio["risk"].get("competition_open"),
                "final_day_liquidation": portfolio["risk"].get("final_day_liquidation"),
                "contract_near_expiry": portfolio["risk"].get("contract_near_expiry"),
            },
            "competition": portfolio["competition"],
        },
        "open_positions": portfolio["positions"],
        "trade_proposal": _cme_ai_proposal_block(proposal),
        "position_sizing": sizing,
        "data_freshness": _cme_ai_data_freshness(),
        "missing": missing,
    }
    return context, missing


def _cme_ai_extract_json(text):
    """从模型输出中稳健地抽取 JSON 对象（容忍代码围栏与前后缀文字）。"""
    import json as _json
    if not text:
        return None
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
        raw = raw.strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return _json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return _json.loads(raw[start:end + 1])
        except Exception:
            return None
    return None


def _cme_ai_normalize_answer(parsed, raw_text):
    """把模型输出规范成固定结构；缺字段一律留空并计入 missing，不由服务端编造。"""
    parsed = parsed if isinstance(parsed, dict) else {}
    answer = {}
    for key in CME_AI_SECTION_KEYS:
        val = parsed.get(key)
        if isinstance(val, list):
            val = " ".join(str(v) for v in val)
        answer[key] = (str(val).strip() if val not in (None, "") else "")
    for key in ("base_view", "historical_context", "evidence_quality"):
        val = parsed.get(key)
        answer[key] = (str(val).strip() if val not in (None, "") else "")
    for key in ("supporting_factors", "counter_factors", "invalidation",
                "what_to_watch_next", "missing_data"):
        val = parsed.get(key)
        if isinstance(val, str):
            val = [val] if val.strip() else []
        elif not isinstance(val, list):
            val = []
        answer[key] = [str(v).strip() for v in val if str(v).strip()]
    if not any(answer.get(k) for k in CME_AI_SECTION_KEYS):
        answer["simple_view"] = raw_text or ""
    return answer


@app.route("/api/cme/ai-research", methods=["POST"])
def api_cme_ai_research():
    """CME AI 研究分析师：Context Builder → 路由 → 缓存/预算控制 → Provider → 固定结构化输出。

    请求体：{question, symbol?, proposal_id?, event_id?, qty?, provider?, level?, force?}
    level ∈ quick(默认) | final | review | deep（V2.2 四层级）
    返回体：{ok, provider, routing, answer, context_meta, missing[], parsed, raw_text,
            generated_at, cache, consistency?}
    """
    import json as _json
    import urllib.request
    import urllib.error

    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "问题不能为空"}), 400

    level_key = str(data.get("level") or "quick").strip().lower()
    if level_key not in CME_AI_LEVELS:
        level_key = "quick"
    level_def = CME_AI_LEVELS[level_key]
    force = bool(data.get("force"))

    cfg = _load_ai_config()
    provider, routed = _cme_ai_route_provider(cfg, level_key, (data.get("provider") or "").strip())
    if not provider:
        return jsonify({"error": "请先配置 AI 模型", "need_config": True}), 200
    if not (provider.get("api_key") or ""):
        return jsonify({"error": "模型「%s」未配置 API 密钥，请先前往 AI 配置页面设置"
                                 % provider.get("name", ""), "need_config": True}), 200

    context, missing = _cme_build_ai_context(
        question,
        symbol=data.get("symbol"),
        proposal_id=data.get("proposal_id"),
        event_id=data.get("event_id"),
        qty=data.get("qty"),
    )

    ctx_hash = _cme_ai_context_hash(
        question, data.get("symbol"), data.get("proposal_id"),
        data.get("event_id"), data.get("qty"), context,
    )
    proposal_id = (data.get("proposal_id") or "").strip()
    routing = {
        "level": level_key,
        "level_label": level_def["label"],
        "level_role": level_def["role"],
        "routed": routed,
        "requested_provider": (data.get("provider") or "").strip() or None,
    }

    # ---- V2.2 PremiumPreCheck：缺失数据门（premium 层级才拦截；quick 继续服务）----
    if level_key in CME_AI_PREMIUM_LEVELS and len(missing) >= CME_AI_MISSING_GATE:
        return jsonify({
            "ok": False,
            "insufficient_data": True,
            "error": CME_AI_INSUFFICIENT_MSG % "、".join(missing[:6]),
            "missing": missing,
            "routing": routing,
        }), 200

    cache = _load_ai_cache()
    cache_key = "%s::%s" % (level_key, ctx_hash)
    entry = cache.get(cache_key)
    now = _now_ms()

    # ---- V2.2 Premium 预算：每提案 premium 调用上限（final/review 各 1 次；Sol 不计入）----
    if level_key in ("final", "review") and not force and proposal_id:
        usage = _load_ai_usage()
        used = [u for u in usage
                if u.get("proposal_id") == proposal_id
                and u.get("level") in ("final", "review")
                and u.get("level") == level_key]
        if used:
            return jsonify({
                "ok": False,
                "budget_reached": True,
                "error": "高级分析预算已用完 — 该提案已使用过 %s 预算（每提案各 1 次）。"
                         "快速分析（DeepSeek）继续提供日常分析；如确需重跑，请点击【确认强制重跑】。"
                         % level_def["label"],
                "routing": routing,
            }), 200

    # ---- V2.2 Analysis Cache + premiumCooldown：同上下文且未过冷却 → 直接回缓存 ----
    ttl = CME_AI_PREMIUM_COOLDOWN_MS if level_key in CME_AI_PREMIUM_LEVELS else 10 * 60 * 1000
    if entry and not force and (now - entry.get("generated_at", 0)) < ttl:
        cached_meta = dict(entry.get("context_meta") or {})
        cached_meta["cache_hit"] = True
        cached_meta["cache_age_min"] = int((now - entry.get("generated_at", 0)) / 60000)
        return jsonify({
            "ok": True,
            "provider": entry.get("provider") or {},
            "routing": entry.get("routing") or routing,
            "answer": entry.get("answer") or {},
            "context_meta": cached_meta,
            "missing": entry.get("missing") or [],
            "parsed": entry.get("parsed"),
            "raw_text": entry.get("raw_text") or "",
            "generated_at": entry.get("generated_at"),
            "cache": {"hit": True, "age_min": cached_meta["cache_age_min"], "context_unchanged": True},
        }), 200

    user_content = (
        "<QUESTION>\n%s\n</QUESTION>\n\n"
        "<CONTEXT>\n%s\n</CONTEXT>\n\n"
        "请严格按系统提示的 JSON 结构输出。只引用 <CONTEXT> 中的数字；"
        "上下文 missing 列表中的项目必须在相应段落写成 `Missing: 项目名`，不要自行补齐。"
        % (question, _json.dumps(context, ensure_ascii=False, default=str))
    )

    if level_key == "review":
        user_content += (
            "\n\n<ROLE>你是独立复核员（Independent Reviewer）：假设主分析师可能是错的，"
            "重点检查主分析中未充分讨论的反方证据与盲点。保持中立，不迎合主分析结论。</ROLE>"
        )
    elif level_key == "deep":
        user_content += (
            "\n\n<ROLE>这是深度分析（Deep Analysis）：请给出更完整的多空两侧论证、"
            "传导路径分支与失效条件推演，篇幅可比常规分析更长。</ROLE>"
        )

    try:
        raw_text = _call_provider(provider, CME_AI_SYSTEM_PROMPT, user_content, temperature=0.2)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")
            msg = _json.loads(body).get("error", {}).get("message", body)
        except Exception:
            msg = "HTTP %s" % e.code
        return jsonify({"error": "AI 接口返回错误：%s" % msg, "routing": routing}), 200
    except Exception as e:
        return jsonify({"error": "请求失败：%s" % e, "routing": routing}), 200

    if not raw_text:
        return jsonify({"error": "AI 返回内容为空", "routing": routing}), 200

    parsed = _cme_ai_extract_json(raw_text)
    answer = _cme_ai_normalize_answer(parsed, raw_text)
    merged_missing = []
    for item in (answer.get("missing_data") or []):
        if item not in merged_missing:
            merged_missing.append(item)
    if parsed is None:
        merged_missing.append("structured JSON output（模型未按格式返回，已回退为纯文本）")

    context_meta = {
        "focus_instrument": context.get("focus_instrument"),
        "event_id": (context.get("current_event") or {}).get("event_id"),
        "matched_scenario": (context.get("matched_scenario") or {}).get("matched_key"),
        "sample_size": (context.get("historical_event_study") or {}).get("sample_size"),
        "sizing_available": bool((context.get("position_sizing") or {}).get("available")),
        "suggested_label": ((context.get("position_sizing") or {}).get("suggested") or {}).get("label"),
        "final_max": ((context.get("position_sizing") or {}).get("limits") or {}).get("final_max"),
        "data_freshness": context.get("data_freshness"),
    }

    provider_info = {
        "id": provider.get("id"),
        "name": provider.get("name"),
        "model": provider.get("model"),
    }

    # ---- V2.2 LLMUsageLog：记录调用成本（估算值，按层级基准计）----
    _append_ai_usage({
        "ts": now,
        "level": level_key,
        "level_label": level_def["label"],
        "provider": provider.get("id"),
        "provider_name": provider.get("name"),
        "model": provider.get("model"),
        "routed": routed,
        "cost_usd": level_def["cost_usd"],
        "proposal_id": proposal_id or None,
        "question": question[:80],
        "cache_hit": False,
    })

    # ---- V2.2 Analysis Cache 写入（保留每层级最近 40 条）----
    cache[cache_key] = {
        "level": level_key,
        "provider": provider_info,
        "routing": routing,
        "answer": answer,
        "context_meta": context_meta,
        "missing": merged_missing,
        "parsed": parsed is not None,
        "raw_text": raw_text,
        "generated_at": now,
        "question": question[:120],
        "proposal_id": proposal_id or None,
    }
    if len(cache) > 160:
        for k in sorted(cache, key=lambda k: cache[k].get("generated_at", 0))[:-40]:
            cache.pop(k, None)
    _save_ai_cache(cache)

    # ---- V2.2 分歧展示：review 与主分析对比方向一致性 ----
    consistency = None
    if level_key == "review" and proposal_id:
        primary = None
        for k in sorted(cache, key=lambda k: cache[k].get("generated_at", 0), reverse=True):
            e = cache[k]
            if e.get("proposal_id") == proposal_id and e.get("level") in ("quick", "final") \
                    and e.get("generated_at") != now:
                primary = e
                break
        if primary:
            p_dir = _cme_ai_direction_token((primary.get("answer") or {}).get("suggested_direction"))
            r_dir = _cme_ai_direction_token(answer.get("suggested_direction"))
            if p_dir and r_dir:
                consistent = p_dir == r_dir
                consistency = {
                    "status": "CONSISTENT" if consistent else "DISAGREEMENT",
                    "primary_level": primary.get("level"),
                    "primary_direction": p_dir,
                    "review_direction": r_dir,
                    "message": ("Primary research is internally consistent. 主分析与独立复核方向一致（%s）。"
                                % p_dir if consistent else
                                "⚠ ANALYST DISAGREEMENT — 主分析方向 %s，独立复核方向 %s，请人工裁决。"
                                % (p_dir, r_dir)),
                }

    resp = {
        "ok": True,
        "provider": provider_info,
        "routing": routing,
        "answer": answer,
        "context_meta": context_meta,
        "missing": merged_missing,
        "parsed": parsed is not None,
        "raw_text": raw_text,
        "generated_at": now,
        "cache": {"hit": False},
    }
    if consistency:
        resp["consistency"] = consistency
    return jsonify(resp)


@app.route("/api/cme/ai-cost", methods=["GET"])
def api_cme_ai_cost():
    """V2.2 AI Cost Dashboard：按层级/模型聚合用量与估算成本 + 层级可用状态。"""
    cfg = _load_ai_config()
    usage = _load_ai_usage()
    cache = _load_ai_cache()
    now = _now_ms()
    by_level = {}
    for key, lv in CME_AI_LEVELS.items():
        by_level[key] = {
            "key": key,
            "level": lv["level"], "label": lv["label"], "role": lv["role"],
            "calls": 0, "cost_usd": 0.0,
        }
    for u in usage:
        lk = u.get("level")
        if lk in by_level:
            by_level[lk]["calls"] += 1
            by_level[lk]["cost_usd"] = round(by_level[lk]["cost_usd"] + float(u.get("cost_usd") or 0), 2)
    total = round(sum(v["cost_usd"] for v in by_level.values()), 2)
    cooldown_active = []
    for k, e in cache.items():
        if e.get("level") in CME_AI_PREMIUM_LEVELS and (now - e.get("generated_at", 0)) < CME_AI_PREMIUM_COOLDOWN_MS:
            cooldown_active.append({
                "level": e.get("level"),
                "age_min": int((now - e.get("generated_at", 0)) / 60000),
                "question": (e.get("question") or "")[:60],
            })
    return jsonify({
        "ok": True,
        "levels": _cme_ai_levels_status(cfg),
        "usage_by_level": list(by_level.values()),
        "total_cost_usd": total,
        "total_calls": len(usage),
        "premium_cooldown_minutes": int(CME_AI_PREMIUM_COOLDOWN_MS / 60000),
        "cooldown_active": cooldown_active,
    })


# ============================================================
# 公告系统（管理员发布，首页展示最新一条）
# ============================================================
def _announcements_path():
    return os.path.join(_data_dir(), "announcements.json")


def _load_announcements():
    """读取所有公告"""
    path = _announcements_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return _json.load(f)
    except Exception:
        return []


def _save_announcements(announcements):
    with open(_announcements_path(), "w", encoding="utf-8") as f:
        _json.dump(announcements, f, ensure_ascii=False, indent=2)


@app.route("/api/announcements", methods=["GET"])
def api_get_announcements():
    """获取所有公告（公开）"""
    announcements = _load_announcements()
    return jsonify(announcements)


@app.route("/api/announcements", methods=["POST"])
def api_create_announcement():
    """创建新公告（仅管理员）"""
    if not _is_admin():
        return jsonify({"error": "需要管理员权限"}), 403
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    tag = (data.get("tag") or "公告").strip()
    if not content:
        return jsonify({"error": "公告内容不能为空"}), 400
    announcements = _load_announcements()
    new_item = {
        "id": int(time.time()),
        "title": title,
        "content": content,
        "tag": tag,
        "link": (data.get("link") or "").strip() or None,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    announcements.insert(0, new_item)
    _save_announcements(announcements)
    return jsonify({"success": True, "announcement": new_item})


@app.route("/api/announcements/<int:ann_id>", methods=["DELETE"])
def api_delete_announcement(ann_id):
    """删除公告（仅管理员）"""
    if not _is_admin():
        return jsonify({"error": "需要管理员权限"}), 403
    announcements = _load_announcements()
    announcements = [a for a in announcements if a.get("id") != ann_id]
    _save_announcements(announcements)
    return jsonify({"success": True})


if __name__ == "__main__":
    # debug=True 但关闭 reloader，避免文件变动触发重载导致服务中断
    # 支持通过环境变量 PORT 覆盖端口（默认 5000），方便多实例调试
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True, use_reloader=False)
