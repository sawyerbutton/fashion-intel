# 潮流情报系统 — Project Brief
> 把这份文档粘贴给 Claude Code 作为项目开发的完整上下文

---

## 项目目标

搭建一套**自动化潮流情报爬虫系统**，核心功能：
1. 多平台抓取偶像/KOL 穿搭图片及社媒数据
2. 用 Gemini Vision API 自动识别图片中的潮牌单品
3. 趋势评分 + 爆款预测，输出选品建议
4. Streamlit 可视化看板 + Telegram 预警推送

**业务场景**：针对 Stussy 等街头潮牌，追踪粉丝经济带货链路，支撑选品决策和小红书/B站内容选题。

---

## 技术栈

| 模块 | 技术选型 | 说明 |
|------|----------|------|
| 爬虫 | Playwright + requests | 优先用 Playwright 处理动态页面 |
| 图片识别 | Google Gemini Vision API | 已有 API Key |
| 趋势分析 | Google Gemini Pro API | 同一个 Key 复用 |
| 数据存储 | SQLite（本地开发） | 后期可迁移 Supabase |
| 自动化调度 | Python APScheduler | 不用 n8n，纯 Python |
| 可视化看板 | Streamlit | 快速出界面 |
| 预警推送 | Telegram Bot API | 免费，配置简单 |
| 环境配置 | python-dotenv (.env 文件) | API Key 不写死在代码里 |

**Python 版本**：3.11+
**包管理**：pip + requirements.txt

---

## 项目目录结构

```
fashion-intel/
├── .env                        # API Keys（不提交 git）
├── .env.example                # Key 模板（提交 git）
├── requirements.txt
├── README.md
│
├── config/
│   └── settings.py             # 从 .env 加载配置 + 关键词/品牌常量
│
├── crawlers/
│   ├── __init__.py
│   ├── base_crawler.py         # 基类，统一接口
│   ├── xiaohongshu.py          # 小红书爬虫
│   ├── instagram.py            # Instagram 爬虫
│   └── dewu.py                 # 得物价格爬虫
│
├── analyzers/
│   ├── __init__.py
│   ├── gemini_vision.py        # 图片单品识别
│   └── trend_scorer.py         # 趋势评分逻辑
│
├── database/
│   ├── __init__.py
│   ├── models.py               # SQLite 表结构定义
│   └── db.py                   # 数据库连接和 CRUD 操作
│
├── dashboard/
│   └── app.py                  # Streamlit 看板
│
├── notifier/
│   └── telegram_bot.py         # 预警推送
│
├── scheduler.py                # 定时任务主入口
└── main.py                     # 手动运行入口（调试用）
```

---

## 数据库表结构（SQLite）

### 表 1：raw_posts（爬取的原始帖子）
```sql
CREATE TABLE raw_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT NOT NULL,          -- 'xiaohongshu' | 'instagram' | 'dewu'
    post_id     TEXT UNIQUE,            -- 平台原始 ID，防重复
    url         TEXT,
    title       TEXT,
    content     TEXT,
    image_urls  TEXT,                   -- JSON 数组，存多张图片 URL
    likes       INTEGER DEFAULT 0,
    comments    INTEGER DEFAULT 0,
    author      TEXT,
    keyword     TEXT,                   -- 触发抓取的关键词
    crawled_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_analyzed INTEGER DEFAULT 0       -- 0=待分析, 1=已分析
);
```

### 表 2：analyzed_items（Gemini 识别出的单品）
```sql
CREATE TABLE analyzed_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         INTEGER REFERENCES raw_posts(id),
    image_url       TEXT,
    brand           TEXT,               -- 识别出的品牌，如 'Stussy'
    item_type       TEXT,               -- 如 'hoodie' | 'tee' | 'cap'
    colorway        TEXT,               -- 如 'black/white'
    logo_visible    INTEGER DEFAULT 0,  -- 1=logo清晰可见
    confidence      REAL,               -- 识别置信度 0.0-1.0
    raw_response    TEXT,               -- Gemini 原始 JSON 响应
    analyzed_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 表 3：trend_scores（每日趋势评分快照）
```sql
CREATE TABLE trend_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    brand           TEXT,
    item_type       TEXT,
    score_date      DATE,
    mention_count   INTEGER DEFAULT 0,  -- 当日提及次数
    avg_likes       REAL DEFAULT 0,     -- 相关帖子平均点赞
    hot_score       REAL DEFAULT 0,     -- 综合热度分 0-100
    breakout_prob   REAL DEFAULT 0,     -- 爆款概率 0-100
    related_idols   TEXT,               -- JSON 数组，关联艺人
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 表 4：alerts_log（预警推送记录）
```sql
CREATE TABLE alerts_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type  TEXT,                   -- 'price_spike' | 'mention_surge' | 'idol_spotted'
    brand       TEXT,
    item_type   TEXT,
    message     TEXT,
    sent_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 环境变量（.env 文件格式）

```env
# Google Gemini
GEMINI_API_KEY=your_gemini_api_key_here

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# 数据库路径
DB_PATH=./data/fashion_intel.db
```

---

## 核心配置（config/settings.py）

```python
import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DB_PATH = os.getenv("DB_PATH", "./data/fashion_intel.db")

# 监控关键词
KEYWORDS = [
    "Stussy 穿搭",
    "Stussy 同款",
    "街头潮牌",
    "男团同款穿搭",
]

# 监控品牌
TARGET_BRANDS = [
    "Stussy",
    "Supreme",
    "BAPE",
    "Carhartt",
    "Palace",
]

# 爆款预警阈值
ALERT_THRESHOLDS = {
    "mention_surge_pct": 50,    # 24h内提及量增幅 >50% 触发预警
    "hot_score_min": 75,        # 热度分 >75 触发推送
    "breakout_prob_min": 70,    # 爆款概率 >70% 推送
}

# 调度频率（小时）
CRAWL_INTERVAL_HOURS = 6
ANALYSIS_INTERVAL_HOURS = 1
SCORE_INTERVAL_HOURS = 24
```

---

## Gemini Vision 调用规范

### 图片单品识别 Prompt
```python
VISION_PROMPT = """
你是一个专业的街头潮牌穿搭分析师。

分析图片中所有可见的服装和配饰单品，严格按照以下 JSON 格式返回，不要输出任何其他文字：

{
  "items": [
    {
      "brand": "品牌名（如无法识别填 unknown）",
      "item_type": "单品类型（tee/hoodie/jacket/pants/cap/bag/shoes/accessory）",
      "colorway": "配色描述",
      "logo_visible": true/false,
      "confidence": 0.0到1.0之间的数字
    }
  ],
  "overall_style": "整体风格描述（streetwear/casual/sport/formal）",
  "has_target_brands": true/false
}
"""
```

### 趋势评分 Prompt
```python
TREND_ANALYSIS_PROMPT = """
你是一个潮流趋势分析师，专注于街头潮牌和粉丝经济。

以下是过去7天的社媒数据摘要：
{data_summary}

请分析并输出 JSON 格式（不输出其他文字）：
{
  "top_items": [
    {
      "brand": "品牌",
      "item_type": "单品类型",
      "hot_score": 0到100的热度分,
      "breakout_prob": 0到100的爆款概率,
      "reason": "评分理由（50字以内）",
      "related_idols": ["艺人1", "艺人2"]
    }
  ],
  "weekly_insight": "本周潮流洞察（100字以内）",
  "recommended_action": "选品建议（50字以内）"
}
"""
```

---

## 数据流（完整）

```
[APScheduler 定时触发]
        ↓
[crawlers/] 抓取帖子 → raw_posts 表 (is_analyzed=0)
        ↓
[analyzers/gemini_vision.py]
  批量取出 is_analyzed=0 的记录
  → 下载/传入图片 URL 给 Gemini Vision
  → 解析 JSON 响应 → 写入 analyzed_items 表
  → 更新 raw_posts.is_analyzed=1
        ↓
[analyzers/trend_scorer.py]
  聚合 analyzed_items 数据
  → 构建数据摘要 → 调用 Gemini Pro
  → 解析评分结果 → 写入 trend_scores 表
        ↓
[notifier/telegram_bot.py]
  检查 trend_scores 是否触发阈值
  → 超过阈值则推送 Telegram 消息
  → 写入 alerts_log 表
        ↓
[dashboard/app.py]
  Streamlit 读取 SQLite
  → 展示热度排行、趋势图、识别结果
```

---

## Sprint 1 开发范围（第一个可运行版本）

**只做这些，其他后续再加：**

- [ ] 项目初始化：目录结构 + requirements.txt + .env.example
- [ ] `database/models.py`：建表 + 数据库初始化
- [ ] `database/db.py`：基础 CRUD 函数
- [ ] `crawlers/xiaohongshu.py`：单关键词搜索，抓取标题+图片URL+点赞数
- [ ] `analyzers/gemini_vision.py`：批量识别图片中的单品，存入数据库
- [ ] `main.py`：手动触发一次完整流程（爬取 → 识别 → 打印结果）
- [ ] `dashboard/app.py`：最简版 Streamlit，展示 raw_posts 和 analyzed_items 表内容

**验收标准**：
1. 输入关键词 "Stussy 穿搭"，能抓到 ≥10 条帖子存入 SQLite
2. 对抓到的图片跑 Gemini Vision，能正确识别出 Stussy 单品
3. Streamlit 能打开并显示数据

---

## Sprint 2 计划（Sprint 1 完成后）

- Instagram 爬虫模块
- 得物价格监控模块
- trend_scorer 趋势评分逻辑
- Telegram 预警推送
- APScheduler 自动化调度

---

## 开发注意事项

1. **反爬措施**：小红书有反爬，爬虫需加随机延迟（2-5秒），User-Agent 轮换
2. **图片处理**：Gemini Vision 支持直接传图片 URL（`image_url` 类型），不需要下载再 base64
3. **错误处理**：Gemini API 调用必须有 try/except，失败记录 error log，不中断批处理
4. **去重逻辑**：用 `post_id` 字段做唯一约束，避免重复抓取
5. **数据目录**：SQLite 文件放在 `./data/` 目录，加入 .gitignore

---

## 第一次给 Claude Code 的开场 Prompt

```
请按照 project_brief.md 的设计，帮我初始化这个项目。

第一步，请完成以下工作：
1. 创建完整的目录结构
2. 生成 requirements.txt（包含所有需要的依赖）
3. 生成 .env.example 文件
4. 实现 database/models.py 和 database/db.py（建表 + CRUD）
5. 实现 config/settings.py

完成后告诉我，我们再进入爬虫模块的开发。
```
