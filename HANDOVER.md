# Parite · 多货币研究平台 — 交接与协作手册

> 本文件是给「接手这个项目的人」看的——无论是另一个 AI、新协作者，还是几个月后回来改东西的自己。
> 读完这一份就能上手操作，不用翻历史对话。

---

## 0. 一分钟速览

- **项目本质**：基于 Flask 的多货币研究网站（深色学术风），覆盖 7 种货币：日元/人民币/欧元/英镑/澳元/瑞郎/美元
- **线上地址**：https://parite.top
- **GitHub 仓库**：https://github.com/snowjqm-sys/parite-forex
- **默认分支**：`main`
- **本地路径**（你这台机器）：`C:\Users\snowj\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a73eba14b017102fbc7aad4\forex_website`
- **技术栈**：Python + Flask + Plotly.js（本地）+ Cloudflare CDN + Vercel Serverless
- **启动命令**：双击 `run.bat`，浏览器开 `http://127.0.0.1:5000`

---

## 1. 项目结构（实际目录）

```
forex_website/
├── app.py                  # Flask 主应用（路由、API、缓存策略、实时汇率代理）
├── data.py                 # 所有静态数据（货币、利率、报告、概念……）
├── api/index.py            # Vercel Serverless 入口（WSGI 适配）
├── vercel.json             # Vercel 部署配置
├── requirements.txt        # Python 依赖（目前只有 flask）
├── run.bat                 # 本地启动脚本（双击即可）
├── share.bat               # Cloudflare 隧道临时公网分享脚本
├── cloudflared.exe         # Cloudflare 隧道工具（.gitignore 排除，不入库）
├── README.md               # 面向使用者的说明
├── HANDOVER.md             # 本文件（交接与协作）
├── announcements.json      # 首页公告栏（含日报/周报链接）
├── admin_config.json       # 管理员密码（.gitignore 排除，本地配置）
├── ai_config.json          # AI 助手 API Key（.gitignore 排除，本地配置）
├── feedback.json           # 用户反馈本地存储（.gitignore 排除）
├── .env.local              # 环境变量（.gitignore 排除）
├── _futures_ref.txt        # 期货参考资料（开发时查阅）
│
├── static/
│   ├── css/style.css       # 深色主题样式表（主样式）
│   └── js/
│       └── plotly-2.35.2.min.js  # Plotly 本地库（务必不要换回 CDN）
│
└── templates/
    ├── base.html           # 基础骨架（导航、页脚、品牌、AI 助手壳）
    ├── index.html          # 首页（市场总览 + 公告 + 货币卡片）
    ├── basics.html         # 外汇基础概念页
    ├── currency.html       # 货币研究页（七个货币共用一个模板，按 CODE 渲染）
    ├── comparison.html     # 对比与自由思考页
    ├── explorer.html       # 数据探索页
    └── report.html        # 日报/周报详情页
```

---

## 2. 数据在哪里（核心！）

**所有静态数据都集中在 `data.py` 这一个文件里**。下面是字段索引，改数据按图索骥即可。

### 2.1 货币核心数据 `CURRENCIES`（第 101 行起）

每个货币的完整信息，按小写代码组织：`jpy / cny / eur / gbp / aud / chf / usd`。

每个货币对象的关键字段：

| 字段 | 含义 | 示例（JPY）|
|------|------|-----------|
| `code` / `name` / `name_en` | 货币代码与名称 | `JPY` / `日元` |
| `pair` / `pair_label` | 货币对 | `USD/JPY` / `美元兑日元` |
| `category` | 货币类别 | `融资货币` |
| `current.rate` | 当前汇率（需定期更新） | `153.27` |
| `current.date` | 当前汇率日期 | `2026-09-09` |
| `current.source` | 数据来源标注 | `Frankfurter/ECB` |
| `trend` / `trend_dir` | 趋势描述 | `长期贬值` / `up` |
| `core_insight` | 一句话核心洞察 | —— |
| `intro` | 货币介绍段落（首页卡片用） | —— |
| `history` | 年度历史汇率+事件（历史图数据源） | 列表，含 date/rate/event |
| `drivers` | 驱动因素列表（加权分类） | 见下 |
| `questions` | 思考题 | —— |

**`drivers` 字段结构**（驱动因素，货币页核心内容）：

```python
{
    "title": "美日利差持续高位",
    "weight": "核心驱动",           # 核心驱动/基本面驱动/结构性因素/放大器/近期事件/情境因素
    "mechanism": "……",              # 作用机制详述
    "key_point": "……",              # 关键判断点
    "links": [                       # 参考链接
        {"text": "美联储 H.15", "url": "https://...", "type": "official"}
    ]
}
```

### 2.2 实时汇率配置 `LIVE_PAIRS`（第 887 行）

定义每个货币页右上角"实时汇率小窗"拉取哪个货币对。例如：

```python
"jpy": {"from": "USD", "to": "JPY"}
```

实时汇率走三层 fallback：Frankfurter API → exchangerate.host → `data.py` 里的 `current.rate` 静态兜底。前两层失败时前端会显示黄色提示横幅。

### 2.3 利率数据 `INTEREST_RATES`（第 77 行起）

各国政策利率年度序列，用于利差对比图。包含 `country`、`code`、`rate`（年度均值）、`year` 等字段。

### 2.4 其他数据表（按需修改）

| 变量名 | 行号附近 | 内容 |
|--------|---------|------|
| `MARKET_SNAPSHOT` | 19 | 首页市场快照 |
| `HOME_HERO` | 37 | 首页 Hero 文案 |
| `RATE_RADAR` | 47 | 利率雷达（首页小卡片） |
| `RECENT_UPDATES` | 59 | 首页"近期更新"列表 |
| `CURRENCY_NAV` | 864 | 货币页 TOC 导航结构 |
| `CURRENCY_DEEP_ANALYSIS` | 900 | 货币深度分析补充段落 |
| `FOREX_CONCEPTS` | 1205 | 外汇基础概念（10 个） |
| `LEARNING_PATH` / `LEARNING_STAGES` | 1218 / 1308 | 学习路径步骤与阶段 |
| `DISCUSSION_QUESTIONS` | 1318 | 对比页思考题 |
| `DATA_SOURCES_DETAIL` | 1375 | 数据来源详表 |
| `FED_RATE_HISTORY` | 1389 | 美联储利率历史 |
| `US_TREASURY_HISTORY` | 1416 | 美债历史 |
| `DXY_COMPONENTS` | 1437 | 美元指数构成 |
| `FED_POLICY_CYCLES` | 1447 | 美联储政策周期 |
| `FOREX_FUTURES_*` | 1459-1690 | 外汇期货相关（介绍/合约/保证金/策略/术语） |
| `GLOSSARY` | 1713 | 术语表 |
| `FX_EXCHANGES` / `FX_EXCHANGES_SUMMARY` | 1756 / 1920 | 全球外汇交易所 |
| `BOND_*` | 1935-2107 | 债券市场（收益率曲线/利差/概览/概念） |
| `RISK_FREE_RATES` / `CREDIT_SPREADS` / `CHINA_CREDIT_BONDS` / `CREDIT_CONCEPTS` | 2107-2333 | 信用债相关 |
| `DAILY_REPORTS` | 2333 | 日报列表（详情页数据源） |
| `WEEKLY_REPORTS` | 2517 | 周报列表（详情页数据源） |

### 2.5 公告 `announcements.json`（项目根目录）

首页公告栏数据。每条结构：

```json
{
    "date": "2026-09-10",
    "title": "美债举措深度分析",
    "summary": "……",
    "link": "/report/daily/2026-09-10"   // 可选，有则显示"→ 点击查看"
}
```

### 2.6 日报/周报内容

日报在 `DAILY_REPORTS`（第 2333 行），周报在 `WEEKLY_REPORTS`（第 2517 行）。每条带 `id`、`date`、`title`、`content`（支持多段落、小标题）。访问路由：`/report/daily/<id>` 和 `/report/weekly/<id>`。

---

## 3. 本地调试操作清单

### 3.1 启动本地服务

**方式 A（推荐）**：双击 `run.bat`

**方式 B（命令行）**：

```powershell
cd "C:\Users\snowj\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a73eba14b017102fbc7aad4\forex_website"
python app.py
```

启动后浏览器开 `http://127.0.0.1:5000`。

### 3.2 改完代码看效果

Flask 已禁用 auto-reload（`use_reloader=False`），所以**改代码不会自动生效**，必须手动重启：

1. 在命令行窗口按 `Ctrl+C` 停掉旧进程
2. 再次双击 `run.bat`（或 `python app.py`）
3. 浏览器按 `Ctrl+Shift+R` 强制刷新（避免缓存）

### 3.3 端口被占用怎么办

如果报 "Address already in use" 或 5000 端口被占：

```powershell
# 查找占用 5000 端口的进程
netstat -ano | findstr ":5000"
# 用 PID 杀进程（把 <PID> 换成上一步看到的数字）
taskkill /PID <PID> /F
```

或者直接改 `app.py` 最后一行的 `port=5000` 成别的端口（如 8080）。

也可以用任务管理器 → 详细信息 → 找 `python.exe` → 结束任务。

### 3.4 改数据的标准流程

1. 编辑 `data.py`，找到对应变量（参考第 2 节的索引）
2. 改完保存
3. 重启服务（`Ctrl+C` → `run.bat`）
4. `Ctrl+Shift+R` 刷新浏览器查看

### 3.5 改页面样式的标准流程

- **改颜色/字体/动画/布局**：`static/css/style.css`
- **改 HTML 结构**：`templates/` 下对应模板
- **货币页特殊说明**：`templates/currency.html` 是七种货币共用的模板，按 URL 里的 `CODE`（如 `/currency/jpy`）动态渲染。改一处影响所有七个货币页。
- **改导航/页脚/品牌**：`templates/base.html`

### 3.6 临时分享给他人（不部署）

1. 双击 `run.bat` 启动
2. 双击 `share.bat` 创建 Cloudflare 临时隧道
3. 把出现的 `https://xxx.trycloudflare.com` 链接发给别人
4. 关闭 `share.bat` 窗口即停止分享

注意：每次重启 `share.bat` 链接会变，无 SLA 保证，仅适合临时演示。

---

## 4. GitHub 仓库与协作

### 4.1 仓库信息

- **地址**：https://github.com/snowjqm-sys/parite-forex
- **默认分支**：`main`
- **当前协作者**：只有仓库 owner（`snowjqm-sys`）

### 4.2 推送本地改动到 GitHub

```powershell
# 在项目根目录
git add .                            # 暂存所有改动
git commit -m "feat: 你的改动说明"    # 提交（信息用中文英文都行）
git push origin main                 # 推送到 GitHub
```

推送后 Vercel 会自动构建部署，约 1-2 分钟后 parite.top 生效。

### 4.3 和别人一起协作

**步骤 1：邀请协作者**

1. 打开 https://github.com/snowjqm-sys/parite-forex/settings/access
2. 点 "Add people"
3. 输入对方的 GitHub 用户名或邮箱
4. 权限选 "Write"（能推送代码但不能改设置）
5. 对方邮件接受邀请即可

**步骤 2：协作者克隆项目**

```bash
git clone https://github.com/snowjqm-sys/parite-forex.git
cd parite-forex
pip install -r requirements.txt
python app.py
```

**步骤 3：协作者本地配置（必须！）**

以下文件被 `.gitignore` 排除，不会进仓库，协作者需要自己创建：

- `ai_config.json`：AI 助手的 API Key 配置（格式问 owner 或看 `app.py` 的 `/ai-config` 路由）
- `admin_config.json`：管理员密码（格式同上）
- `.env.local`：环境变量（如邮件 SMTP 授权码）

**步骤 4：协作工作流（推荐用 Pull Request）**

```bash
# 协作者新建分支
git checkout -b feature/新增功能
# 改代码……
git add .
git commit -m "feat: 新增 xxx"
git push origin feature/新增功能
# 然后去 GitHub 网页上发起 Pull Request，owner 审核后合并到 main
```

如果只有 1-2 人简单协作，也可以直接推 main 分支，但用 PR 更安全。

### 4.4 拉取最新代码

```powershell
git pull origin main
```

有冲突时先 `git stash`（暂存本地改动）→ `git pull` → `git stash pop`（恢复改动）→ 手动解决冲突。

### 4.5 常用 Git 命令速查

| 操作 | 命令 |
|------|------|
| 查看改动状态 | `git status` |
| 查看具体改动 | `git diff` |
| 暂存所有改动 | `git add .` |
| 提交 | `git commit -m "说明"` |
| 推送 | `git push origin main` |
| 拉取最新 | `git pull origin main` |
| 新建分支 | `git checkout -b 分支名` |
| 切回 main | `git checkout main` |
| 查看提交历史 | `git log --oneline` |

---

## 5. 部署到 parite.top

### 5.1 自动部署（推荐）

本地 push 到 GitHub `main` 分支后，Vercel 自动构建部署。约 1-2 分钟生效。

查看部署状态：https://vercel.com/dashboard（登录绑定的 Vercel 账号）

### 5.2 部署配置

- **入口文件**：`api/index.py`（WSGI 适配器）
- **部署配置**：`vercel.json`（已配置 regions=hkg1 香港，includeFiles 包含 py/html/css/js/json）
- **环境变量**：Vercel Dashboard → 项目 → Settings → Environment Variables 里设置（如 SMTP 授权码、AI API Key、管理员密码）

### 5.3 部署后验证

1. 访问 https://parite.top 看首页正常
2. 访问 https://parite.top/currency/JPY 看货币页
3. F12 控制台无红色报错
4. 图表正常渲染
5. 实时汇率小窗有数据

### 5.4 Cloudflare 配置（一般不用动）

- DNS：`parite.top` CNAME 到 Vercel
- CDN：Brotli 压缩、Auto Minify、Early Hints、Always Use HTTPS 已启用
- 最低 TLS 版本：1.2
- Page Rules：`/api/*`、`/admin*`、`/ai-config*` 绕过缓存；其他路由 Edge TTL 5 分钟

---

## 6. 关键约束（务必遵守）

这些是项目历史踩坑总结的硬约束，改代码时必须留意：

### 6.1 数据

- 所有数据必须来自官方权威源（FRED、PBOC、BOJ、美联储、BIS、IMF、SAFE、Frankfurter API）
- 不许编造数据
- 静态数据 `data.py` 要定期更新当前汇率（至少每月一次），否则线上数据会过时
- 当前年份的历史汇率会自动从 Frankfurter API 覆盖，但历史年份必须手动维护

### 6.2 图表

- Plotly.js 必须用本地文件 `static/js/plotly-2.35.2.min.js`，**不能换回 CDN**（CDN 不稳定）
- 图表标题不要自动编号（用户手动加）
- 图表要高分辨率（DPI 400）
- x 轴文字不能重叠
- 图表渲染必须用 `safePlotly` 包装函数处理异常

### 6.3 缓存

- 实时汇率 API 永不缓存（`/api/ticker`、`/api/live`、`/api/currency/<code>/history|monthly|daily`）
- 静态数据 API 缓存 10 分钟（`/api/snapshot`、`/api/rates`、`/api/currencies`、`/api/regression`）
- 管理员和 AI 配置页永不缓存
- 缓存白名单在 `app.py` 顶部 `_NO_CACHE_API_PREFIXES` 和 `_STATIC_API_PREFIXES`

### 6.4 样式

- 深色学术风（纯黑背景 `#000`，白色文本，灰色半透明线条）
- 极简 emoji
- 字体：标题 Lora + Noto Serif SC，正文 Nunito，行距 1.75
- 页面加载淡入动画（0.9s ease-out）
- 货币研究页用日记式可展开卡片（`.journal-card`）
- AI 助手名"蓝莓"，Persona 5 游戏风格对话框

### 6.5 实时汇率

- 三层 fallback：Frankfurter → exchangerate.host → data.py 静态
- 指数退避重试：0.5s → 1s，最多 3 次
- 60 秒内存缓存
- fallback 模式前端显示黄色提示横幅
- 颜色：涨红跌绿（中国习惯），`--accent-jpy=#ff6b6b`（红/涨）、`--accent-cny=#3fb950`（绿/跌）

---

## 7. 常见操作速查

| 我想…… | 怎么做 |
|--------|--------|
| 改某个货币的当前汇率 | `data.py` 第 101 行起 `CURRENCIES`，找对应货币的 `current.rate` 和 `current.date` |
| 改某个货币的介绍文字 | 同上，改 `intro` 字段 |
| 改某个货币的驱动因素 | 同上，改 `drivers` 列表 |
| 改历史走势图数据 | `data.py` 对应货币的 `history` 列表 |
| 加一篇日报 | `data.py` 第 2333 行 `DAILY_REPORTS`，按现有格式加一条 |
| 加一篇周报 | `data.py` 第 2517 行 `WEEKLY_REPORTS` |
| 改首页公告 | `announcements.json`（项目根目录） |
| 改某个货币的实时汇率对 | `data.py` 第 887 行 `LIVE_PAIRS` |
| 改利率数据 | `data.py` 第 77 行 `INTEREST_RATES` |
| 改网站颜色/字体 | `static/css/style.css` |
| 改导航或页脚 | `templates/base.html` |
| 改货币页布局 | `templates/currency.html` |
| 改首页布局 | `templates/index.html` |
| 加新页面 | 在 `templates/` 加 html + 在 `app.py` 加路由 |
| 加新 API | 在 `app.py` 加 `@app.route`，实时类加到 `_NO_CACHE_API_PREFIXES`，静态类加到 `_STATIC_API_PREFIXES` |
| 部署到线上 | `git push origin main`，Vercel 自动部署 |
| 临时分享给别人 | 双击 `run.bat` + `share.bat`，发 trycloudflare 链接 |
| 拉取最新代码 | `git pull origin main` |
| 重启服务 | 命令行 `Ctrl+C` → 双击 `run.bat` |
| 清浏览器缓存 | `Ctrl+Shift+R` |

---

## 8. 接手 Checklist（给新 AI / 新人）

接到这个项目后，按顺序做：

- [ ] 读本文件（`HANDOVER.md`）
- [ ] 读 `README.md`（面向使用者的说明）
- [ ] 看 `app.py` 顶部缓存策略部分（第 50-115 行附近）
- [ ] 看 `data.py` 的 `CURRENCIES` 结构（第 101 行起）
- [ ] 启动一次本地服务，访问 `http://127.0.0.1:5000` 确认正常
- [ ] 访问 `/currency/JPY` 确认货币页、图表、实时汇率正常
- [ ] 访问 `https://parite.top` 确认线上版本正常
- [ ] 如有疑问，查 `project_memory.md`（在 `c:\Users\snowj\.trae-cn\memory\projects\` 下，包含所有历史踩坑记录）

---

## 9. 联系与历史

- **仓库 owner**：`snowjqm-sys`
- **反馈邮箱**：snowjqm@163.com（网站反馈表单也会发到这个邮箱）
- **历史踩坑记录**：`c:\Users\snowj\.trae-cn\memory\projects\-snowj-AppData-Roaming-TRAE-SOLO-CN-ModularData-ai-agent-work-mode-projects-6a73eba14b017102fbc7aad4-pqn4b5--p2-ad2d026c4bc7ae42f40f\project_memory.md`（本机路径，包含所有硬约束和过往 bug 修复经验）

---

## 10. 多 Agent 协作交接模板

本项目可能由多个 AI agent（如当前 agent、WorkBuddy 等）分阶段接力开发。
为了让下一个 agent 快速进入状态，每次交接时**复制下方模板，填好后作为新会话的第一条消息发给下一个 agent**。

### 10.1 交接信息模板（复制填写）

```
你接手一个叫 Parité 的多货币研究网站项目。请先读 HANDOVER.md 熟悉项目，然后再执行下方任务。

【项目路径】
C:\Users\snowj\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a73eba14b017102fbc7aad4\forex_website

【必读文档】
1. HANDOVER.md（项目根目录）— 结构、数据位置、操作清单、硬约束
2. project_memory.md（c:\Users\snowj\.trae-cn\memory\projects\ 下对应项目文件夹）— 历史踩坑与硬约束全集

【上一步进展】
- 上一个 agent（或我）做了：________（简述，比如"加了 KRW 货币页，改了 data.py 和 currency.html"）
- 改动的文件：________（列出，比如 data.py / templates/currency.html / static/css/style.css）
- 是否已提交 push：是 / 否
- 当前 git 分支：main / ________

【你的任务】
________（明确描述，比如"改首页布局，把公告栏移到货币卡片上方"）

【涉及的文件】
________（如果知道，指明要改哪些文件；不知道就让 agent 自己判断）

【约束提醒】
- 改代码前先 `git pull origin main` 拿到最新版本
- 改完用 git 提交推送，让 Vercel 自动部署
- 遵守 HANDOVER.md 第 6 节的硬约束（数据来源、Plotly 本地化、缓存策略、深色主题等）
- 不要同时和别的 agent 改同一个文件，会冲突

【验证方式】
________（怎么确认做对了，比如"访问 http://127.0.0.1:5000 看首页公告栏位置"）
```

### 10.2 交接时的注意事项

**给下一个 agent 之前，确认这几点**：

- [ ] 上一步改动已 `git add` + `git commit` + `git push origin main`（不然下一个 agent 拉不到）
- [ ] 本地服务已停掉（`Ctrl+C` 关掉 run.bat 窗口，避免端口占用）
- [ ] 交接信息里"上一步进展"和"你的任务"填清楚了
- [ ] 如果上一步没 push，明确告诉下一个 agent"先不要 git pull，我在本地改了还没提交"

**避免冲突的分工原则**：

| 场景 | 是否安全 | 说明 |
|------|---------|------|
| 两个 agent 改不同文件 | ✅ 安全 | 比如一个改 data.py，一个改 style.css |
| 两个 agent 改同一文件不同部分 | ⚠️ 有风险 | 可能自动合并成功，也可能冲突 |
| 两个 agent 改同一文件同一区域 | ❌ 会冲突 | 必须串行，前一个 push 后后一个再 pull 改 |
| 两个 agent 同时改 + 同时 push | ❌ 危险 | 后 push 的会被拒，需要先 pull 再 push |

**推荐的分工方式**：

- 按"模块"分，不按"层"分。比如"你做货币页"（涉及 data.py + currency.html + style.css）比"你做数据层"（只改 data.py）更不容易和别的 agent 撞
- 如果两个 agent 都要改 data.py，让它们改不同的货币字段（比如一个改 JPY，一个改 CNY），git 通常能自动合并
- 每次交接时，把上一步改了哪些文件明确告诉下一个 agent，让它判断会不会撞

### 10.3 快速启动新 agent 的最小信息

如果你嫌上面模板太长，最少最少告诉下一个 agent 这三行：

```
接手 Parité 多货币网站项目。路径：C:\Users\snowj\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a73eba14b017102fbc7aad4\forex_website
请先读 HANDOVER.md 和 project_memory.md 熟悉项目与硬约束。
任务：________（你的任务描述）
```

读完两个文档 + git pull，它就能接上进度了。
