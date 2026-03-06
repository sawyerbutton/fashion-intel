"""趋势评分：聚合 analyzed_items 数据，调用 Gemini Pro 生成趋势评分。"""

import json
import logging
from datetime import date, timedelta

from google import genai

from config.settings import GEMINI_API_KEY, TREND_ANALYSIS_PROMPT, TARGET_BRANDS
from database.db import get_conn, insert_trend_score

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY 未设置")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _build_data_summary(days: int = 7) -> str:
    """聚合最近 N 天的识别数据，生成摘要文本供 Gemini 分析。"""
    conn = get_conn()
    try:
        since = (date.today() - timedelta(days=days)).isoformat()

        # 按品牌+类型聚合
        rows = conn.execute(
            """
            SELECT ai.brand, ai.item_type,
                   COUNT(*) as mention_count,
                   AVG(rp.likes) as avg_likes,
                   GROUP_CONCAT(DISTINCT rp.author) as authors
            FROM analyzed_items ai
            JOIN raw_posts rp ON ai.post_id = rp.id
            WHERE ai.analyzed_at >= ? AND ai.brand != 'unknown'
            GROUP BY ai.brand, ai.item_type
            ORDER BY mention_count DESC
            LIMIT 30
            """,
            (since,),
        ).fetchall()

        if not rows:
            return ""

        lines = []
        for r in rows:
            lines.append(
                f"- {r['brand']} {r['item_type']}: 提及{r['mention_count']}次, "
                f"平均点赞{r['avg_likes']:.0f}, 相关作者: {r['authors'] or '无'}"
            )

        # 补充目标品牌的总体情况
        target_rows = conn.execute(
            """
            SELECT ai.brand, COUNT(*) as total,
                   AVG(rp.likes) as avg_likes,
                   MAX(rp.likes) as max_likes
            FROM analyzed_items ai
            JOIN raw_posts rp ON ai.post_id = rp.id
            WHERE ai.analyzed_at >= ?
              AND (ai.brand IN ({}) OR LOWER(ai.brand) IN ({}))
            GROUP BY ai.brand
            """.format(
                ",".join(f"'{b}'" for b in TARGET_BRANDS),
                ",".join(f"'{b.lower()}'" for b in TARGET_BRANDS),
            ),
            (since,),
        ).fetchall()

        if target_rows:
            lines.append("\n目标品牌汇总:")
            for r in target_rows:
                lines.append(
                    f"  {r['brand']}: {r['total']}次提及, "
                    f"平均点赞{r['avg_likes']:.0f}, 最高点赞{r['max_likes']}"
                )

        return "\n".join(lines)
    finally:
        conn.close()


def generate_trend_scores() -> list[dict]:
    """调用 Gemini 生成趋势评分，写入数据库。"""
    summary = _build_data_summary()
    if not summary:
        logger.info("没有足够的数据生成趋势评分")
        return []

    logger.info("生成趋势评分，数据摘要:\n%s", summary[:500])

    prompt = TREND_ANALYSIS_PROMPT.format(data_summary=summary)

    try:
        response = _get_client().models.generate_content(
            model=MODEL, contents=prompt
        )
        text = response.text.strip()

        # 清理 JSON
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0].strip()

        import re
        text = re.sub(r",\s*([}\]])", r"\1", text)

        result = json.loads(text)
    except Exception as e:
        logger.error("Gemini 趋势分析失败: %s", e)
        return []

    # 写入数据库
    today = date.today()
    scores = []
    for item in result.get("top_items", []):
        score_data = {
            "brand": item.get("brand", ""),
            "item_type": item.get("item_type", ""),
            "score_date": today,
            "mention_count": 0,  # 后面补充
            "avg_likes": 0,
            "hot_score": item.get("hot_score", 0),
            "breakout_prob": item.get("breakout_prob", 0),
            "related_idols": item.get("related_idols", []),
        }

        # 从数据库补充实际的 mention_count 和 avg_likes
        conn = get_conn()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt, AVG(rp.likes) as avg_l
                FROM analyzed_items ai
                JOIN raw_posts rp ON ai.post_id = rp.id
                WHERE ai.brand = ? AND ai.item_type = ?
                """,
                (score_data["brand"], score_data["item_type"]),
            ).fetchone()
            if row:
                score_data["mention_count"] = row["cnt"]
                score_data["avg_likes"] = row["avg_l"] or 0
        finally:
            conn.close()

        insert_trend_score(**score_data)
        scores.append(score_data)

    logger.info("趋势评分完成，生成 %d 条评分", len(scores))

    # 记录洞察
    if "weekly_insight" in result:
        logger.info("本周洞察: %s", result["weekly_insight"])
    if "recommended_action" in result:
        logger.info("选品建议: %s", result["recommended_action"])

    return scores
