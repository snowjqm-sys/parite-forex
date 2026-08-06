# -*- coding: utf-8 -*-
"""
Parité · 多货币研究平台 — 数据与内容模块

数据来源（官方权威）：
  - USD/JPY、USD/CNY 年度均值：美联储 G.5A / FRED AEXJPUS、AEXCHUS
  - 当前汇率快照：美联储 H.10（2026-08-03 发布，截至 2026-07-31）
  - 美国联邦基金利率：美联储 H.15 / FRED RIFSPFFNA
  - 日本隔夜拆借利率：OECD MEI / FRED IRSTCI01JPM156N
  - EUR/GBP/AUD/CHF 年度均值：欧洲央行 / FRED（DEXUSEU、DEXUSUK、DEXUSAL、DEXSZUS）
  - 实时汇率：欧洲央行 Frankfurter API（frankfurter.app，免费无需密钥）

数据更新：2026-08-05
"""

# ============================================================
# 市场快照（美联储 H.10，2026-07-31）
# ============================================================
MARKET_SNAPSHOT = {
    "as_of": "2026-08-05",
    "source": "美联储 H.10 / H.15 / ECB",
    "data_items": [
        {"pair": "USD/JPY", "value": "159.16", "trend": "干预后回落", "note": "7/29=163.86 → 7/31=159.16（美日联合干预）"},
        {"pair": "USD/CNY", "value": "6.7509", "trend": "人民币升值", "note": "2023年2月以来最强"},
        {"pair": "EUR/USD", "value": "1.0912", "trend": "欧元偏强", "note": "ECB 参考汇率"},
        {"pair": "GBP/USD", "value": "1.3008", "trend": "英镑走强", "note": "ECB 参考汇率"},
        {"pair": "AUD/USD", "value": "0.6591", "trend": "震荡", "note": "ECB 参考汇率"},
        {"pair": "USD/CHF", "value": "0.8703", "trend": "瑞郎强势", "note": "避险需求支撑"},
        {"pair": "美联邦基金利率", "value": "3.63%", "trend": "降息周期", "note": "2026-07（H.15）"},
        {"pair": "美日利差", "value": "约 280 bp", "trend": "仍处高位", "note": "3.63% - 0.84%"},
    ],
}

# ============================================================
# 利率数据（年度均值）
# 美国：联邦基金有效利率（美联储 H.15）
# 日本：BOJ 政策利率（OECD）
# 中国：1 年期 LPR（PBOC）
# 欧元区：ECB 主要再融资利率
# 英国：BOE 基准利率
# 澳大利亚：RBA 现金利率
# 瑞士：SNB 政策利率
# ============================================================
INTEREST_RATES = [
    {"date": "2010", "us": 0.18, "jp": 0.10,  "cn": 5.56, "eu": 1.00, "gb": 0.50, "au": 4.35, "ch": 0.25},
    {"date": "2011", "us": 0.10, "jp": 0.05,  "cn": 6.06, "eu": 1.29, "gb": 0.50, "au": 4.36, "ch": 0.25},
    {"date": "2012", "us": 0.14, "jp": 0.05,  "cn": 6.00, "eu": 0.59, "gb": 0.50, "au": 3.55, "ch": 0.25},
    {"date": "2013", "us": 0.11, "jp": 0.05,  "cn": 5.81, "eu": 0.25, "gb": 0.50, "au": 2.75, "ch": 0.25},
    {"date": "2014", "us": 0.09, "jp": 0.05,  "cn": 5.56, "eu": 0.15, "gb": 0.50, "au": 2.50, "ch": 0.25},
    {"date": "2015", "us": 0.13, "jp": 0.05,  "cn": 4.56, "eu": 0.05, "gb": 0.50, "au": 2.10, "ch": -0.75},
    {"date": "2016", "us": 0.40, "jp": -0.10, "cn": 4.35, "eu": 0.00, "gb": 0.25, "au": 1.60, "ch": -0.75},
    {"date": "2017", "us": 1.00, "jp": -0.10, "cn": 4.35, "eu": 0.00, "gb": 0.25, "au": 1.50, "ch": -0.75},
    {"date": "2018", "us": 1.83, "jp": -0.10, "cn": 4.31, "eu": 0.00, "gb": 0.50, "au": 1.50, "ch": -0.75},
    {"date": "2019", "us": 2.16, "jp": -0.10, "cn": 4.15, "eu": 0.00, "gb": 0.75, "au": 0.75, "ch": -0.75},
    {"date": "2020", "us": 0.38, "jp": -0.10, "cn": 3.85, "eu": 0.00, "gb": 0.10, "au": 0.25, "ch": -0.75},
    {"date": "2021", "us": 0.08, "jp": -0.10, "cn": 3.80, "eu": 0.00, "gb": 0.10, "au": 0.10, "ch": -0.75},
    {"date": "2022", "us": 1.69, "jp": -0.10, "cn": 3.65, "eu": 0.69, "gb": 1.67, "au": 1.35, "ch": -0.25},
    {"date": "2023", "us": 5.03, "jp": -0.10, "cn": 3.45, "eu": 3.96, "gb": 5.04, "au": 4.11, "ch": 1.75},
    {"date": "2024", "us": 5.14, "jp": 0.10,  "cn": 3.10, "eu": 3.76, "gb": 5.02, "au": 4.21, "ch": 1.25},
    {"date": "2025", "us": 4.21, "jp": 0.50,  "cn": 3.00, "eu": 2.75, "gb": 4.25, "au": 3.60, "ch": 0.50},
    {"date": "2026", "us": 3.63, "jp": 0.84, "cn": 2.85, "eu": 2.15, "gb": 3.75, "au": 3.10, "ch": 0.25},
]

# ============================================================
# 多货币数据结构
# 每个货币：历史、驱动因素、自由思考问题、关联货币
# ============================================================
CURRENCIES = {
    "jpy": {
        "code": "JPY", "name": "日元", "name_en": "Japanese Yen",
        "pair": "USD/JPY", "pair_label": "美元兑日元",
        "region": "亚洲", "category": "融资货币",
        "current": {"rate": 159.16, "date": "2026-07-31", "source": "美联储 H.10"},
        "trend": "长期贬值", "trend_dir": "up",
        "rate_context": "美日利差", "rate_pair": ("us", "jp"),
        "correlations": ["USD", "EUR", "CHF", "KRW"],
        "intro": (
            "日元是全球第三大交易货币，因日本央行长期超宽松政策成为全球最大的融资货币。"
            "2021-2026年USD/JPY从109升至159，贬值幅度约46%，核心驱动是美日利差扩大至约280基点。"
            "2026年7月触及163.86（40年低点）后美日联合干预回落。"
            "理解日元需把握三组矛盾：低利率vs贬值压力、避险属性vs套息融资、干预意愿vs政策约束。"
        ),
        "history": [
            {"date": "2010", "rate": 87.78,  "event": "美联储 QE2 前夕，日元强势"},
            {"date": "2011", "rate": 79.70,  "event": "日本地震，日元创战后高点"},
            {"date": "2012", "rate": 79.82,  "event": "安倍经济学前夕"},
            {"date": "2013", "rate": 97.60,  "event": "黑田量质宽松启动，日元急贬"},
            {"date": "2014", "rate": 105.74, "event": "QQE 扩大"},
            {"date": "2015", "rate": 121.05, "event": "持续宽松，日元弱势"},
            {"date": "2016", "rate": 108.66, "event": "负利率实施"},
            {"date": "2017", "rate": 112.10, "event": "全球同步复苏"},
            {"date": "2018", "rate": 110.40, "event": "小幅震荡"},
            {"date": "2019", "rate": 109.02, "event": "贸易摩擦避险"},
            {"date": "2020", "rate": 106.78, "event": "疫情避险推升日元"},
            {"date": "2021", "rate": 109.84, "event": "美联储转鹰前夜"},
            {"date": "2022", "rate": 131.46, "event": "美联储激进加息，利差急剧扩大"},
            {"date": "2023", "rate": 140.50, "event": "利差维持，财务省多次干预"},
            {"date": "2024", "rate": 151.46, "event": "BOJ 结束负利率，加息极缓"},
            {"date": "2025", "rate": 149.57, "event": "美联储降息，日元小幅反弹"},
            {"date": "2026", "rate": 159.16, "event": "美日联合干预后回落（美联储 H.10，2026-07-31）"},
        ],
        "drivers": [
            {"title": "美日利差持续高位", "weight": "核心驱动", "mechanism": "美联储联邦基金利率3.63%，日本隔夜拆借0.84%，利差约280基点。巨大的利差使套息交易有利可图，资金持续从日元流向美元资产。利差演变：2021年仅18bp → 2023年达513bp峰值 → 2026-07收窄至约280bp，但仍处历史高位。利差是日元走势的最强预测变量。", "key_point": "只要利差维持高位，日元就持续承压。这是预判反转的首要指标。", "links": [{"text": "美联储 H.15 利率", "url": "https://www.federalreserve.gov/releases/h15/", "type": "official"}, {"text": "BOJ 政策利率", "url": "https://www.boj.or.jp/en/statistics/boj/other/cabs/index.htm", "type": "official"}, {"text": "美日利差走势", "url": "https://forex.10jqka.com.cn/quotes/", "type": "ths"}]},
            {"title": "日本央行政策与全球背离", "weight": "结构性因素", "mechanism": "2016-2023年BOJ坚持负利率与YCC，而全球央行2022-2023年激进加息。即使2024年结束负利率，加息也极缓慢（0→0.75%）。背后顾虑：日本国债占GDP约260%，加息大幅推升偿债成本；担心抑制脆弱复苏；通胀预期未稳固。", "key_point": "'不敢加息'是日元软弱的深层结构性原因，也是判断反转时点的关键。", "links": [{"text": "BOJ 货币政策声明", "url": "https://www.boj.or.jp/en/mopo/mpmsche_ol/index.htm", "type": "official"}, {"text": "日本内阁府财政", "url": "https://www.cao.go.jp/about/content/000589044.pdf", "type": "article"}]},
            {"title": "套息交易规模庞大", "weight": "放大器", "mechanism": "全球大量资金借入低息日元投资美元资产。据BIS和IMF估算，日元套息仓位达万亿美元级别。建立仓位时卖出日元→贬值；平仓时买入日元→急升，常形成踩踏。这解释了日元'缓贬急升'的不对称特征。", "key_point": "套息交易让贬值自我强化，但埋下急速反转隐患。", "links": [{"text": "BIS 季度回顾", "url": "https://www.bis.org/publ/qtrpdf/r_qt2403z.htm", "type": "article"}, {"text": "CFTC 持仓报告", "url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm", "type": "official"}]},
            {"title": "贸易条件恶化", "weight": "次要因素", "mechanism": "日本能源自给率仅约12%，高度依赖进口。日元贬值推高进口成本，导致持续贸易逆差（2022-2024年多个月份逆差），形成'贬值→逆差→再贬值'循环。与传统'贬值促出口'认知相反。", "key_point": "贸易逆差削弱日元基本面支撑，需结合能源价格综合判断。", "links": [{"text": "日本财务省贸易统计", "url": "https://www.mof.go.jp/english/policy/reference/trade_statistics/index.htm", "type": "official"}]},
            {"title": "美日联合干预的新变量", "weight": "近期事件", "mechanism": "2026年7月30-31日美日联合干预，USD/JPY从163.86回落至159.16，两天升值约4.7%。美国参与的政治信号表明'无序贬值'触及美方容忍底线。历史上美国直接参与干预极为罕见（上次是2011年福岛后G7行动）。", "key_point": "干预改变短期节奏但不改变利差这一根本驱动。", "links": [{"text": "美国财政部外汇报告", "url": "https://home.treasury.gov/policy-issues/international/exchange-rate-policies", "type": "official"}, {"text": "日本财务省干预", "url": "https://www.mof.go.jp/english/policy/international_policy/reference/fe_intervention/", "type": "official"}]},
            {"title": "避险属性减弱", "weight": "情境因素", "mechanism": "传统上日元被视为避险货币，但2022-2026年这一属性明显减弱：即使地缘冲突频发，日元仍持续贬值。原因：经常账户恶化削弱避险基础；套息规模过大掩盖避险买盘；BOJ超宽松政策使日元不再被视为安全港。", "key_point": "避险属性减弱是近年新现象，不能机械套用传统框架。", "links": [{"text": "BIS 避险货币研究", "url": "https://www.bis.org/publ/work1060.htm", "type": "article"}]},
        ],
        "questions": [
            "日元贬值是'日本问题'还是'美元问题'？如何用数据区分？",
            "若美日利差收窄至100bp，日元是否会反转？还需要什么条件？",
            "日本央行何时会大幅加息？触发因素可能是什么？",
            "美日联合干预的可持续性如何？是否只是一次性效果？",
            "日元'避险属性减弱'是暂时的还是结构性的？如何验证？",
        ],
    },
    "cny": {
        "code": "CNY", "name": "人民币", "name_en": "Chinese Yuan",
        "pair": "USD/CNY", "pair_label": "美元兑人民币",
        "region": "亚洲", "category": "管理浮动",
        "current": {"rate": 6.7509, "date": "2026-07-31", "source": "美联储 H.10"},
        "trend": "升值", "trend_dir": "down",
        "rate_context": "中美利差", "rate_pair": ("us", "cn"),
        "correlations": ["USD", "EUR", "JPY", "KRW", "AUD"],
        "intro": (
            "人民币实行有管理的浮动汇率制，是全球第五大交易货币。"
            "USD/CNY从2024年7.20降至2026-07的6.75，升值约6.3%。"
            "核心驱动是美元走弱（美联储降息）的被动升值，叠加经常账户顺差与央行中间价引导。"
            "关键分析视角：区分'主动升值'（基本面强）与'被动升值'（美元跌），决定升值可持续性。"
        ),
        "history": [
            {"date": "2010", "rate": 6.77, "event": "汇改后渐进升值期"},
            {"date": "2011", "rate": 6.46, "event": "持续升值"},
            {"date": "2012", "rate": 6.31, "event": "升值延续"},
            {"date": "2013", "rate": 6.15, "event": "阶段性升值高点附近"},
            {"date": "2014", "rate": 6.16, "event": "基本持平"},
            {"date": "2015", "rate": 6.28, "event": "811 汇改，贬值启动"},
            {"date": "2016", "rate": 6.64, "event": "贬值压力，资本流出"},
            {"date": "2017", "rate": 6.76, "event": "企稳"},
            {"date": "2018", "rate": 6.61, "event": "贸易摩擦前半段"},
            {"date": "2019", "rate": 6.91, "event": "破 7 压力"},
            {"date": "2020", "rate": 6.90, "event": "疫情冲击后企稳"},
            {"date": "2021", "rate": 6.45, "event": "出口强劲，人民币升值"},
            {"date": "2022", "rate": 6.73, "event": "美联储加息，美元走强"},
            {"date": "2023", "rate": 7.08, "event": "中美利差倒挂，贬值压力"},
            {"date": "2024", "rate": 7.20, "event": "美元强势，年内高点 7.30+"},
            {"date": "2025", "rate": 7.19, "event": "美联储降息后企稳"},
            {"date": "2026", "rate": 6.75, "event": "2023年2月以来最强（美联储 H.10，2026-07-31）"},
        ],
        "drivers": [
            {"title": "美元走弱（美联储降息）", "weight": "核心驱动", "mechanism": "美联储联邦基金利率从2023年峰值5.03%降至2026-07的3.63%，累计降息约140bp。美元指数走弱，人民币对美元被动升值。USD/CNY从2024年7.20降至2026-07的6.75，升值约6.3%。关键：要区分'美元跌'和'人民币涨'——用美元指数拆分主动与被动成分。", "key_point": "区分主动升值与被动升值是分析人民币的核心视角，决定升值可持续性。", "links": [{"text": "美联储 FOMC 声明", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "type": "official"}, {"text": "ICE 美元指数", "url": "https://www.theice.com/products/194/US-Dollar-Index-Futures", "type": "official"}, {"text": "美元指数走势", "url": "https://forex.10jqka.com.cn/quotes/", "type": "ths"}]},
            {"title": "经常账户顺差", "weight": "基本面支撑", "mechanism": "中国商品贸易持续顺差，2024年货物贸易顺差约8230亿美元（历史新高）。出口企业结汇形成人民币买盘，是汇率最坚实的长期支撑。经常账户顺差反映实体经济对人民币的需求，与资本账户短期波动不同，提供'压舱石'作用。", "key_point": "经常账户顺差是人民币不至于长期贬值的压舱石。", "links": [{"text": "SAFE 国际收支", "url": "https://www.safe.gov.cn/safe/zgggjzsjsj/index.html", "type": "official"}, {"text": "海关总署贸易统计", "url": "http://www.customs.gov.cn/", "type": "official"}]},
            {"title": "央行中间价引导与逆周期调节", "weight": "政策因素", "mechanism": "央行通过强中间价释放稳定/升值信号。2026年8月中间价持续强于市场预期。'逆周期因子'可在顺周期波动时平滑汇率。市场热议'换锚'：央行可能更强调CFETS一篮子货币指数稳定，而非紧盯USD/CNY双边汇率，意味着人民币对美元弹性上升。", "key_point": "央行态度是人民币短期方向的关键变量，中间价是观察政策意图的最直接窗口。", "links": [{"text": "PBOC 中间价公告", "url": "http://www.pbc.gov.cn/zhengcehuobisi/125207/125217/index.html", "type": "official"}, {"text": "外汇交易中心", "url": "https://www.chinamoney.com.cn/chinese/bkccpr/", "type": "official"}, {"text": "人民币中间价", "url": "https://forex.10jqka.com.cn/quotes/", "type": "ths"}]},
            {"title": "中美利差收窄预期", "weight": "资金流向", "mechanism": "美联储降息使中美利差收窄。2023年利差倒挂约158bp（美国5.03%-中国3.45%）→2026-07收窄至约78bp（美国3.63%-中国2.85%）。利差收窄使人民币资产相对吸引力上升，外资增配人民币债券和股票。但利差仍倒挂，资本流动具有双向波动特征。", "key_point": "利差收窄是升值催化剂，但需警惕资本流动的双向波动。", "links": [{"text": "PBOC LPR 公告", "url": "http://www.pbc.gov.cn/zhengcehuobisi/125207/index.html", "type": "official"}, {"text": "中美利差走势", "url": "https://forex.10jqka.com.cn/quotes/", "type": "ths"}]},
            {"title": "经济基本面与预期修复", "weight": "中期因素", "mechanism": "汇率最终反映经济基本面。关键因素：GDP增速与内需强度；房地产市场企稳；财政与货币政策力度；出口结构升级。若国内经济企稳、政策预期改善，升值可持续；反之则制约升值空间。", "key_point": "基本面是升值能否持续的决定因素，不能只看短期汇率数字。", "links": [{"text": "国家统计局", "url": "https://www.stats.gov.cn/", "type": "official"}, {"text": "PBOC 货币政策报告", "url": "http://www.pbc.gov.cn/zhengcehuobisi/125207/125227/index.html", "type": "official"}]},
            {"title": "人民币国际化与储备需求", "weight": "长期因素", "mechanism": "人民币国际化带来结构性需求：IMF SDR篮子中人民币权重约12.28%；跨境贸易人民币结算占比提升；CIPS业务量增长；双边货币互换网络扩大。这些带来长期结构性人民币买盘。", "key_point": "人民币国际化带来长期结构性需求，是汇率长期支撑因素。", "links": [{"text": "PBOC 人民币国际化报告", "url": "http://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html", "type": "official"}, {"text": "IMF SDR 篮子", "url": "https://www.imf.org/en/About/Factsheets/Sheets/2023/Special-drawing-rights-sdr", "type": "official"}]},
        ],
        "questions": [
            "人民币升值是'被动'还是'主动'？两种判断对政策含义有何不同？",
            "如何用美元指数拆分'美元因素'与'人民币因素'？",
            "央行'换锚'讨论意味着什么？对人民币弹性有何影响？",
            "人民币持续升值对出口企业、资产价格、货币政策各有什么影响？",
            "在岸-离岸价差能否作为升值可持续性的判断依据？",
        ],
    },
    "eur": {
        "code": "EUR", "name": "欧元", "name_en": "Euro",
        "pair": "EUR/USD", "pair_label": "欧元兑美元",
        "region": "欧洲", "category": "自由浮动",
        "current": {"rate": 1.0912, "date": "2026-08-04", "source": "欧洲央行"},
        "trend": "震荡偏强", "trend_dir": "up",
        "rate_context": "欧美利差", "rate_pair": ("eu", "us"),
        "correlations": ["USD", "GBP", "CHF", "JPY"],
        "intro": (
            "欧元是全球第二大交易货币，占外汇市场日均交易量约31%。"
            "EUR/USD从2022年0.95（与美元平价附近）回升至2026-08的1.09，反映欧美利差收窄与欧元区经济企稳。"
            "欧元走势核心看欧美央行政策分化与欧元区经济基本面。"
            "作为美元的'镜像货币'，欧元是观察美元周期的重要窗口。"
        ),
        "history": [
            {"date": "2010", "rate": 1.326, "event": "欧债危机前夕"},
            {"date": "2011", "rate": 1.392, "event": "欧债危机深化，先升后跌"},
            {"date": "2012", "rate": 1.284, "event": "德拉吉'whatever it takes'"},
            {"date": "2013", "rate": 1.328, "event": "企稳"},
            {"date": "2014", "rate": 1.328, "event": "ECB开启负利率讨论"},
            {"date": "2015", "rate": 1.110, "event": "ECB启动QE，欧元大跌"},
            {"date": "2016", "rate": 1.107, "event": "英国脱欧，欧元承压"},
            {"date": "2017", "rate": 1.130, "event": "欧元区复苏"},
            {"date": "2018", "rate": 1.181, "event": "ECB退出QE预期"},
            {"date": "2019", "rate": 1.120, "event": "贸易摩擦与增长放缓"},
            {"date": "2020", "rate": 1.142, "event": "疫情后复苏基金推动"},
            {"date": "2021", "rate": 1.183, "event": "欧元区强劲复苏"},
            {"date": "2022", "rate": 1.054, "event": "俄乌冲突、能源危机、与美元平价"},
            {"date": "2023", "rate": 1.081, "event": "ECB激进加息，欧元回升"},
            {"date": "2024", "rate": 1.082, "event": "ECB降息周期开启"},
            {"date": "2025", "rate": 1.085, "event": "欧美利差收窄"},
            {"date": "2026", "rate": 1.0912, "event": "ECB参考汇率（2026-08-04）"},
        ],
        "drivers": [
            {"title": "欧美央行政策分化", "weight": "核心驱动", "mechanism": "ECB主要再融资利率2.15%，美联储3.63%，欧美利差约-148bp（美国高于欧元区）。利差演变：2023年欧美利差倒挂达-107bp峰值 → 2026-07收窄至-148bp→实际上美联储降息使利差收窄。EUR/USD对欧美央行政策路径预期高度敏感。", "key_point": "欧美央行政策预期差是EUR/USD最核心的驱动变量。", "links": [{"text": "ECB 货币政策", "url": "https://www.ecb.europa.eu/mopo/html/index.en.html", "type": "official"}, {"text": "美联储 FOMC", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "type": "official"}, {"text": "欧美利差", "url": "https://forex.10jqka.com.cn/quotes/", "type": "ths"}]},
            {"title": "美元周期（镜像关系）", "weight": "结构性因素", "mechanism": "EUR/USD占美元指数（DXY）权重约57.6%，是美元的'镜像货币'。美元走强时欧元通常走弱，反之亦然。理解欧元必须同时理解美元周期。当美联储降息、美元走弱时，欧元被动走强——这与人民币被动升值逻辑类似。", "key_point": "欧元是美元周期的镜像，分析欧元先看美元。", "links": [{"text": "ICE 美元指数", "url": "https://www.theice.com/products/194/US-Dollar-Index-Futures", "type": "official"}]},
            {"title": "能源价格与贸易条件", "weight": "基本面", "mechanism": "2022年俄乌冲突引发能源危机，欧元区进口成本飙升，贸易条件恶化，欧元一度跌至与美元平价（0.995）。能源价格回落与多元化供应改善后，贸易条件修复支撑欧元回升。欧元区对进口能源的依赖是结构性脆弱点。", "key_point": "能源价格是欧元区贸易条件与欧元汇率的关键变量。", "links": [{"text": "Eurostat 能源统计", "url": "https://ec.europa.eu/eurostat/web/energy", "type": "official"}]},
            {"title": "欧元区经济增长与债务", "weight": "中期因素", "mechanism": "欧元区增长乏力、成员国债务分化（南北差距）是欧元的长期制约。意大利、希腊等高债务国与德国的利差反映分裂风险。任何关于欧元区稳定性的担忧都会压制欧元。复苏基金（NextGenerationEU）是强化财政一体化的关键进展。", "key_point": "欧元区政治财政一体化进程决定欧元的长期稳定性。", "links": [{"text": "ECB 经济公报", "url": "https://www.ecb.europa.eu/pub/economic-bulletin/html/index.en.html", "type": "official"}]},
            {"title": "避险与资本流动", "weight": "情境因素", "mechanism": "欧元在部分时期呈现避险属性（如美元流动性紧张时资金回流）。但欧元区内部结构使其避险属性弱于美元、瑞郎、日元。资本流动受欧美资产相对吸引力驱动。", "key_point": "欧元避险属性有限，更多反映欧美相对基本面。", "links": [{"text": "ECB 金融稳定评估", "url": "https://www.ecb.europa.eu/pub/fsr/html/index.en.html", "type": "official"}]},
        ],
        "questions": [
            "EUR/USD与美元指数的'镜像关系'在什么条件下会失效？",
            "欧美利差倒挂对欧元意味着什么？如何判断拐点？",
            "能源危机对欧元的冲击是暂时还是结构性？",
            "欧元区财政一体化进展如何影响欧元的长期地位？",
            "欧元能否挑战美元的全球储备货币地位？障碍是什么？",
        ],
    },
    "gbp": {
        "code": "GBP", "name": "英镑", "name_en": "British Pound",
        "pair": "GBP/USD", "pair_label": "英镑兑美元",
        "region": "欧洲", "category": "自由浮动",
        "current": {"rate": 1.3008, "date": "2026-08-04", "source": "欧洲央行"},
        "trend": "走强", "trend_dir": "up",
        "rate_context": "英美利差", "rate_pair": ("gb", "us"),
        "correlations": ["USD", "EUR", "AUD", "CAD"],
        "intro": (
            "英镑是全球第四大交易货币，伦敦是全球最大外汇交易中心。"
            "GBP/USD从2022年低点1.07（特拉斯危机）大幅回升至2026-08的1.30，反映英国央行高利率支撑与美元走弱。"
            "英镑走势核心看英美利差、英国经济基本面与脱欧后续影响。"
            "作为高息G7货币，英镑兼具避险与套息目标货币双重特征。"
        ),
        "history": [
            {"date": "2010", "rate": 1.646, "event": "危机后强势"},
            {"date": "2011", "rate": 1.605, "event": "欧债危机避险"},
            {"date": "2012", "rate": 1.586, "event": "震荡"},
            {"date": "2013", "rate": 1.567, "event": "卡尼上任BOE"},
            {"date": "2014", "rate": 1.649, "event": "苏格兰独立公投"},
            {"date": "2015", "rate": 1.529, "event": "大选与油价"},
            {"date": "2016", "rate": 1.351, "event": "脱欧公投，英镑闪崩"},
            {"date": "2017", "rate": 1.288, "event": "脱欧谈判启动"},
            {"date": "2018", "rate": 1.335, "event": "脱欧协议拉锯"},
            {"date": "2019", "rate": 1.277, "event": "约翰逊上台、硬脱欧担忧"},
            {"date": "2020", "rate": 1.283, "event": "疫情冲击、脱欧完成"},
            {"date": "2021", "rate": 1.367, "event": "解封后复苏"},
            {"date": "2022", "rate": 1.231, "event": "特拉斯减税危机、英镑闪崩至1.07"},
            {"date": "2023", "rate": 1.244, "event": "BOE高利率支撑"},
            {"date": "2024", "rate": 1.278, "event": "BOE开启降息"},
            {"date": "2025", "rate": 1.285, "event": "美元走弱推动"},
            {"date": "2026", "rate": 1.3008, "event": "ECB参考汇率（2026-08-04）"},
        ],
        "drivers": [
            {"title": "英美利差", "weight": "核心驱动", "mechanism": "BOE基准利率3.75%，美联储3.63%，英美利差约+12bp（英国略高）。2023年BOE激进加息至5.25%峰值支撑英镑。英镑对英美利差高度敏感，BOE相对鹰派立场是英镑走强的关键。", "key_point": "BOE相对美联储的鹰鸽程度是英镑短期方向的核心。", "links": [{"text": "BOE 货币政策", "url": "https://www.bankofengland.co.uk/monetary-policy", "type": "official"}, {"text": "英美利差", "url": "https://forex.10jqka.com.cn/quotes/", "type": "ths"}]},
            {"title": "脱欧长期影响", "weight": "结构性因素", "mechanism": "2016年脱欧公投后英镑累计贬值约15-20%，反映贸易关系重构、投资流入减少、金融业外迁风险。脱欧的长期成本仍在消化中，是英镑的结构性压制因素。任何英欧贸易摩擦重燃都会冲击英镑。", "key_point": "脱欧是英镑长期的结构性折扣因素。", "links": [{"text": "英国政府脱欧", "url": "https://www.gov.uk/government/publications/the-result-of-the-eu-referendum", "type": "official"}]},
            {"title": "美元周期", "weight": "镜像因素", "mechanism": "GBP/USD与EUR/USD类似，受美元周期驱动。美联储降息、美元走弱时英镑被动走强。需区分英镑自身强弱与美元因素——可用英镑贸易加权指数（BEI）判断。", "key_point": "区分英镑自身强弱与美元因素是分析关键。", "links": [{"text": "BOE 有效汇率", "url": "https://www.bankofengland.co.uk/statistics/effective-exchange-rates", "type": "official"}]},
            {"title": "英国经济与财政", "weight": "基本面", "mechanism": "英国通胀粘性、财政赤字、投资疲软是制约因素。2022年特拉斯减税危机暴露财政可持续性担忧，英镑单日暴跌。财政纪律与增长前景是英镑长期支撑。", "key_point": "财政可信度是英镑的信任锚，不可忽视。", "links": [{"text": "OBR 财政预测", "url": "https://obr.uk/", "type": "official"}]},
            {"title": "伦敦金融中心地位", "weight": "长期因素", "mechanism": "伦敦是全球最大外汇交易中心（日均交易占比约38%），金融业是英镑需求的重要来源。伦敦金融中心地位的任何削弱（如脱欧后业务外流）都会影响英镑的长期需求基础。", "key_point": "伦敦金融中心地位是英镑长期需求的结构性支撑。", "links": [{"text": "BIS 外汇调查", "url": "https://www.bis.org/statistics/rpfx22.htm", "type": "official"}]},
        ],
        "questions": [
            "脱欧对英镑的长期折价是否已充分定价？",
            "BOE高利率支撑英镑的可持续性如何？",
            "英镑的'高息避险'双重属性在风险事件中如何表现？",
            "伦敦金融中心地位变化对英镑意味着什么？",
            "英美贸易协定预期对英镑的潜在影响？",
        ],
    },
    "aud": {
        "code": "AUD", "name": "澳元", "name_en": "Australian Dollar",
        "pair": "AUD/USD", "pair_label": "澳元兑美元",
        "region": "大洋洲", "category": "商品货币",
        "current": {"rate": 0.6591, "date": "2026-08-04", "source": "欧洲央行"},
        "trend": "震荡", "trend_dir": "flat",
        "rate_context": "美澳利差", "rate_pair": ("au", "us"),
        "correlations": ["USD", "NZD", "CNY", "CAD", "JPY"],
        "intro": (
            "澳元是典型的'商品货币'，全球第五大交易货币。"
            "AUD/USD长期在0.65-0.75区间震荡，走势与铁矿石等大宗商品价格、中国需求高度相关。"
            "澳元兼具套息目标货币（RBA利率相对较高）与风险资产属性。"
            "理解澳元需把握：大宗商品周期、中国因素、RBA政策、风险偏好四条主线。"
        ),
        "history": [
            {"date": "2010", "rate": 0.917, "event": "大宗商品超级周期"},
            {"date": "2011", "rate": 1.034, "event": "澳元升破美元平价"},
            {"date": "2012", "rate": 1.036, "event": "矿业投资高峰"},
            {"date": "2013", "rate": 0.968, "event": "RBA降息周期"},
            {"date": "2014", "rate": 0.902, "event": "大宗回落"},
            {"date": "2015", "rate": 0.758, "event": "铁矿石大跌"},
            {"date": "2016", "rate": 0.745, "event": "低位企稳"},
            {"date": "2017", "rate": 0.780, "event": "全球复苏"},
            {"date": "2018", "rate": 0.747, "event": "贸易摩擦冲击"},
            {"date": "2019", "rate": 0.696, "event": "RBA降息至历史低点"},
            {"date": "2020", "rate": 0.690, "event": "疫情冲击后反弹"},
            {"date": "2021", "rate": 0.748, "event": "大宗商品反弹"},
            {"date": "2022", "rate": 0.666, "event": "美联储激进加息"},
            {"date": "2023", "rate": 0.661, "event": "RBA滞后加息"},
            {"date": "2024", "rate": 0.661, "event": "中国需求疲软"},
            {"date": "2025", "rate": 0.650, "event": "RBA降息"},
            {"date": "2026", "rate": 0.6591, "event": "ECB参考汇率（2026-08-04）"},
        ],
        "drivers": [
            {"title": "大宗商品价格（尤其铁矿石）", "weight": "核心驱动", "mechanism": "澳大利亚是全球最大铁矿石出口国，铁矿石占其出口约30%。铁矿石价格与AUD/USD高度正相关（相关系数约0.6-0.8）。大宗商品周期是澳元最核心的驱动，反映全球（尤其中国）需求。", "key_point": "大宗商品价格是澳元的命脉，铁矿石是核心指标。", "links": [{"text": "澳大利亚统计局贸易", "url": "https://www.abs.gov.au/statistics/economy/international-trade", "type": "official"}, {"text": "铁矿石价格", "url": "https://forex.10jqka.com.cn/quotes/", "type": "ths"}]},
            {"title": "中国因素", "weight": "结构性因素", "mechanism": "中国是澳大利亚最大贸易伙伴（出口占比约35%）。中国房地产、基建需求直接影响铁矿石价格与澳元。AUD/USD与人民币、中国股市有一定相关性。中国经济放缓是近年澳元承压的主因之一。", "key_point": "中国需求是澳元的结构性支撑，中国因素即澳元因素。", "links": [{"text": "中国海关统计", "url": "http://www.customs.gov.cn/", "type": "official"}]},
            {"title": "美澳利差与RBA政策", "weight": "资金流向", "mechanism": "RBA现金利率3.10%，美联储3.63%，美澳利差约-53bp（美国略高）。澳元曾是高息套息目标货币，但近年利差收窄削弱这一属性。RBA相对美联储的政策路径决定AUD/USD方向。", "key_point": "RBA与美联储政策分化是澳元资金流向的关键。", "links": [{"text": "RBA 货币政策", "url": "https://www.rba.gov.au/monetary-policy/", "type": "official"}]},
            {"title": "风险偏好与套息属性", "weight": "情境因素", "mechanism": "澳元兼具风险资产属性——风险偏好上升时走强（如股市上涨），避险情绪升温时走弱。历史上澳元是套息交易的目标货币（借日元买澳元）。风险事件下澳元常与日元反向波动。", "key_point": "澳元是风险偏好的晴雨表，与日元常反向。", "links": [{"text": "RBA 金融稳定", "url": "https://www.rba.gov.au/financial-stability/", "type": "official"}]},
            {"title": "美元周期", "weight": "镜像因素", "mechanism": "AUD/USD同样受美元周期影响。美元走弱时澳元被动走强，但澳元的商品属性使其波动大于纯镜像货币。需用澳元贸易加权指数剥离美元因素。", "key_point": "澳元波动=商品因素+美元因素+风险因素三者叠加。", "links": [{"text": "RBA 有效汇率", "url": "https://www.rba.gov.au/statistics/frequency/exchange-rates/", "type": "official"}]},
        ],
        "questions": [
            "铁矿石价格与AUD/USD的相关性是否在减弱？原因是什么？",
            "中国经济转型对澳元的长期影响如何？",
            "澳元作为'风险晴雨表'的属性在近年是否变化？",
            "澳元与纽元、加元等同为商品货币的联动逻辑？",
            "RBA政策正常化对澳元意味着什么？",
        ],
    },
    "chf": {
        "code": "CHF", "name": "瑞郎", "name_en": "Swiss Franc",
        "pair": "USD/CHF", "pair_label": "美元兑瑞郎",
        "region": "欧洲", "category": "避险货币",
        "current": {"rate": 0.8703, "date": "2026-08-04", "source": "欧洲央行"},
        "trend": "瑞郎强势", "trend_dir": "down",
        "rate_context": "美瑞利差", "rate_pair": ("us", "ch"),
        "correlations": ["EUR", "USD", "JPY", "GBP"],
        "intro": (
            "瑞郎是全球最经典的避险货币，与日元、美元构成'避险三角'。"
            "USD/CHF从2022年0.96降至2026-08的0.87，瑞郎持续走强。"
            "瑞郎走势核心看避险需求、SNB政策与欧元区稳定性。"
            "2015年瑞郎脱钩事件是外汇史上最大单日波动之一，是理解瑞郎的关键案例。"
        ),
        "history": [
            {"date": "2010", "rate": 1.043, "event": "欧债危机避险"},
            {"date": "2011", "rate": 0.879, "event": "SNB设定欧元兑瑞郎1.20下限"},
            {"date": "2012", "rate": 0.939, "event": "上限维持"},
            {"date": "2013", "rate": 0.934, "event": "上限维持"},
            {"date": "2014", "rate": 0.910, "event": "上限压力增大"},
            {"date": "2015", "rate": 0.969, "event": "1月15日脱钩，瑞郎单日暴涨30%"},
            {"date": "2016", "rate": 0.987, "event": "脱欧避险"},
            {"date": "2017", "rate": 0.969, "event": "全球复苏"},
            {"date": "2018", "rate": 0.992, "event": "贸易摩擦"},
            {"date": "2019", "rate": 0.994, "event": "避险回升"},
            {"date": "2020", "rate": 0.940, "event": "疫情避险"},
            {"date": "2021", "rate": 0.914, "event": "风险偏好回升"},
            {"date": "2022", "rate": 0.956, "event": "SNB意外加息、干预升值"},
            {"date": "2023", "rate": 0.906, "event": "瑞郎强势"},
            {"date": "2024", "rate": 0.880, "event": "SNB降息"},
            {"date": "2025", "rate": 0.880, "event": "避险与利差平衡"},
            {"date": "2026", "rate": 0.8703, "event": "ECB参考汇率（2026-08-04）"},
        ],
        "drivers": [
            {"title": "避险需求", "weight": "核心驱动", "mechanism": "瑞郎是传统避险货币，地缘冲突、金融危机、市场动荡时资金流入瑞郎。瑞士政治稳定、经常账户顺差、法治健全构成避险基础。2022年俄乌冲突、银行业动荡均推升瑞郎。避险属性是瑞郎长期强势的根本。", "key_point": "避险需求是瑞郎的核心溢价来源，风险事件是主要催化剂。", "links": [{"text": "SNB 货币政策", "url": "https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/monetary_policy", "type": "official"}]},
            {"title": "SNB政策与外汇干预", "weight": "政策因素", "mechanism": "SNB政策利率0.25%，曾长期负利率。SNB历史上积极干预汇率：2011-2015年设定欧元兑瑞郎1.20下限；2015年突然脱钩引发市场震荡；2022年罕见出售外汇干预升值。SNB干预意愿与方向是瑞郎短期波动的关键。", "key_point": "SNB干预历史显示其'不按常理出牌'，是瑞郎的特殊风险。", "links": [{"text": "SNB 干预报告", "url": "https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/forex-intervention", "type": "official"}]},
            {"title": "欧元区稳定性", "weight": "结构性因素", "mechanism": "瑞士与欧元区经济高度一体化，EUR/CHF是重要交叉汇率。欧元区动荡（欧债危机、银行业问题）会推升瑞郎避险买盘。瑞郎与欧元长期负相关——欧元弱则瑞郎强。", "key_point": "欧元区风险是瑞郎避险需求的长期来源。", "links": [{"text": "Eurostat", "url": "https://ec.europa.eu/eurostat", "type": "official"}]},
            {"title": "美瑞利差", "weight": "资金流向", "mechanism": "美联储3.63%，SNB仅0.25%，美瑞利差约338bp。巨大利差理论上压制瑞郎，但避险溢价持续抵消利差负面影响。这是瑞郎'反常'之处——低利率却强势，反映避险溢价的主导。", "key_point": "瑞郎低利率却强势，体现避险溢价对利差的主导。", "links": [{"text": "美瑞利差", "url": "https://forex.10jqka.com.cn/quotes/", "type": "ths"}]},
            {"title": "瑞士经常账户顺差", "weight": "基本面", "mechanism": "瑞士长期经常账户顺差（占GDP约5-10%），反映出口竞争力与海外投资收益。经常账户顺差是瑞郎长期强势的基本面支撑，与避险属性共同构成'强势瑞郎'基础。", "key_point": "经常账户顺差+避险属性=瑞郎长期强势的双重支撑。", "links": [{"text": "瑞士央行统计", "url": "https://www.snb.ch/en/ifor/finmkt/statistics", "type": "official"}]},
        ],
        "questions": [
            "2015年瑞郎脱钩事件的教训是什么？SNB为何突然行动？",
            "瑞郎'低利率却强势'如何用理论解释？避险溢价的边界？",
            "瑞郎与日元的避险属性有何异同？何时分化？",
            "SNB干预升值（2022年）的动机与效果如何？",
            "数字瑞郎（CBDC）对瑞郎国际地位的影响？",
        ],
    },
    "usd": {
        "code": "USD", "name": "美元", "name_en": "US Dollar",
        "pair": "DXY", "pair_label": "美元指数",
        "region": "全球", "category": "储备货币",
        "current": {"rate": 102.4, "date": "2026-08-01", "source": "ICE"},
        "trend": "降息周期走弱", "trend_dir": "down",
        "rate_context": "美国利率与利差", "rate_pair": ("us", "us"),
        "correlations": ["EUR", "JPY", "GBP", "CNY", "CHF"],
        "intro": (
            "美元是全球储备货币，占外汇储备约58%、外汇交易约88%。"
            "美元指数（DXY）从2022年高点114降至2026-08的102，反映美联储降息周期。"
            "美元是所有货币的'分母'，理解美元周期是分析所有货币的前提。"
            "美元强弱核心看：美联储政策、美国经济相对表现、全球风险偏好、储备货币地位。"
        ),
        "history": [
            {"date": "2010", "rate": 79.2, "event": "QE2前夕，美元弱势"},
            {"date": "2011", "rate": 80.9, "event": "欧元区危机避险"},
            {"date": "2012", "rate": 80.3, "event": "震荡"},
            {"date": "2013", "rate": 81.4, "event": "缩减恐慌"},
            {"date": "2014", "rate": 86.5, "event": "美元走强周期启动"},
            {"date": "2015", "rate": 96.5, "event": "美联储加息预期"},
            {"date": "2016", "rate": 96.5, "event": "特朗普当选"},
            {"date": "2017", "rate": 92.3, "event": "全球复苏，美元走弱"},
            {"date": "2018", "rate": 95.1, "event": "贸易摩擦与加息"},
            {"date": "2019", "rate": 96.5, "event": "避险与降息"},
            {"date": "2020", "rate": 90.9, "event": "疫情后美元走弱"},
            {"date": "2021", "rate": 90.5, "event": "通胀升温"},
            {"date": "2022", "rate": 103.5, "event": "美联储激进加息，DXY触114"},
            {"date": "2023", "rate": 103.5, "event": "高位震荡"},
            {"date": "2024", "rate": 104.2, "event": "美元强势延续"},
            {"date": "2025", "rate": 103.0, "event": "美联储降息，美元回落"},
            {"date": "2026", "rate": 102.4, "event": "ICE美元指数（2026-08-01）"},
        ],
        "drivers": [
            {"title": "美联储货币政策", "weight": "核心驱动", "mechanism": "美联储联邦基金利率3.63%（2026-07），从2023年峰值5.03%降息约140bp。美元指数与美联储政策周期高度相关：加息周期美元走强（2022-2023），降息周期美元走弱（2025-2026）。利差是美元相对所有货币的核心驱动。", "key_point": "美联储政策周期是美元走势的第一性驱动。", "links": [{"text": "美联储 FOMC", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "type": "official"}, {"text": "美联储利率", "url": "https://www.federalreserve.gov/releases/h15/", "type": "official"}]},
            {"title": "美国经济相对表现", "weight": "基本面", "mechanism": "美元强弱本质是美国相对其他经济体的表现。美国增长强于欧日时美元走强，反之走弱。关键指标：相对GDP增速、相对通胀、相对PMI。'美国例外论'预期是近年美元强势的基本面支撑。", "key_point": "美元是相对价格，看美国vs其他经济体的相对表现。", "links": [{"text": "BEA 经济数据", "url": "https://www.bea.gov/", "type": "official"}]},
            {"title": "全球风险偏好与避险", "weight": "情境因素", "mechanism": "美元是终极避险货币。全球风险事件（金融危机、地缘冲突、疫情）时资金流入美元。但2026年日元、瑞郎也具备避险属性，美元避险地位受一定挑战。风险偏好上升时美元往往走弱。", "key_point": "美元避险属性使其在风险事件中'越跌越涨'。", "links": [{"text": "VIX 恐慌指数", "url": "https://www.cboe.com/tradable_products/vix/", "type": "official"}]},
            {"title": "双赤字与财政", "weight": "结构性因素", "mechanism": "美国长期贸易与财政双赤字是美元的结构性压制。但'特里芬难题'下，美元储备需求掩盖了赤字压力。财政赤字扩大长期削弱美元信用，但短期影响有限。", "key_point": "双赤字是美元长期隐忧，但被储备需求掩盖。", "links": [{"text": "美国财政部国际资本", "url": "https://ticdata.treasury.gov/", "type": "official"}]},
            {"title": "储备货币地位与去美元化", "weight": "长期因素", "mechanism": "美元占全球外汇储备约58%（2015年约66%），呈缓慢下降趋势。去美元化议题（人民币国际化、金砖货币、央行增持黄金）是美元长期地位的变量。但美元的网络效应与市场深度使其地位短期难以撼动。", "key_point": "去美元化是长期变量，短期影响有限但需关注趋势。", "links": [{"text": "IMF COFER", "url": "https://data.imf.org/?sk=2DFB3380-3603-4D2C-90BE-A04D8BBCE237", "type": "official"}]},
        ],
        "questions": [
            "美元周期的'美国例外论'预期是否可持续？",
            "去美元化对美元长期地位的实质影响有多大？",
            "美联储降息周期中，美元走弱的速度与幅度如何预判？",
            "特里芬难题在当前是否更加突出？",
            "美元避险地位是否受到日元、瑞郎的挑战？",
        ],
    },
}

# 货币列表（导航用，按逻辑分组）
CURRENCY_NAV = [
    {"code": "jpy", "label": "日元", "pair": "USD/JPY"},
    {"code": "cny", "label": "人民币", "pair": "USD/CNY"},
    {"code": "eur", "label": "欧元", "pair": "EUR/USD"},
    {"code": "gbp", "label": "英镑", "pair": "GBP/USD"},
    {"code": "aud", "label": "澳元", "pair": "AUD/USD"},
    {"code": "chf", "label": "瑞郎", "pair": "USD/CHF"},
    {"code": "usd", "label": "美元", "pair": "DXY"},
]

# 关联货币代码映射（用于实时小窗）
CORRELATED_CODES = {
    "JPY": ["USD", "EUR", "CHF", "KRW", "CNY"],
    "CNY": ["USD", "EUR", "JPY", "KRW", "AUD"],
    "EUR": ["USD", "GBP", "CHF", "JPY", "CNY"],
    "GBP": ["USD", "EUR", "AUD", "CAD", "JPY"],
    "AUD": ["USD", "NZD", "CNY", "CAD", "JPY"],
    "CHF": ["EUR", "USD", "JPY", "GBP", "CAD"],
    "USD": ["EUR", "JPY", "GBP", "CNY", "CHF"],
}

# 各货币的 Frankfurter API 查询对（用于月度/日度数据获取）
# USD 美元指数无单一货币对，用 EUR/USD 作为镜像代理
LIVE_PAIRS = {
    "jpy": {"from": "USD", "to": "JPY", "label": "USD/JPY"},
    "cny": {"from": "USD", "to": "CNY", "label": "USD/CNY"},
    "eur": {"from": "EUR", "to": "USD", "label": "EUR/USD"},
    "gbp": {"from": "GBP", "to": "USD", "label": "GBP/USD"},
    "aud": {"from": "AUD", "to": "USD", "label": "AUD/USD"},
    "chf": {"from": "USD", "to": "CHF", "label": "USD/CHF"},
    "usd": {"from": "EUR", "to": "USD", "label": "EUR/USD（美元镜像）"},
}

# ============================================================
# 货币深度分析（货币角色 / 近期大事件 / 深度驱动因素）
# ============================================================
CURRENCY_DEEP_ANALYSIS = {
    "jpy": {
        "currency_role": (
            "日元是全球套利交易（carry trade）的核心融资货币。其机制为：由于日本长期实施低利率/负利率政策"
            "（2016年起实行负利率，2024年退出负利率），全球投资者以极低成本借入日元，再将资金投入高息资产"
            "（美元、澳元、新兴市场资产等）赚取利差。据市场估算，日元套利交易规模曾高达约586万亿日元，"
            "成为全球风险资产流动性重要来源。日元因此具备'反向风险晴雨表'特征：当全球风险偏好上升时，"
            "套利交易扩张令日元贬值；当风险规避或日债收益率上升时，套利平仓引发日元急升并对全球股市/科技股"
            "形成冲击。日元同时是全球第三大交易货币，亦是储备货币之一，但在政策正常化进程中其融资货币属性"
            "正在被重新定价。"
        ),
        "recent_events": [
            {"date": "2024-03", "title": "BOJ退出负利率政策",
             "description": "BOJ结束长达8年的负利率政策，首次加息，标志货币政策正常化起点。这是2007年以来首次加息。",
             "impact": "理论上应支撑日元升值，但因加息幅度温和且前瞻指引鸽派，日元反而贬值，套利交易继续扩张，USD/JPY一度升至160上方。"},
            {"date": "2024-07至08", "title": "日元套利交易平仓引发全球闪崩",
             "description": "BOJ意外加息叠加美国非农数据超预期走弱，USD/JPY在不到一个月内从162急贬至143，TOPIX从历史高点回落24%，纳斯达克100遭遇惨烈抛售，8月5日全球金融闪崩。",
             "impact": "套利交易平仓（unwind）放大市场波动，凸显日元套利规模对全球金融稳定的系统性风险。市场短暂稳定后套利交易部分重启，但结构性脆弱性仍在。"},
            {"date": "2025全年", "title": "BOJ推进渐进加息与国债收益率上行",
             "description": "行长植田和男多次释放加息信号，10年期日债收益率升至2.120%附近，2年期日债收益率创17年新高。经济学家普遍预测2025年加息两次。",
             "impact": "市场对12月加息预期一度升至80%以上，动摇全球套息交易根基。日元年内升值接近10%，创退出负利率以来最大年度升值幅度。"},
            {"date": "2026-07月底", "title": "美日罕见联合外汇干预",
             "description": "日元兑美元跌至近40年低点（USD/JPY低位约163.97），日美当局实施罕见联合外汇干预。美国财政部时隔15年再度直接下场（通过纽约联储卖出美元/买入日元）。",
             "impact": "USD/JPY迅速从163.97拉升至155.22高位，随后稳定在157.60附近。此次联合干预目的涉及美债市场稳定、半导体与AI供应链安全及全球金融体系稳定。"},
        ],
        "deep_drivers": [
            {"category": "结构性因素（长期）", "factor": "美日利差与套利交易结构性存量",
             "mechanism": "美国政策利率（3.5-3.75%）与日本政策利率（1.0%）仍存在显著正利差，构成套利交易的根本动力。",
             "detail": "据BIS与市场估算，日元套利存量约586万亿日元。利差每收窄25bp，套利吸引力相应下降，但需利差显著收窄或出现风险事件才会触发大规模平仓。"},
            {"category": "结构性因素（长期）", "factor": "日本贸易结构与海外资产回流",
             "mechanism": "日本长期贸易顺差转为逆差（能源进口依赖），叠加日本机构投资者海外资产巨大，汇率对冲行为影响日元供需。",
             "detail": "日本GPIF（政府养老金）等机构海外资产配置及对冲比率调整，构成日元长期供需的重要变量。"},
            {"category": "周期性因素（中期）", "factor": "BOJ货币政策正常化节奏",
             "mechanism": "BOJ加息步伐、YCC退出程度、缩减购债节奏直接决定日债收益率上行斜率。",
             "detail": "植田和男主导渐进式正常化，10年期日债收益率升至2.12%。市场对2025-2026年再加息预期持续修正，是日元中期定价核心。"},
            {"category": "事件性因素（短期）", "factor": "外汇干预与全球风险事件",
             "mechanism": "日本财务省单独或联合美联储干预，可在短期剧烈扭转汇率；全球风险-off事件触发套利平仓放大日元升值。",
             "detail": "2026年7月美日联合干预为15年来首次美国直接参与。干预通常在USD/JPY极端低位（>160）或无序波动时出手。"},
            {"category": "事件性因素（短期）", "factor": "美国非农与美联储政策预期",
             "mechanism": "美国经济数据通过影响美联储降息预期，反向作用于美日利差与套利交易。",
             "detail": "2024年8月闪崩即由美国非农走弱触发。美联储降息预期升温→美债收益率下行→美日利差收窄→套利平仓→日元升值。"},
        ],
    },
    "cny": {
        "currency_role": (
            "人民币是受管制的国际化货币，实行在岸（CNY）/离岸（CNH）双轨制。在岸人民币受中国央行严格管理，"
            "每日设有中间价及2%波动区间；离岸人民币（CNH）在香港等离岸市场自由交易，反映国际供需与预期。"
            "央行通过中间价引导、逆周期因子、离岸央票发行、外汇存款准备金率等工具调节汇率。人民币是全球第五大"
            "支付货币（2025年占比约6%），并通过CIPS（人民币跨境支付系统）、数字人民币、'一带一路'贸易结算等"
            "推进国际化。其汇率定价同时受中美关系、美元周期、资本流出管控、国内经济基本面多重影响，是新兴市场"
            "货币中特殊的存在——兼具管制属性与国际化雄心。"
        ),
        "recent_events": [
            {"date": "2025-01", "title": "央行发行600亿离岸央票稳汇率",
             "description": "1月9日，离岸人民币兑美元收复7.35关口，央行公告发行600亿元离岸央票，回收离岸人民币流动性。",
             "impact": "收紧离岸人民币流动性以抬高做空成本，抑制离岸贬值压力，释放稳汇率信号。USD/CNH日内反弹约100个基点。"},
            {"date": "2025-04", "title": "美国推出'对等关税'与中美关税博弈",
             "description": "2025年4月初美国推出所谓'对等关税'，中美双边关税不断升级，人民币汇率再次走弱突破7.3水平。后经多轮磋商达成相互降低关税协议。",
             "impact": "关税预期扰动是2025年人民币核心压力源。关税升级期间人民币承压贬值破7.3，缓和后人民币重启升值。"},
            {"date": "2025全年", "title": "人民币'先弱后强'升破7.00收官",
             "description": "人民币从7.30附近开局，到升破7.00收官。在岸、离岸人民币兑美元分别累计上涨约4.27%、4.93%。",
             "impact": "反映'美国例外论崩塌'、美元信任走弱及中国政策托底共同作用。市场预期人民币2026年有望双向波动升值。"},
            {"date": "2026-07", "title": "人民币震荡上行创阶段新高",
             "description": "2026年7月以来人民币兑美元震荡上行，7月30日在岸人民币盘中最高触及6.7581，离岸最高升至6.7561，双双创阶段新高。",
             "impact": "反映美元走软、中美摩擦阶段性降温及央行稳增长与防资本外流平衡的综合效果。"},
            {"date": "2025-10", "title": "央行发布《2025年人民币国际化报告》",
             "description": "央行发布报告，多边央行数字货币桥已有5家央行参与，CIPS持续扩容，2026年3月CIPS日均交易额达9205亿元。",
             "impact": "人民币国际化基础设施快速完善，全球支付份额升至6%。在地缘政治背景下，人民币国际化进程加速，为汇率提供长期支撑。"},
        ],
        "deep_drivers": [
            {"category": "结构性因素（长期）", "factor": "在岸/离岸双轨制与资本账户管制",
             "mechanism": "资本账户尚未完全开放，央行通过中间价、逆周期因子、外汇管制等工具对冲投机性资本流动，使人民币汇率弹性低于自由浮动货币。",
             "detail": "双轨制下离岸（CNH）反映国际预期，在岸（CNY）受央行管理，两者价差本身成为压力信号。"},
            {"category": "结构性因素（长期）", "factor": "人民币国际化与去美元化趋势",
             "mechanism": "CIPS系统扩容、数字人民币跨境应用、'一带一路'贸易结算、金砖国家本币结算推进，长期提升人民币需求。",
             "detail": "2025年人民币全球支付份额约6%，2026年3月CIPS日均交易额9205亿元。多边央行数字货币桥项目持续推进。"},
            {"category": "周期性因素（中期）", "factor": "中美关系与关税政策",
             "mechanism": "中美贸易摩擦升级→出口承压、资本外流压力上升→人民币贬值；缓和→升值。",
             "detail": "2025年4月'对等关税'冲击是典型案例。中美关系是人民币中期最大不确定因素。"},
            {"category": "周期性因素（中期）", "factor": "美元周期与中美利差",
             "mechanism": "美联储降息周期→美元走弱→人民币被动升值；中美利差收窄→资本流出压力缓解。",
             "detail": "2025年美元指数暴跌9.3-9.7%，为人民币升值提供外部支撑。2026年市场预期美联储继续降息2-3次。"},
            {"category": "事件性因素（短期）", "factor": "央行稳汇率工具操作",
             "mechanism": "离岸央票发行、外汇存款准备金率调整、逆周期因子、国有大行结售汇等工具短期内扭转预期。",
             "detail": "2025年1月600亿离岸央票发行即为一例。工具操作在关键点位（如7.3、7.0）尤为密集。"},
        ],
    },
    "eur": {
        "currency_role": (
            "欧元是全球第二大储备货币与第二大交易货币，欧元区GDP与美国相当。欧元的特殊角色在于："
            "（1）反映欧元区20国经济与政策的综合平衡，是'多国一币'架构的产物；"
            "（2）受欧洲央行（ECB）统一货币政策约束，但各成员国财政独立，形成'货币统一、财政分散'的内在张力；"
            "（3）能源高度依赖进口（尤其2022年北溪管道事件后重塑能源格局），使欧元对能源价格高度敏感；"
            "（4）作为美元主要对手货币，EUR/USD是全球流动性最高的货币对，欧元走势与美元指数高度负相关。"
            "欧元区内部经济分化（德国工业 vs 南欧服务业）使单一货币政策面临结构性挑战。"
        ),
        "recent_events": [
            {"date": "2024-09起", "title": "ECB开启连续降息周期",
             "description": "自2024年9月起ECB连续降息，至2025年12月已是连续第四次降息，2026年2月欧元区央行政策利率降至2.15%。",
             "impact": "降息周期压低欧元汇率，但因美联储同步降息且欧元区经济预期上调，欧元并未单边贬值。"},
            {"date": "2025-12", "title": "ECB上调经济增长与通胀预测",
             "description": "ECB预计2025年欧元区经济增长1.4%、2026年增长1.2%，2026年通胀预期同步上修。ECB预测假设2026-2028年欧元兑美元汇率1.16。",
             "impact": "通胀黏性使ECB降息空间受限，相对利差支撑欧元。但增长预期偏弱限制欧元上行。"},
            {"date": "2025-03", "title": "欧元区通胀反扑终结通缩叙事",
             "description": "3月调和CPI年率终值意外上修至2.6%，德国增长腰斩，通胀反扑逼近临界点。",
             "impact": "通胀超预期使ECB降息预期收敛，欧元兑美元短线走强超50个基点。"},
            {"date": "2022-2025", "title": "能源危机后遗症持续拖累德国工业",
             "description": "北溪管道受损后，欧洲能源格局重塑。据德国经济研究所测算，2022至2025年间能源危机吞噬数千亿欧元。",
             "impact": "能源成本结构性抬升削弱欧元区（尤其德国）制造业竞争力，贸易条件恶化，长期压制欧元估值。"},
            {"date": "2025", "title": "欧元区经济分化加剧",
             "description": "德国增长腰斩、法国数据接连爆冷，南欧（西班牙、希腊）相对稳健，欧元区内部经济分化加剧。",
             "impact": "分化使ECB单一货币政策难以适配所有成员国，'多国一币'内在张力凸显。"},
        ],
        "deep_drivers": [
            {"category": "结构性因素（长期）", "factor": "能源依赖与去工业化压力",
             "mechanism": "欧元区能源高度依赖进口，能源价格冲击→贸易条件恶化→欧元贬值。",
             "detail": "2022-2025年能源危机吞噬数千亿欧元。德国工业基础受损，制造业外迁压力上升。"},
            {"category": "结构性因素（长期）", "factor": "'多国一币'与经济分化",
             "mechanism": "20国共用单一货币政策，但经济周期与竞争力差异显著，核心国与外围国分化使政策两难。",
             "detail": "德国疲弱需宽松，南欧过热需收紧，ECB被迫折中。分化加剧时欧元区主权风险溢价上升。"},
            {"category": "周期性因素（中期）", "factor": "ECB货币政策周期与利差",
             "mechanism": "ECB降息/加息节奏相对美联储的差值决定欧美利差，直接影响EUR/USD汇率。",
             "detail": "2026年2月ECB政策利率2.15%，美联储3.5-3.75%，利差仍有利于美元。但ECB降息空间因通胀黏性受限。"},
            {"category": "周期性因素（中期）", "factor": "服务业通胀黏性与工资压力",
             "mechanism": "服务业通胀黏性使ECB难以快速降息，相对偏鹰支撑欧元；但高利率抑制增长。",
             "detail": "2025年3月HICP上修至2.6%，2026年通胀预期上修。ECB在'稳增长 vs 防通胀'间摇摆。"},
            {"category": "事件性因素（短期）", "factor": "地缘政治与能源供给冲击",
             "mechanism": "俄乌冲突、中东局势、能源供给中断等事件通过能源价格与风险溢价传导至欧元。",
             "detail": "欧元对地缘政治风险高度敏感，因能源进口依赖。任何中断欧洲能源供给的事件均会冲击欧元。"},
        ],
    },
    "gbp": {
        "currency_role": (
            "英镑是全球第四大交易货币与历史最悠久的储备货币之一。伦敦作为全球最大外汇交易中心，"
            "赋予英镑超越其经济体量的金融影响力。英镑的特殊性在于："
            "（1）脱欧后英国经济与欧盟关系重构，贸易与投资流重新定位；"
            "（2）英国经常账户长期赤字，依赖资本流入融资，使英镑对全球风险偏好与英国资产吸引力敏感；"
            "（3）英国央行（BoE）在G10中常率先行动，利率波动较大；"
            "（4）财政政治风险高（十年七相、工党预算争议），使英镑兼具'风险货币'与'政治敏感货币'属性。"
        ),
        "recent_events": [
            {"date": "2024-07", "title": "工党上台与财政'黑洞'披露",
             "description": "工党政府7月当选后披露220亿英镑财政'黑洞'，首相斯塔默直言英国已'破产'。",
             "impact": "财政担忧升温一度压制英镑。但工党强调财政审慎，市场对'负责任治理'预期部分对冲悲观情绪。"},
            {"date": "2024-10-11", "title": "里夫斯预算案财政紧缩",
             "description": "财政大臣里夫斯宣布规模300-400亿英镑的财政紧缩计划，通过增税与支出调整填补缺口。",
             "impact": "财政紧缩短期抑制增长预期，但长期改善财政可持续性，英镑反应混合。"},
            {"date": "2024-12", "title": "BoE维持高利率应对通胀黏性",
             "description": "英国通胀连续两月上升至2.6%，BoE 12月维持基准利率4.75%不变。",
             "impact": "相对偏鹰支撑英镑，但高利率抑制增长，形成'利率支撑 vs 增长拖累'拉锯。"},
            {"date": "2026-07", "title": "BoE维持3.75%利率，警示通胀上行风险",
             "description": "BoE维持政策基准利率3.75%不变，货币政策委员会投票6:3。政策官员警示通胀存在上行风险。",
             "impact": "BoE相对鹰派立场支撑英镑，但增长担忧限制上行。高盛预计2026年BoE可能再降息三次至3%。"},
            {"date": "2025-2026", "title": "脱欧十年后遗症持续显现",
             "description": "脱欧十年之际，十年七相被视为'脱欧诅咒'，贸易投资关系重构持续影响经济。",
             "impact": "脱欧后遗症长期压制英镑估值中枢，贸易壁垒与劳动力短缺削弱英国竞争力。"},
        ],
        "deep_drivers": [
            {"category": "结构性因素（长期）", "factor": "脱欧后遗症与贸易投资重构",
             "mechanism": "脱欧后贸易壁垒上升、劳动力短缺、投资流入减弱，结构性削弱英国潜在增长与英镑估值中枢。",
             "detail": "十年七相反映脱欧政治动荡。脱欧使英国与最大贸易伙伴欧盟关系重构。"},
            {"category": "结构性因素（长期）", "factor": "经常账户赤字与资本流入依赖",
             "mechanism": "英国长期经常账户赤字，依赖外国资本流入融资。全球风险-off时资本流出→英镑贬值。",
             "detail": "使英镑对全球风险偏好与英国资产吸引力高度敏感，具备一定'风险货币'属性。"},
            {"category": "周期性因素（中期）", "factor": "BoE货币政策与通胀黏性",
             "mechanism": "BoE利率相对其他央行偏高支撑英镑，但高利率抑制增长。通胀黏性使BoE降息节奏慢于预期。",
             "detail": "2026年7月BoE利率3.75%（6:3投票），高盛预计2026年再降三次至3%。"},
            {"category": "周期性因素（中期）", "factor": "财政政策与政治风险",
             "mechanism": "财政紧缩短期抑制增长，长期改善可持续性；政治不稳定性削弱英镑信心。",
             "detail": "工党预算案300-500亿英镑紧缩规模，220亿英镑财政'黑洞'。十年七相政治动荡是英镑长期折价来源。"},
            {"category": "事件性因素（短期）", "factor": "预算案与财政事件冲击",
             "mechanism": "重大财政公告通过增长预期与债务可持续性预期短期冲击英镑。",
             "detail": "2024年10月预算案、7月财政'黑洞'披露均为典型。类似2022年'迷你预算'危机的财政事件风险仍需警惕。"},
        ],
    },
    "aud": {
        "currency_role": (
            "澳元是典型的商品货币与风险偏好晴雨表。澳大利亚是铁矿石、煤炭、液化天然气等大宗商品主要出口国，"
            "澳元汇率与大宗商品价格（尤其铁矿石）高度正相关。其特殊角色在于："
            "（1）与中国经济高度联动——中国是澳大利亚最大贸易伙伴，中国需求前景直接驱动澳元；"
            "（2）作为G10中收益率较高的货币，澳元常作为套利交易的目标货币（与日元融资端互补）；"
            "（3）贸易条件（出口价格/进口价格）是澳元中期定价核心。澳元因此兼具'商品属性'与'风险属性'，"
            "在全球风险-on时表现强势，风险-off时贬值。"
        ),
        "recent_events": [
            {"date": "2025-04", "title": "RBA维持利率，铁矿石价格急速下滑",
             "description": "RBA 4月7日宣布维持指标利率2.25%不变，令预期降息的投资者意外。背景是铁矿石价格急速下滑。",
             "impact": "RBA按兵不动短期支撑澳元，但铁矿石价格下跌构成基本面压力。市场对降息概率一度升至84%。"},
            {"date": "2025-12", "title": "2026年铁矿石价格预计明显下行",
             "description": "澳大利亚政府和主要金融机构报告预计2026年铁矿石价格将明显下行。",
             "impact": "铁矿石价格下行预期构成澳元2026年核心利空。贸易条件恶化将拖累澳元。"},
            {"date": "2026年", "title": "中国地产政策优化刺激商品货币",
             "description": "2026年中国国内地产政策优化（三道红线调整）刺激铜价单日暴涨6%，铁矿石价格底部托举。",
             "impact": "中国需求预期改善直接利好澳元。对比欧、日（欧洲依赖能源进口），澳洲作为商品出口国贸易条件改善更显著。"},
            {"date": "2026年展望", "title": "RBA加息预期与澳元走势悬于央行",
             "description": "2026年澳元走势核心扰动源包括：RBA加息还是按兵不动、美联储降息节奏、铁矿石价格走势、中国需求前景。11月加息概率约40%。",
             "impact": "IMF下调澳洲2026增长至1.9%，通胀仍约4%，RBA继续鹰派概率低。加息预期延后下调澳元上行空间。"},
        ],
        "deep_drivers": [
            {"category": "结构性因素（长期）", "factor": "大宗商品出口与贸易条件",
             "mechanism": "铁矿石、煤炭、LNG出口价格决定澳大利亚贸易条件，直接驱动澳元。",
             "detail": "铁矿石是澳元最核心驱动。2026年铁矿石预计明显下行，构成澳元长期利空。"},
            {"category": "结构性因素（长期）", "factor": "中国经济联动",
             "mechanism": "中国是澳大利亚最大贸易伙伴，中国需求决定大宗商品价格，传导至澳元。",
             "detail": "2026年中国地产政策优化刺激铜价、铁矿石，直接利好澳元。"},
            {"category": "周期性因素（中期）", "factor": "RBA货币政策与利差",
             "mechanism": "RBA利率相对美联储利差决定套利流向。RBA鹰派→澳元升值；RBA鸽派或降息→澳元贬值。",
             "detail": "RBA利率2.25%（2025年4月），加息预期约40%（2026年11月）。IMF下调澳洲2026增长至1.9%。"},
            {"category": "周期性因素（中期）", "factor": "全球风险偏好与套利交易",
             "mechanism": "澳元作为套利目标货币，全球风险-on时资金流入升值，风险-off时平仓贬值。",
             "detail": "澳元与美股、新兴市场资产正相关。日元套利平仓时澳元常首当其冲贬值。"},
            {"category": "事件性因素（短期）", "factor": "中国经济政策与大宗商品价格波动",
             "mechanism": "中国重大政策与商品价格异动短期剧烈驱动澳元。",
             "detail": "2026年中国三道红线调整刺激铜价单日暴涨6%即为典型。"},
        ],
    },
    "chf": {
        "currency_role": (
            "瑞郎是全球公认的传统避险货币，与日元、美元并称三大避险货币。其避险属性源于："
            "（1）瑞士政治永久中立、法律稳定、私人银行业发达，是全球资本避风港；"
            "（2）瑞士经济财政稳健，经常账户长期盈余；"
            "（3）瑞士央行（SNB）历史上强力干预瑞郎升值（如2011-2015年EUR/CHF 1.20汇率上限）；"
            "（4）瑞郎与欧元高度相关（瑞士与欧元区经贸紧密），常被视为'欧元区风险对冲'。"
            "瑞郎的'负利率遗产'（2015-2022年曾实施-0.75%负利率）使其融资属性弱于日元，"
            "但避险属性更强、更纯粹。"
        ),
        "recent_events": [
            {"date": "2015-01-15", "title": "SNB取消EUR/CHF 1.20汇率上限（历史遗产）",
             "description": "SNB突然宣布取消瑞郎兑欧元1.20汇率上限并降息至-0.75%，瑞郎兑欧元暴涨，'瑞郎风暴'引发巨震。",
             "impact": "瑞郎瞬间暴涨约30%，对冲基金惨重损失。SNB自此放弃硬性上限，转向通过外汇干预与利率调节。"},
            {"date": "2025-2026", "title": "SNB维持0%利率并准备外汇干预",
             "description": "SNB将主要政策利率维持在0%不变，表态若市场避险需求升温推高瑞郎汇率将随时干预外汇市场。",
             "impact": "SNB干预立场抑制瑞郎过度升值，保护瑞士出口竞争力与通胀目标。0%利率使瑞郎融资属性弱于日元。"},
            {"date": "2026-06", "title": "SNB 6月议息会议纪要：紧盯瑞郎波动",
             "description": "SNB 6月议息会议纪要显示维持政策利率0%不变，紧盯瑞郎汇率波动。",
             "impact": "SNB通过活期存款变动向市场释放干预信号，影响瑞郎短期走势。"},
        ],
        "deep_drivers": [
            {"category": "结构性因素（长期）", "factor": "避险属性与瑞士中立地位",
             "mechanism": "瑞士永久中立、政治法律稳定、私人银行业发达，全球风险-off时资本流入瑞郎避险。",
             "detail": "瑞郎与日元、美元并称三大避险货币，但避险属性更纯粹。瑞士经常账户长期盈余强化瑞郎强势基础。"},
            {"category": "结构性因素（长期）", "factor": "负利率遗产与融资属性弱化",
             "mechanism": "2015-2022年SNB实施-0.75%负利率，但避险需求主导使瑞郎仍强势。负利率退出后瑞郎融资属性弱于日元。",
             "detail": "瑞郎不再是主要套利融资货币，使其走势更纯粹反映避险需求与SNB政策。"},
            {"category": "周期性因素（中期）", "factor": "SNB货币政策与外汇干预",
             "mechanism": "SNB通过利率与外汇干预调节瑞郎。瑞郎过度升值→SNB卖出瑞郎/买入外汇→抑制升值。",
             "detail": "2025-2026年SNB维持0%利率，明确准备干预。SNB活期存款变动是干预线索。"},
            {"category": "周期性因素（中期）", "factor": "欧元区风险与EUR/CHF联动",
             "mechanism": "瑞士与欧元区经贸紧密，瑞郎常被视为欧元区风险对冲。欧元区危机→资金从欧元流入瑞郎。",
             "detail": "EUR/CHF是观察欧元区风险溢价的关键交叉汇率。欧元区经济疲弱或主权风险上升时瑞郎相对欧元升值。"},
            {"category": "事件性因素（短期）", "factor": "全球风险-off事件与SNB口头干预",
             "mechanism": "地缘政治、金融危机等风险-off事件触发避险资金流入瑞郎；SNB官员口头干预或实际入场短期扭转走势。",
             "detail": "SNB行长曾称瑞郎'严重高估'并威胁积极干预。口头干预本身能在短期抑制瑞郎升值。"},
        ],
    },
    "usd": {
        "currency_role": (
            "美元是全球储备货币与计价结算核心，占据全球外汇储备约56-57%（2025年）、国际贸易结算约40%、"
            "大宗商品计价近100%。美元霸权体现在：（1）石油美元体系与大宗商品美元计价；"
            "（2）美债作为全球'无风险资产'基准与抵押品核心；（3）美联储作为全球最后贷款人；"
            "（4）美元支付网络（SWIFT、CHIPS）的全球垄断地位。"
            "美元指数（DXY）衡量美元对6种主要货币汇率，是全球风险偏好与流动性核心指标。"
            "美元具备'反风险'属性：全球风险-off时美元升值。但2025年美元霸权面临去美元化、财政赤字恶化、"
            "美联储独立性受质疑等结构性挑战，黄金储备价值时隔近30年首次超过美债持有规模。"
        ),
        "recent_events": [
            {"date": "2025全年", "title": "美元指数暴跌9.3-9.7%，2017年以来最差",
             "description": "截至2025年12月26日，美元指数徘徊98附近，全年累计下跌约9.3-9.7%。美元从年初108跌至约98。",
             "impact": "反映'美国例外论崩塌'、市场对美元信心动摇。德意志银行、高盛、摩根士丹利等一致看跌2026年美元。"},
            {"date": "2025-12", "title": "美联储降息至3.5-3.75%并暗示2026年仅一次降息",
             "description": "美联储12月会议降息25个基点至3.5-3.75%区间，点阵图暗示2026年仅一次降息。但市场定价更激进，预计至少两次降息。",
             "impact": "美联储相对偏鹰与市场激进降息预期的背离，是美元短期波动源。"},
            {"date": "2025中期", "title": "全球央行黄金储备价值首超美债持有规模",
             "description": "2025年标志性转折——全球央行持有的黄金储备总价值首次超过其持有的美债规模。美元在全球外汇储备占比降至56.77%。",
             "impact": "标志'黄金锚定'新时代开启，去美元化进入新阶段。各国央行转向零信用风险黄金。"},
            {"date": "2025-2026", "title": "美债规模突破40万亿美元与财政赤字恶化",
             "description": "美国国债规模突破40万亿美元，财政赤字高企。美联储陷入两难：降息缓解还债压力会复燃通胀，坚持高利率则融资成本高企。",
             "impact": "财政可持续性担忧削弱美元信用。美债收益率一度飙升至5.2%。"},
            {"date": "2026-07", "title": "美国财长呼吁提高FIMA上限配合日元干预",
             "description": "美日联合干预日元时，美国财长贝森特公开呼吁美联储提高FIMA回购便利上限。",
             "impact": "反映美国在强美元与美债稳定间的权衡。提高上限暗示美国容忍美元走弱以维护全球金融稳定。"},
        ],
        "deep_drivers": [
            {"category": "结构性因素（长期）", "factor": "美元霸权与去美元化趋势",
             "mechanism": "美元储备货币地位带来'过度特权'，但去美元化侵蚀其份额。",
             "detail": "2025年美元储备占比降至56.77%（30年低点），黄金储备份额达23%（30年高点），金砖黄金储备占比17.4%。"},
            {"category": "结构性因素（长期）", "factor": "财政赤字与美债可持续性",
             "mechanism": "财政赤字恶化→美债供给激增→收益率上行→融资成本上升→赤字进一步恶化，形成恶性循环。",
             "detail": "美债规模突破40万亿美元。美债收益率一度飙至5.2%。财政可持续性是美元长期信用的核心风险。"},
            {"category": "周期性因素（中期）", "factor": "美联储政策周期与利差",
             "mechanism": "美联储降息/加息节奏相对其他央行差值决定美元利差优势。",
             "detail": "2025年美联储降息至3.5-3.75%，市场预期2026年再降2-3次。与ECB（2.15%）、BoE（3.75%）利差收窄压制美元。"},
            {"category": "周期性因素（中期）", "factor": "美国经济相对表现与'美国例外论'",
             "mechanism": "美国经济相对其他经济体强弱决定美元。'美国例外论'强化→美元升值；例外论崩塌→美元贬值。",
             "detail": "2025年'美国例外论崩塌'是美元暴跌9.3-9.7%的核心叙事。"},
            {"category": "事件性因素（短期）", "factor": "美联储独立性担忧与全球风险-off",
             "mechanism": "政治压力干预美联储独立性→美元贬值；全球危机时美元作为储备货币吸引避险资金流入。",
             "detail": "2025年黄金避险地位上升，部分分流美元避险需求。美元避险属性面临'去美元化'重新定价。"},
        ],
    },
}

# ============================================================
# 外汇基础概念（学术化，无表情符号）
# ============================================================
FOREX_CONCEPTS = [
    {"title": "汇率与标价法", "summary": "汇率是两国货币的相对价格；标价方向决定数值升降的升贬含义。", "detail": "汇率以货币对（currency pair）报价，如 USD/JPY、EUR/USD。直接标价法（1外币=X本币，数值升=本币贬值）多用于中国、日本；间接标价法（1本币=X外币，数值升=本币升值）用于英、美、欧。USD/JPY=159 表示1美元换159日元；EUR/USD=1.09 表示1欧元换1.09美元。", "formula": "1单位基准货币 = X单位标价货币\nUSD/JPY = 159 → 1美元 = 159日元\nEUR/USD = 1.09 → 1欧元 = 1.09美元", "example": "USD/JPY 从109升至159 = 日元贬值46%；USD/CNY从7.20降至6.75 = 人民币升值6.3%。方向感是外汇分析的起点。", "links": [{"text": "美联储 H.10 汇率发布", "url": "https://www.federalreserve.gov/releases/h10/", "type": "official"}, {"text": "BIS 外汇市场概览", "url": "https://www.bis.org/statistics/fx.htm", "type": "official"}]},
    {"title": "利率平价理论 (Interest Rate Parity)", "summary": "利差决定汇率的预期变动方向，是无套利均衡条件。", "detail": "覆盖利率平价（CIP）通过远期合约锁定，理论上严格成立。无覆盖利率平价（UIP）假设远期汇率等于未来即期预期，是汇率决定理论核心：高利率货币远期应贴水（贬值预期），低利率货币升水。但现实中UIP常被拒绝——高利率货币短期反而吸引资金流入，这正是套息交易的土壤。", "formula": "F/S = (1 + r_本币) / (1 + r_外币)\n期望：E(S₁)/S₀ ≈ (1+r_本币)/(1+r_外币)", "example": "美国3.63%、日本0.84%，理论日元应远期升水约2.8%。但日元持续贬值——差额是'风险溢价'，反映套息者要求的风险补偿。", "links": [{"text": "BIS 利率平价研究", "url": "https://www.bis.org/publ/work551.htm", "type": "article"}, {"text": "IMF 汇率理论", "url": "https://www.imf.org/external/pubs/ft/fandd/basics/exch.htm", "type": "article"}]},
    {"title": "套息交易 (Carry Trade)", "summary": "借低息货币、投高息资产，赚利差——外汇最经典策略之一。", "detail": "借入低利率融资货币（如日元），换成高利率货币投资高息资产，赚取利差。收益=利差+汇率损益。融资货币贬值时双丰收，升值时汇率损失快速吞噬利差，触发平仓踩踏。日元因长期低利率是全球最大融资货币，套息仓位据BIS估算达万亿美元级。2024年8月平仓曾引发全球股市震荡。", "formula": "总收益 ≈ (r_高息 - r_低息) + Δ汇率\n利差稳定可预期，汇率变动是主要风险源", "example": "借1亿日元（0.75%）→换63万美元→买3.63%美债→年赚利差约2.88%。若日元升值5%，汇率损失约3.15万美元，超过利差收益——触发平仓。", "links": [{"text": "BIS 季度回顾", "url": "https://www.bis.org/publ/qtrpdf/r_qt2403z.htm", "type": "article"}, {"text": "CFTC 持仓报告", "url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm", "type": "official"}]},
    {"title": "购买力平价 (PPP)", "summary": "长期汇率应反映两国物价水平之比，是均衡汇率的长期锚。", "detail": "基于'一价定律'：同样一篮子商品在各国用同种货币计价应相等。绝对PPP：S=P_本/P_外；相对PPP：汇率变动率≈两国通胀率之差。PPP是长期均衡锚，但中短期汇率大幅偏离。日元长期被低估是典型——OECD估算PPP公允约100-110，实际长期在130-160。巨无霸指数是PPP通俗版。", "formula": "绝对 PPP：S = P_本 / P_外\n相对 PPP：ΔS/S ≈ π_本 - π_外", "example": "日本巨无霸450日元，美国5.69美元，PPP隐含汇率≈79。实际159，日元被低估约50%。但PPP衡量5-10年长期均衡，短期几乎不成立。", "links": [{"text": "OECD PPP 数据库", "url": "https://www.oecd.org/en/data/datasets/oecd-economic-outlook.html", "type": "official"}, {"text": "经济学人巨无霸指数", "url": "https://www.economist.com/big-mac-index", "type": "article"}]},
    {"title": "有管理的浮动汇率制", "summary": "人民币汇率制度核心：市场供求+一篮子货币+逆周期调节。", "detail": "中国实行'以市场供求为基础、参考一篮子货币、有管理的浮动汇率制'。中间价=收盘汇率+一篮子货币变化+逆周期因子，日内波动±2%。央行三工具：中间价引导、外汇储备干预、资本管制。理解人民币必须理解这三层工具的相互作用。", "formula": "中间价 = 收盘价 + 一篮子货币变化 + 逆周期因子\n日内波动区间：中间价 ±2%", "example": "2026年8月'换锚'讨论：央行可能更强调CFETS篮子指数稳定而非USD/CNY双边，意味着人民币对美元弹性上升。", "links": [{"text": "PBOC 货币政策报告", "url": "http://www.pbc.gov.cn/zhengcehuobisi/125207/125227/index.html", "type": "official"}, {"text": "外汇交易中心 CFETS", "url": "https://www.chinamoney.com.cn/chinese/bkccpr/", "type": "official"}]},
    {"title": "央行外汇干预", "summary": "官方直接买卖外汇以影响汇率，是'最后手段'而非常规工具。", "detail": "分口头干预与实际干预。日本由财务省决策、BOJ执行。2026年7月美日联合干预，USD/JPY从163.86跌至159.16，两天升值约4.7%。美国参与是15年来首次。中国通过中间价与储备操作管理，较少直接干预。关键认知：干预只能改变节奏、难扭趋势，除非配合货币政策转向。", "example": "2026-07-29日元163.86→7月30-31日美日联合干预→7/31回落159.16。效果：短期改变节奏（约4.7%反弹），但利差（约280bp）未变，趋势性反转仍需等待。", "links": [{"text": "日本财务省干预", "url": "https://www.mof.go.jp/english/policy/international_policy/reference/fe_intervention/", "type": "official"}, {"text": "美国财政部外汇报告", "url": "https://home.treasury.gov/policy-issues/international/exchange-rate-policies", "type": "official"}]},
    {"title": "在岸 vs 离岸汇率 (CNY vs CNH)", "summary": "CNY受管制，CNH反映国际预期，价差是市场情绪风向灯。", "detail": "CNY：境内银行间市场，受中间价约束，波动±2%，反映境内供求与政策意图。CNH：境外（香港、伦敦、新加坡）自由交易，无中间价约束，波动更大，反映国际预期。CNH弱于CNY→海外看空；CNH强于CNY→海外看多。央行可通过在岸引导、离岸流动性管理影响价差。", "example": "2022年10月人民币承压时，CNH弱于CNY约200点，反映海外看空。2026年8月升值时CNH强于CNY，反映海外看多。研究人民币必看价差这一领先指标。", "links": [{"text": "香港金管局 CNH 数据", "url": "https://www.hkma.gov.hk/eng/data-publications-and-research/data-and-statistics/", "type": "official"}]},
    {"title": "蒙代尔-弗莱明模型（不可能三角）", "summary": "固定汇率、资本自由流动、独立货币政策三者不可兼得。", "detail": "一个经济体最多同时实现三项中两项：固定汇率、资本自由流动、独立货币政策。中国选择：独立货币政策+管理浮动+资本部分管制（用管制换取政策独立与汇率稳定的兼顾）。日本/美国：独立货币政策+资本自由流动+自由浮动（放弃汇率固定）。香港：联系汇率+资本自由流动（放弃独立货币政策，利率跟随美国）。这是理解各国汇率制度差异的最高层框架。", "formula": "三者取其二：\n固定汇率+资本自由流动 → 放弃独立货币政策\n独立货币政策+资本自由流动 → 放弃固定汇率\n独立货币政策+固定汇率 → 实施资本管制", "example": "中国2022-2023年降息（独立政策）+承受贬值压力（汇率弹性）+资本账户管理（管制）——正是不可能三角的现实映射。", "links": [{"text": "IMF 不可能三角解释", "url": "https://www.imf.org/external/pubs/ft/fandd/basics/triangle.htm", "type": "article"}]},
    {"title": "外汇储备与汇率稳定", "summary": "外汇储备是央行干预汇率的'弹药'，规模反映抵御冲击能力。", "detail": "央行持有的外币资产（主要是美欧日国债），用于干预市场、应对国际收支危机、支撑主权信用。中国外汇储备约3.2万亿美元（全球第一），是人民币汇率稳定的压舱石。日本约1.2万亿美元。关键指标：储备/月进口额、储备/短期外债。", "example": "2024年日本干预耗资约9.8万亿日元（约650亿美元），占其外汇储备约5%。即使储备雄厚，持续干预也有成本上限。", "links": [{"text": "SAFE 中国外汇储备", "url": "https://www.safe.gov.cn/safe/whsj/index.html", "type": "official"}, {"text": "IMF COFER 全球储备", "url": "https://www.imf.org/external/datamapper/COFER", "type": "official"}]},
    {"title": "货币的相关性与联动", "summary": "货币间存在基本面、贸易、套息驱动的联动，是分散与对冲的基础。", "detail": "货币相关性来源：（1）贸易联系（如澳元与中国需求、加元与美国经济）；（2）共同驱动（美元周期影响所有货币）；（3）套息关系（日元与高息货币反向）；（4）区域一体化（欧元与瑞郎、英镑）。相关性非固定，危机时往往趋近1（共振）。理解联动有助于构建对冲组合与识别异常信号。", "example": "风险事件中，日元、瑞郎、美元常同向走强（避险共振），而澳元、英镑、新兴货币同向走弱（风险资产共振）。", "links": [{"text": "BIS 有效汇率", "url": "https://www.bis.org/statistics/eer.htm", "type": "official"}]},
]

LEARNING_PATH = [
    {"step": 1, "title": "建立方向感", "task": "彻底弄懂'数值变大=谁升谁贬'，区分直接/间接标价。"},
    {"step": 2, "title": "理解利率平价", "task": "掌握利差与汇率的理论关系，这是分析框架的基石。"},
    {"step": 3, "title": "拆解套息交易", "task": "理解carry trade的建立、收益、风险与平仓机制。"},
    {"step": 4, "title": "区分主动与被动", "task": "学会用美元指数拆分'美元因素'与'本国因素'。"},
    {"step": 5, "title": "看懂央行操作", "task": "理解中间价、逆周期因子、干预的工具与意图。"},
    {"step": 6, "title": "掌握不可能三角", "task": "理解汇率制度选择的根本约束，看懂各国政策差异。"},
    {"step": 7, "title": "形成独立判断", "task": "基于数据与机制，对货币走势给出有依据的观点。"},
]

# ============================================================
# 对比思考：问题 + 学术参考分析
# 每个问题附参考分析，帮助形成观点（非标准答案）
# ============================================================
DISCUSSION_QUESTIONS = [
    {
        "category": "一、机制理解",
        "questions": [
            {"q": "为什么日元长期低利率会成为'融资货币'？这与日本经济结构有何关系？",
             "ref": "日元成为融资货币源于三重条件叠加：（1）日本央行自2013年实施量质宽松、2016年转入负利率，使日元成为G7中利率最低的货币，套息融资成本极低；（2）日本资本账户完全开放，资金可自由借出并跨境转换；（3）日元流动性高、汇率波动相对可控（风险事件外），使套息者能以较低风险溢价借入。从理论看，这是利率平价的镜像——低利率货币在UIP下应远期升水，但套息者赌的是短期贬值趋势延续，赚取利差与汇兑双收益。深层原因是日本经济的结构性特征：人口老龄化、低通胀、巨额国债约束（占GDP约260%），使央行难以退出超宽松政策，形成'低利率锁定'。"},
            {"q": "套息交易在什么条件下会反转？反转时汇率会出现什么特征？",
             "ref": "反转触发条件包括：（1）融资货币突然升值预期——如央行意外加息或干预；（2）风险偏好骤降（VIX飙升、地缘冲突、股市暴跌），套息者被迫平仓去杠杆；（3）利差收窄至套息收益无法覆盖汇率波动风险溢价。反转时呈现'急升缓贬'的不对称特征：平仓需买入日元偿还借款，集中买盘引发踩踏式急升，常在数日内吞噬数月贬值幅度。2024年8月与2026年7月的波动即典型。可监测CFTC日元净空头持仓、VIX、美日利差变化作为预警信号。"},
            {"q": "人民币'参考一篮子货币'与'单一盯美元'有何本质区别？优势是什么？",
             "ref": "本质区别在于汇率弹性的来源。单一盯美元下，USD/CNY固定，人民币对其他货币随美元波动——美元强势时人民币对欧元、日元被动升值，损害出口竞争力。参考一篮子货币（CFETS指数）下，央行目标是人民币对一篮子贸易伙伴货币的总体稳定，允许USD/CNY双边汇率更大波动——美元强势时人民币对美元贬值但对篮子稳定，实现'对美元浮动、对篮子稳定'。优势：汇率更反映贸易加权竞争力，减少对单一货币的过度依赖，增强货币政策独立性（符合不可能三角中'独立货币政策+资本管制+管理浮动'的选策）。"},
            {"q": "利率平价理论在现实中为何'失效'？是理论错了还是忽略了什么？",
             "ref": "理论未'失效'，而是模型假设过强。UIP假设无风险溢价、无交易成本、无资本管制、投资者风险中性。现实中：（1）汇率风险溢价时变且显著，高利率货币需向投资者补偿汇率风险，反而吸引资金流入推升即期汇率（远期贴水但即期升值）；（2）套息交易本身是风险行为，非无风险套利；（3）资本管制（如中国）阻断套利链条；（4）行为偏差与有限套利。因此UIP在中短期检验常被拒绝，但在长期（5年以上）均值回归上仍具解释力。这是'理论正确但条件不满足'的典型，分析时需识别哪些假设被违反。"},
        ],
    },
    {
        "category": "二、政策分析",
        "questions": [
            {"q": "日本央行不敢大幅加息的真正顾虑是什么？这种顾虑是否合理？",
             "ref": "三重约束：（1）财政可持续性——日本国债占GDP约260%，加息1个百分点将新增数万亿日元利息支出，挤压财政空间，可能引发主权债市场动荡；（2）经济脆弱性——日本内需复苏缓慢，加息将抑制投资与消费，可能重回通缩；（3）通胀性质判断——BOJ认为当前通胀输入型（能源、汇率）而非需求驱动，加息治标不治本且伤经济。顾虑有合理性，但也形成'政策陷阱'——越不敢加息，日元越弱，输入性通胀越强，加息压力越大。这是动态博弈而非静态最优，判断时需权衡短期稳定与长期失衡的权衡。"},
            {"q": "央行干预汇率是'稳市场'还是'扭曲市场'？支持与反对的理由各是什么？",
             "ref": "两面性并存。支持'稳市场'：（1）抑制过度波动与顺周期超调，减少实体汇兑风险；（2）防止套息交易踩踏引发系统性风险；（3）提供流动性缓冲。支持'扭曲市场'：（1）干预延迟必要的汇率调整，累积失衡；（2）消耗外汇储备，有成本上限；（3）若与基本面背离，干预效果短暂（如日本多次干预未扭转趋势）。关键判断标准：干预是否针对'无序波动'（合理）还是'对抗趋势'（扭曲）。学术共识：干预对短期波动有效，对中期趋势无效，除非配合货币政策转向。"},
            {"q": "美国为何罕见地联合日本干预？这背后是美国自身利益还是同盟考量？",
             "ref": "双重逻辑：（1）美国自身利益——日元无序贬值推升美元强势，损害美国出口竞争力，加剧贸易逆差；日元套息平仓可能冲击美债市场（日本是美国国债最大海外持有国之一）；过度贬值引发全球金融不稳定的外溢风险。（2）同盟与秩序考量——G7长期以来在外汇上协调，2026年干预延续'强势美元符合美国利益但无序贬值不可接受'的立场。罕见性表明汇率问题已升至地缘政治层面，但本质仍是利益计算而非纯粹利他。分析时需区分象征意义与实质效果。"},
            {"q": "中国'不可能三角'的选择是否可持续？资本账户开放的利弊？",
             "ref": "现行选策（独立货币政策+管理浮动+资本部分管制）在中期可持续，但存在张力：（1）资本管制效率随金融创新递减，地下渠道与贸易虚假定价可绕过；（2）管制的代价是资源配置扭曲、人民币国际化受限；（3）随开放深化，三元约束将收紧。资本账户开放利：提高资源配置效率、促进人民币国际化、降低融资成本；弊：增加资本流动波动性、削弱货币政策独立性、放大外部冲击。长期看，随人民币国际化推进，中国可能渐进开放资本账户并向更浮动汇率过渡，但路径依赖决定了渐进性。可持续性取决于改革节奏与外部冲击应对。"},
        ],
    },
    {
        "category": "三、观点形成",
        "questions": [
            {"q": "日元贬值是'日本问题'还是'美元问题'？如何用数据区分？",
             "ref": "可用回归数据区分。本站回归显示美日利差解释了USD/JPY变动的69%，剩余31%来自日本结构性因素（贸易逆差、套息规模、避险属性减弱）。判断方法：将USD/JPY变动分解为'美元指数变动贡献'与'日元特异性变动贡献'。若日元相对一篮子货币（如BIS有效汇率）贬值幅度大于美元指数升幅，则日元自身因素为主。2022-2024年日元贬值中美元因素与日本因素约各占一半，2025年后日本结构性因素占比上升。结论是'两者皆有，权重时变'，不宜简单归因。"},
            {"q": "人民币升值是'被动'还是'主动'？两种判断对政策含义有何不同？",
             "ref": "分解方法：比较USD/CNY变动与美元指数（DXY）变动。若USD/CNY升值幅度≈DXY贬值幅度，则为被动（美元因素主导）；若USD/CNY升值大于DXY贬值，则有主动成分（基本面、资金流入）。2026年8月的情况两者兼有：美联储降息推升美元走弱（被动），但经常账户顺差与央行引导提供主动支撑。政策含义不同：被动升值随美元周期逆转，主动升值更具持续性。建议结合CFETS指数判断——若CFETS稳定而USD/CNY升值，主要为被动；若CFETS也走强，则有主动成分。"},
            {"q": "若美日利差收窄至100bp，日元是否会反转？还需要什么条件？",
             "ref": "利差收窄是必要非充分条件。100bp利差下套息收益边际下降，但反转还需：（1）利差预期进一步收窄的共识（否则套息者继续持有）；（2）风险事件触发平仓；（3）日本央行加息路径明确化。历史参考：2013年利差约100bp时日元并未反转（因QQE预期强化贬值）。回归模型外推：利差100bp对应USD/JPY约108，但实际偏离取决于风险溢价。结论：利差收窄降低贬值动力，但反转需配合预期反转与触发事件，不宜线性外推。"},
            {"q": "人民币持续升值对出口企业、资产价格、货币政策各有什么影响？",
             "ref": "（1）出口企业——汇兑损失压缩利润，劳动密集型与低毛利出口受冲击最大，但促进产业升级与高附加值出口；（2）资产价格——本币升值吸引外资流入，推升股债资产价格，但也积累资本流动逆转风险；（3）货币政策——升值降低输入性通胀，给货币政策更多宽松空间，但升值过快会抑制出口与就业，需央行通过中间价平滑。净效应取决于升值速度与基本面：渐进升值有利结构调整，急速升值有害经济稳定。这是升值'度'的问题，而非简单的升贬好坏。"},
            {"q": "日元'避险属性减弱'是暂时的还是结构性的？如何验证？",
             "ref": "倾向结构性。减弱原因：（1）经常账户恶化削弱避险基础（传统避险货币需经常账户顺差支撑）；（2）套息交易规模过大，避险买盘被掩盖；（3）BOJ超宽松政策使日元不再被视为'安全港'。验证方法：观察地缘风险事件期间日元是否仍升值。2022-2026年多次风险事件日元反而贬值，支持结构性判断。但若BOJ政策正常化推进、经常账户修复，避险属性可能部分恢复——这是动态变量而非永久定性，需持续跟踪验证。"},
        ],
    },
    {
        "category": "四、研究延伸",
        "questions": [
            {"q": "如何用利率平价理论检验当前日元汇率是否被高估/低估？",
             "ref": "计算UIP隐含汇率与实际汇率偏离度。方法：（1）选取基期（如长期PPP均衡）；（2）按UIP累计利差得到理论汇率路径；（3）比较实际汇率与理论路径。若实际汇率显著弱于UIP隐含（如当前日元），则存在'低估'，但低估可能反映合理风险溢价而非套利机会。需结合PPP（长期锚）与UIP（中期）交叉验证。注意：偏离可持续数年，'低估'不等于'即将反转'，需结合触发条件判断时点。"},
            {"q": "CFETS人民币汇率指数与USD/CNY的差异说明了什么？",
             "ref": "CFETS是人民币对一篮子贸易伙伴货币的加权指数，USD/CNY是双边汇率。差异说明'美元因素'的剥离：若CFETS稳定而USD/CNY贬值，说明人民币对非美货币升值（篮子内欧元、日元等相对美元贬值）。这是判断'主动vs被动'的关键工具。2026年'换锚'讨论即强调从盯USD/CNY转向盯CFETS，意味着人民币对美元弹性上升但对篮子稳定。"},
            {"q": "在岸-离岸价差能否作为市场情绪的领先指标？如何验证？",
             "ref": "可作为市场情绪的同步/弱领先指标。CNH不受中间价约束，更反映国际预期。价差扩大（CNH弱于CNY）预示贬值压力上升，往往领先中间价调整。验证方法：计算价差序列与后续USD/CNY变动的相关性，做Granger因果检验。注意：央行可通过离岸流动性管理（发行央票、收紧CNH流动性）影响价差，因此价差也受政策干预扰动，需结合离岸流动性指标（如CNH HIBOR）综合解读。"},
            {"q": "如何用回归分析量化利差对汇率的解释力？R²说明什么？",
             "ref": "建模步骤：（1）确定变量（利差为X，汇率或汇率变动为Y）；（2）选择样本期与频率（年度/季度/月度）；（3）OLS估计并检验系数显著性（t检验）；（4）诊断残差自相关、结构性变化（Chow检验）。R²衡量模型对Y方差的解释比例，但高R²不等同因果关系——可能存在共同驱动变量（如风险偏好同时影响利差与汇率）。建议补充协整分析（长期均衡）与误差修正模型（短期调整），而非仅依赖单方程OLS。这是计量经济学方法论的基本严谨性要求。"},
        ],
    },
]

DATA_SOURCES_DETAIL = [
    {"name": "美联储 G.5A 外汇汇率（年度均值）", "series": "AEXJPUS / AEXCHUS", "url": "https://fred.stlouisfed.org/series/AEXJPUS", "desc": "USD/JPY、USD/CNY 年度日均均值"},
    {"name": "美联储 H.10 外汇汇率（日度）", "series": "DEXJPUS / DEXCHUS", "url": "https://www.federalreserve.gov/releases/h10/current/", "desc": "当前汇率快照来源"},
    {"name": "美联储 H.15 选定利率", "series": "RIFSPFFNA / FEDFUNDS", "url": "https://fred.stlouisfed.org/series/FEDFUNDS", "desc": "美国联邦基金有效利率"},
    {"name": "OECD 日本隔夜拆借利率", "series": "IRSTCI01JPM156N", "url": "https://fred.stlouisfed.org/series/IRSTCI01JPM156N", "desc": "日本无担保隔夜拆借利率"},
    {"name": "欧洲央行 Frankfurter API", "series": "ECB 参考汇率", "url": "https://frankfurter.app/", "desc": "EUR/GBP/AUD/CHF 实时与历史数据"},
    {"name": "中国人民银行", "series": "—", "url": "http://www.pbc.gov.cn/", "desc": "LPR、中间价、货币政策报告"},
]
