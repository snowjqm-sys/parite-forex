# Parite · 多货币研究平台

一个基于 Flask 的学术化多货币研究平台，覆盖日元、人民币、欧元、英镑、澳元、瑞郎、美元七大货币的汇率驱动因素、历史走势、利差分析与实时数据。

## 功能模块

| 页面 | 内容 |
|------|------|
| **总览** | 市场快照、货币研究栏目入口、快速导航 |
| **外汇基础** | 利率平价、套息交易、购买力平价、不可能三角等 10 个核心概念（可展开，含公式与实例） |
| **货币研究** | 7 个货币独立页面：历史走势、利差对比、驱动因素详解、自由思考、实时汇率小窗 |
| **对比思考** | 多货币归一化对比、利差-汇率 OLS 回归分析、17 个深度问题与参考分析 |
| **数据探索** | 交互式图表、利率数据表、官方数据来源、实时汇率查询 |

## 货币栏目

| 货币 | 货币对 | 类别 | 核心分析维度 |
|------|--------|------|-------------|
| 日元 JPY | USD/JPY | 融资货币 | 美日利差 |
| 人民币 CNY | USD/CNY | 管理浮动 | 中美利差 |
| 欧元 EUR | EUR/USD | 自由浮动 | 欧美利差 |
| 英镑 GBP | GBP/USD | 自由浮动 | 英美利差 |
| 澳元 AUD | AUD/USD | 商品货币 | 美澳利差 |
| 瑞郎 CHF | USD/CHF | 避险货币 | 美瑞利差 |
| 美元 USD | DXY | 储备货币 | 美国利率与利差 |

每个货币页面底部均有实时汇率小窗，展示该货币对关联货币的实时汇率（通过欧洲央行 Frankfurter API 获取）。

## 运行方法

### 方式 A：双击启动脚本（推荐）

1. 双击 `run.bat` 启动网站
2. 浏览器打开 `http://127.0.0.1:5000`

### 方式 B：命令行启动

```bash
cd "C:\Users\snowj\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a73eba14b017102fbc7aad4\forex_website"
pip install flask
python app.py
```

访问 **http://127.0.0.1:5000**

## 分享给他人

### 第 1 步：启动网站

双击 `run.bat`（保持窗口打开）

### 第 2 步：创建公网链接

双击 `share.bat`，等待数秒后会出现类似以下的公网地址：

```
https://xxx-xxx-xxx-xxx.trycloudflare.com
```

将此链接分享给他人即可访问。关闭 share.bat 窗口即停止分享。

> 注意：Cloudflare 快速隧道无需注册账号，但无运行时间保证，适合临时分享。链接每次重启会变化。

## 项目结构

```
forex_website/
├── app.py              # Flask 主应用（动态路由 + API + 实时汇率代理）
├── data.py             # 多货币数据、基础概念、对比思考参考分析
├── requirements.txt    # 依赖清单
├── run.bat             # 启动脚本
├── share.bat           # 公网分享脚本
├── cloudflared.exe     # Cloudflare 隧道工具
├── README.md           # 本说明文件
├── static/
│   └── css/
│       └── style.css   # 深色主题样式表
└── templates/
    ├── base.html       # 基础模板（Parite 品牌、导航、页脚）
    ├── index.html      # 市场总览
    ├── basics.html     # 外汇基础概念
    ├── currency.html   # 货币研究共享模板（动态渲染所有货币）
    ├── comparison.html # 对比与自由思考
    └── explorer.html   # 数据探索
```

## API 端点

网站运行后，以下端点可被 Python 直接调用：

| 端点 | 说明 |
|------|------|
| `GET /api/snapshot` | 市场快照数据 |
| `GET /api/currencies` | 所有货币元信息 |
| `GET /api/currency/<code>/history` | 指定货币历史数据（code: jpy/cny/eur/gbp/aud/chf/usd） |
| `GET /api/rates` | 各国利率年度数据 |
| `GET /api/regression` | 利差-汇率 OLS 回归分析结果 |
| `GET /api/live/<base>` | 实时汇率（base 货币对关联货币，Frankfurter API） |
| `GET /api/live/<base>/history` | 近 30 天历史汇率 |

示例：

```python
import requests

# 获取日元历史数据
jpy = requests.get("http://127.0.0.1:5000/api/currency/jpy/history").json()

# 获取回归分析结果
reg = requests.get("http://127.0.0.1:5000/api/regression").json()
print(reg["jpy"]["regression"])  # {'intercept': ..., 'slope': ..., 'r_squared': ...}

# 获取实时汇率
live = requests.get("http://127.0.0.1:5000/api/live/JPY").json()
print(live["rates"])  # {'USD': 0.0063, 'EUR': 0.0057, ...}
```

## 数据来源

所有数据均来自官方权威源：

| 数据 | 来源 |
|------|------|
| USD/JPY、USD/CNY 年度均值 | 美联储 G.5A / FRED AEXJPUS、AEXCHUS |
| 当前汇率快照 | 美联储 H.10（2026-07-31） |
| 美国联邦基金利率 | 美联储 H.15 / FRED RIFSPFFNA |
| 日本隔夜拆借利率 | OECD MEI / FRED IRSTCI01JPM156N |
| EUR/GBP/AUD/CHF 数据 | 欧洲央行 / FRED |
| 实时汇率 | 欧洲央行 Frankfurter API（frankfurter.app） |
| 中国 LPR、中间价 | 中国人民银行 (pbc.gov.cn) |

## 常见问题

**Q: 报错 "No module named flask"**
A: 执行 `pip install flask`。

**Q: 端口 5000 被占用**
A: 修改 `app.py` 最后一行的 `port=5000` 为其他端口（如 8080）。

**Q: 图表不显示**
A: 需要联网加载 Plotly.js（CDN）。

**Q: 实时汇率加载失败**
A: Frankfurter API 仅工作日更新，且需网络连接。失败时页面会显示错误提示。

**Q: 公网链接无法访问**
A: 确保 run.bat 窗口保持打开，且 share.bat 显示隧道已连接。每次重启 share.bat 链接会变化。
