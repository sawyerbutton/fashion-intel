import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DB_PATH = os.getenv("DB_PATH", "./data/fashion_intel.db")

# Reddit API
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "fashion-intel-bot/1.0")

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

# 海外平台关键词
OVERSEAS_KEYWORDS = [
    "streetwear",
    "Stussy",
    "Supreme",
    "BAPE",
    "Palace",
    "Carhartt WIP",
    "Nike Dunk",
    "New Balance 550",
]

# 豆瓣关键词
DOUBAN_KEYWORDS = [
    "潮牌穿搭",
    "街头穿搭",
    "Stussy穿搭",
    "Supreme穿搭",
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

# Gemini Vision 识别 Prompt
# 注意：{post_context} 会在运行时被替换为帖子的标题、关键词等上下文
VISION_PROMPT = """
你是一个专业的街头潮牌穿搭分析师。

## 帖子上下文
{post_context}

## 重点关注品牌
Stussy, Supreme, BAPE, Carhartt, Palace, Nike, Adidas, New Balance, Converse, Vans, The North Face, Champion, Polo Ralph Lauren, Dickies, WTAPS, NEIGHBORHOOD, HUMAN MADE

## 任务
分析图片中可以识别出品牌的服装和配饰单品。

**重要规则：只报告能识别出品牌的单品，跳过无法判断品牌的普通单品。**
- 如果一件衣服没有可见 Logo、没有品牌特征、帖子上下文也没有提及 → 不要报告它
- 宁可少报，也不要报告 "unknown" 品牌

识别品牌的依据（按优先级）：
1. 图片中可见的 Logo、文字、标志性图案
2. 帖子标题和关键词中提到的品牌（结合图片中的款式判断）
3. 品牌的标志性设计特征（如 Stussy 的手写体 logo、Supreme 的 box logo）

严格按以下 JSON 格式返回：

{
  "items": [
    {
      "brand": "品牌名（必须是具体品牌，不能是 unknown）",
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

# Gemini 趋势分析 Prompt
TREND_ANALYSIS_PROMPT = """
你是一个潮流趋势分析师，专注于街头潮牌和粉丝经济。

以下是过去7天的社媒数据摘要：
{data_summary}

请分析并输出 JSON 格式（不输出其他文字）：
{{
  "top_items": [
    {{
      "brand": "品牌",
      "item_type": "单品类型",
      "hot_score": 0到100的热度分,
      "breakout_prob": 0到100的爆款概率,
      "reason": "评分理由（50字以内）",
      "related_idols": ["艺人1", "艺人2"]
    }}
  ],
  "weekly_insight": "本周潮流洞察（100字以内）",
  "recommended_action": "选品建议（50字以内）"
}}
"""
