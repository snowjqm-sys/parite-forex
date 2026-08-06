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
    )


@app.route("/basics")
def basics():
    """外汇基础"""
    return render_template(
        "basics.html",
        active="basics",
        concepts=DATA.FOREX_CONCEPTS,
        learning_path=DATA.LEARNING_PATH,
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
        currency_nav=DATA.CURRENCY_NAV,
        exchanges_summary=DATA.FX_EXCHANGES_SUMMARY,
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
# 数据 API
# ============================================================
@app.route("/api/snapshot")
def api_snapshot():
    return jsonify(DATA.MARKET_SNAPSHOT)


@app.route("/api/currency/<code>/history")
def api_currency_history(code):
    """货币历史数据"""
    code = code.lower()
    cur = DATA.CURRENCIES.get(code)
    if not cur:
        return jsonify({"error": "unknown currency"}), 404
    return jsonify(cur["history"])


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
# AI 助手 API（配置管理 + 问答代理）
# ============================================================
def _ai_config_path():
    """返回 ai_config.json 的绝对路径"""
    return os.path.join(_data_dir(), "ai_config.json")


def _load_ai_config():
    """读取 AI 配置。

    优先级：环境变量 > ai_config.json > 默认值。
    Vercel serverless 上文件系统不持久化，通过环境变量注入密钥。
    """
    import json as _json
    default = {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
    }
    # 1. 先读本地文件（开发环境）
    path = _ai_config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            merged = dict(default)
            merged.update(data or {})
        except Exception:
            merged = dict(default)
    else:
        merged = dict(default)
    # 2. 环境变量覆盖（Vercel 生产环境）
    if os.environ.get("DEEPSEEK_API_KEY"):
        merged["api_key"] = os.environ["DEEPSEEK_API_KEY"]
    if os.environ.get("AI_API_KEY"):
        merged["api_key"] = os.environ["AI_API_KEY"]
    if os.environ.get("AI_BASE_URL"):
        merged["base_url"] = os.environ["AI_BASE_URL"]
    if os.environ.get("AI_MODEL"):
        merged["model"] = os.environ["AI_MODEL"]
    return merged


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
    """读取当前 AI 配置（api_key 脱敏显示）"""
    cfg = _load_ai_config()
    api_key = cfg.get("api_key", "") or ""
    # 脱敏处理：仅保留前4位和后4位，中间用星号代替
    if len(api_key) > 8:
        masked = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
    elif api_key:
        masked = "*" * len(api_key)
    else:
        masked = ""
    return jsonify({
        "base_url": cfg.get("base_url", ""),
        "api_key": masked,
        "model": cfg.get("model", ""),
        "has_key": bool(api_key),
    })


@app.route("/api/ai/config", methods=["POST"])
def api_save_ai_config():
    """保存 AI 配置到 ai_config.json（需要管理员权限）"""
    # 管理员密码已设置时，必须登录才能修改
    cfg = _load_admin_config()
    if cfg.get("admin_password") and not _is_admin():
        return jsonify({"error": "需要管理员权限，请先登录", "need_login": True}), 403

    data = request.get_json(silent=True) or {}
    base_url = (data.get("base_url") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    model = (data.get("model") or "").strip()

    if not base_url or not model:
        return jsonify({"error": "API 地址和模型名称不能为空"}), 400

    # 如果 api_key 全部为星号或为空，则保留原密钥
    existing = _load_ai_config()
    if api_key and set(api_key) == {"*"}:
        api_key = existing.get("api_key", "")
    elif not api_key:
        api_key = existing.get("api_key", "")

    cfg = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }
    try:
        with open(_ai_config_path(), "w", encoding="utf-8") as f:
            _json.dump(cfg, f, ensure_ascii=False, indent=2)
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


@app.route("/api/ai/ask", methods=["POST"])
def api_ai_ask():
    """AI 问答代理：调用 OpenAI 兼容的 /chat/completions 接口"""
    import json as _json
    import urllib.request
    import urllib.error

    cfg = _load_ai_config()
    api_key = cfg.get("api_key", "")
    if not api_key:
        return jsonify({"error": "请先配置AI API密钥", "need_config": True}), 200

    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    context = (data.get("context") or "").strip()

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

    base_url = cfg.get("base_url", "").rstrip("/")
    model = cfg.get("model", "deepseek-chat")
    url = f"{base_url}/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
    }

    try:
        req = urllib.request.Request(
            url,
            data=_json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
        answer = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
