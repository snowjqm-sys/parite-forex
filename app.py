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
import time
import json as _json
import smtplib
import urllib.request
import urllib.error
from email.mime.text import MIMEText
from email.utils import formataddr
from flask import Flask, render_template, jsonify, request, abort, session, redirect, url_for

import data as DATA

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
    "proposals",     # 模块 C：交易计划
    "positions",     # 模块 D：持仓
    "journal",       # 模块 D：交易日志
    "risk_config",   # 模块 D：风控参数
)


def _cme_file_path(name):
    """返回 CME 模块数据文件路径。"""
    return os.path.join(_data_dir(), "cme_" + name + ".json")


def _cme_load(name, default):
    """通用读取：云端优先，本地 JSON 文件兜底（也承担首次上云的迁移）。"""
    if _kv_env():
        data = _kv_get("parite:cme:" + name)
        if data is not None:
            return data
    path = _cme_file_path(name)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        return data if data is not None else default
    except Exception:
        return default


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
def _load_events():
    return _cme_load("events", [])


def _save_events(events):
    _cme_save("events", events)


def _load_scenarios():
    return _cme_load("scenarios", [])


def _save_scenarios(scenarios):
    _cme_save("scenarios", scenarios)


# ---- 模块 C：Trade Planner ----
def _load_proposals():
    return _cme_load("proposals", [])


def _save_proposals(proposals):
    _cme_save("proposals", proposals)


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
        "account_equity": 100000.0,      # 初始权益（模拟账户）
        "max_contracts_per_day": 10,     # 每日最大交易次数（比赛规则）
        "max_concentration_pct": 40.0,   # 单品种集中度红线（%）
        "max_daily_loss_pct": 2.0,       # 单日亏损红线（%）
        "margin_pct": 10.0,              # 估算保证金比例（%）
    }
    return _cme_load("risk_config", default)


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
    events.sort(key=lambda e: e.get("scheduled_at", ""), reverse=True)
    return jsonify(events)


@app.route("/api/cme/events", methods=["POST"])
def api_cme_add_event():
    data = request.get_json(silent=True) or {}
    event_type = (data.get("event_type") or "").strip()
    scheduled_at = (data.get("scheduled_at") or "").strip()
    if not event_type or not scheduled_at:
        return jsonify({"error": "event_type 和 scheduled_at 不能为空"}), 400
    ev = {
        "id": _new_id(),
        "event_type": event_type,
        "country": (data.get("country") or "").strip(),
        "scheduled_at": scheduled_at,
        "consensus": data.get("consensus"),
        "previous": data.get("previous"),
        "actual": data.get("actual"),
        "surprise": data.get("surprise"),
        "importance": data.get("importance") or "medium",
        "source_url": (data.get("source_url") or "").strip(),
        "note": (data.get("note") or "").strip(),
        "created_at": _now_ms(),
    }
    events = _load_events()
    events.append(ev)
    _save_events(events)
    return jsonify({"success": True, "event": ev})


@app.route("/api/cme/events/<event_id>", methods=["DELETE"])
def api_cme_delete_event(event_id):
    events = _load_events()
    events = [e for e in events if e.get("id") != event_id]
    _save_events(events)
    return jsonify({"success": True})


@app.route("/api/cme/events/<event_id>", methods=["PATCH"])
def api_cme_update_event(event_id):
    """事件落地后更新 actual，自动计算 surprise。"""
    data = request.get_json(silent=True) or {}
    events = _load_events()
    for ev in events:
        if ev.get("id") == event_id:
            if "actual" in data:
                ev["actual"] = data["actual"]
                if ev.get("consensus") is not None and data["actual"] is not None:
                    try:
                        ev["surprise"] = float(data["actual"]) - float(ev["consensus"])
                    except (TypeError, ValueError):
                        ev["surprise"] = None
            if "note" in data:
                ev["note"] = data["note"]
            _save_events(events)
            return jsonify({"success": True, "event": ev})
    return jsonify({"error": "事件不存在"}), 404


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
    """返回该事件的历史事件研究统计（若有）。"""
    scenarios = [s for s in _load_scenarios() if s.get("event_id") == event_id]
    studies = [s.get("historical_stats") for s in scenarios if s.get("historical_stats")]
    return jsonify({"event_id": event_id, "studies": studies})


# ============================================================
# API：模块 C —— Trade Planner（仅 proposal，人工 approve）
# ============================================================
@app.route("/api/cme/proposals", methods=["GET"])
def api_cme_get_proposals():
    proposals = _load_proposals()
    proposals.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    return jsonify(proposals)


@app.route("/api/cme/proposals", methods=["POST"])
def api_cme_add_proposal():
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip()
    direction = (data.get("direction") or "").strip()
    thesis = (data.get("thesis") or "").strip()
    if not symbol or not direction:
        return jsonify({"error": "symbol 和 direction 不能为空"}), 400
    proposal = {
        "id": _new_id(),
        "created_at": _now_ms(),
        "symbol": symbol,
        "direction": direction,
        "thesis": thesis,
        "entry_condition": (data.get("entry_condition") or "").strip(),
        "size_hint": data.get("size_hint"),
        "stop_rule": (data.get("stop_rule") or "").strip(),
        "horizon": (data.get("horizon") or "").strip(),
        "confidence": data.get("confidence"),
        "owner": (data.get("owner") or "").strip(),
        "status": "pending",
        "post_trade_note": "",
    }
    proposals = _load_proposals()
    proposals.append(proposal)
    _save_proposals(proposals)
    return jsonify({"success": True, "proposal": proposal})


@app.route("/api/cme/proposals/<proposal_id>/status", methods=["PATCH"])
def api_cme_update_proposal_status(proposal_id):
    """人工 approve / reject（绝不能自动下单）。"""
    data = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "").strip()
    if new_status not in ("pending", "approved", "rejected"):
        return jsonify({"error": "status 必须是 pending/approved/rejected"}), 400
    proposals = _load_proposals()
    for p in proposals:
        if p.get("id") == proposal_id:
            p["status"] = new_status
            if "post_trade_note" in data:
                p["post_trade_note"] = data["post_trade_note"]
            _save_proposals(proposals)
            return jsonify({"success": True, "proposal": p})
    return jsonify({"error": "proposal 不存在"}), 404


@app.route("/api/cme/proposals/<proposal_id>", methods=["DELETE"])
def api_cme_delete_proposal(proposal_id):
    proposals = _load_proposals()
    proposals = [p for p in proposals if p.get("id") != proposal_id]
    _save_proposals(proposals)
    return jsonify({"success": True})


# ============================================================
# API：模块 D —— Risk Engine + 赛制运营
# ============================================================
def _compute_risk():
    """汇总组合风险：权益、保证金、盈亏、集中度、drawdown 等。"""
    cfg = _load_risk_config()
    positions = _load_positions()
    equity = float(cfg.get("account_equity", 100000.0))
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
    if gross_exposure > 0:
        conc = round(max((abs(float(p.get("qty", 0)) * float(p.get("mark_price", 0) or 0)) / gross_exposure * 100.0)
                         for p in positions) if positions else 0.0, 2)
    # 当日交易次数（用 journal 中今天的记录数估算）
    today = time.strftime("%Y-%m-%d", time.localtime())
    today_contracts = sum(1 for j in _load_journal() if (j.get("entry_time") or "").startswith(today))
    return {
        "account_equity": equity,
        "net_equity": round(net_equity, 2),
        "margin_used": round(margin_used, 2),
        "margin_utilization_pct": margin_util,
        "unrealized_pnl": round(unrealized, 2),
        "gross_exposure": round(gross_exposure, 2),
        "concentration_pct": conc,
        "today_contracts": today_contracts,
        "max_contracts_per_day": cfg.get("max_contracts_per_day", 10),
        "max_concentration_pct": cfg.get("max_concentration_pct", 40.0),
        "max_daily_loss_pct": cfg.get("max_daily_loss_pct", 2.0),
        "warnings": [],
    }


@app.route("/api/cme/risk", methods=["GET"])
def api_cme_risk():
    risk = _compute_risk()
    cfg = _load_risk_config()
    warnings = []
    if risk["margin_utilization_pct"] > 80:
        warnings.append("保证金利用率超过 80%，注意风险")
    if risk["concentration_pct"] > cfg.get("max_concentration_pct", 40.0):
        warnings.append("单品种集中度超过红线 %.0f%%" % cfg.get("max_concentration_pct", 40.0))
    if risk["today_contracts"] >= risk["max_contracts_per_day"]:
        warnings.append("今日交易次数已达上限 %d/%d" % (risk["today_contracts"], risk["max_contracts_per_day"]))
    risk["warnings"] = warnings
    return jsonify(risk)


@app.route("/api/cme/risk-config", methods=["GET"])
def api_cme_get_risk_config():
    return jsonify(_load_risk_config())


@app.route("/api/cme/risk-config", methods=["POST"])
def api_cme_update_risk_config():
    data = request.get_json(silent=True) or {}
    cfg = _load_risk_config()
    for key in ("account_equity", "max_contracts_per_day", "max_concentration_pct",
                "max_daily_loss_pct", "margin_pct"):
        if key in data and data[key] is not None:
            cfg[key] = data[key]
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
    with urllib.request.urlopen(req, timeout=60) as resp:
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
    with urllib.request.urlopen(req, timeout=60) as resp:
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
