"""Telegram 预警推送：当趋势评分触发阈值时发送消息。"""

import logging

import requests

from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    ALERT_THRESHOLDS,
)
from database.db import get_latest_scores, insert_alert

logger = logging.getLogger(__name__)


def send_message(text: str) -> bool:
    """发送 Telegram 消息。"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram 未配置（缺少 BOT_TOKEN 或 CHAT_ID），跳过推送")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Telegram 消息发送成功")
            return True
        else:
            logger.error("Telegram 发送失败: %s %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.error("Telegram 请求异常: %s", e)
        return False


def _format_alert(alert_type: str, brand: str, item_type: str, score: dict) -> str:
    """格式化预警消息。"""
    emoji = {"hot_score": "🔥", "breakout_prob": "🚀", "mention_surge": "📈"}.get(
        alert_type, "⚠️"
    )

    lines = [
        f"{emoji} *潮流预警 - {alert_type}*",
        f"品牌: *{brand}*",
        f"单品: {item_type}",
        f"热度分: {score.get('hot_score', 0):.0f}/100",
        f"爆款概率: {score.get('breakout_prob', 0):.0f}%",
        f"提及次数: {score.get('mention_count', 0)}",
        f"平均点赞: {score.get('avg_likes', 0):.0f}",
    ]
    return "\n".join(lines)


def check_and_alert() -> int:
    """检查最新评分，触发阈值则推送预警。返回发送的预警数。"""
    scores = get_latest_scores(limit=20)
    if not scores:
        logger.info("没有评分数据，跳过预警检查")
        return 0

    hot_min = ALERT_THRESHOLDS.get("hot_score_min", 75)
    breakout_min = ALERT_THRESHOLDS.get("breakout_prob_min", 70)
    sent_count = 0

    for s in scores:
        alerts = []

        if s["hot_score"] >= hot_min:
            alerts.append("hot_score")
        if s["breakout_prob"] >= breakout_min:
            alerts.append("breakout_prob")

        for alert_type in alerts:
            message = _format_alert(alert_type, s["brand"], s["item_type"], s)
            success = send_message(message)

            insert_alert(
                alert_type=alert_type,
                brand=s["brand"],
                item_type=s["item_type"],
                message=message,
            )
            if success:
                sent_count += 1

    logger.info("预警检查完成，发送 %d 条预警", sent_count)
    return sent_count
