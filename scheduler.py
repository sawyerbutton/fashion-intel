"""定时任务主入口：使用 APScheduler 自动化调度所有流程。

启动方式：python scheduler.py
"""

import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler

from config.settings import (
    KEYWORDS,
    CRAWL_INTERVAL_HOURS,
    ANALYSIS_INTERVAL_HOURS,
    SCORE_INTERVAL_HOURS,
)
from database.models import init_db
from database.db import insert_post
from crawlers.xiaohongshu import XiaohongshuCrawler
from analyzers.gemini_vision import run_batch_analysis
from analyzers.trend_scorer import generate_trend_scores
from notifier.telegram_bot import check_and_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scheduler")


# ───────────────── 任务函数 ─────────────────


def job_crawl():
    """定时爬取任务。"""
    logger.info("━━━ 定时爬取开始 ━━━")
    crawler = XiaohongshuCrawler(headless=True)

    for kw in KEYWORDS:
        try:
            notes = crawler.search(kw, max_notes=20)
            new_count = 0
            for note in notes:
                row_id = insert_post(
                    platform=note["platform"],
                    post_id=note["post_id"],
                    url=note["url"],
                    title=note["title"],
                    content=note["content"],
                    image_urls=note["image_urls"],
                    likes=note["likes"],
                    comments=note["comments"],
                    author=note["author"],
                    keyword=kw,
                )
                if row_id:
                    new_count += 1
            logger.info("[%s] 抓取 %d 条, 新增 %d 条", kw, len(notes), new_count)
        except Exception as e:
            logger.error("[%s] 爬取失败: %s", kw, e)

    logger.info("━━━ 定时爬取结束 ━━━")


def job_analyze():
    """定时分析任务。"""
    logger.info("━━━ 定时分析开始 ━━━")
    try:
        result = run_batch_analysis()
        logger.info("分析完成: %s", result)
    except Exception as e:
        logger.error("分析失败: %s", e)
    logger.info("━━━ 定时分析结束 ━━━")


def job_score():
    """定时评分 + 预警任务。"""
    logger.info("━━━ 定时评分开始 ━━━")
    try:
        scores = generate_trend_scores()
        logger.info("生成 %d 条评分", len(scores))
    except Exception as e:
        logger.error("评分失败: %s", e)

    try:
        sent = check_and_alert()
        logger.info("发送 %d 条预警", sent)
    except Exception as e:
        logger.error("预警推送失败: %s", e)
    logger.info("━━━ 定时评分结束 ━━━")


# ───────────────── 调度器 ─────────────────


def main():
    init_db()

    scheduler = BlockingScheduler()

    # 爬取任务：每 N 小时执行
    scheduler.add_job(job_crawl, "interval", hours=CRAWL_INTERVAL_HOURS, id="crawl")

    # 分析任务：每 N 小时执行
    scheduler.add_job(job_analyze, "interval", hours=ANALYSIS_INTERVAL_HOURS, id="analyze")

    # 评分+预警：每天执行一次
    scheduler.add_job(job_score, "interval", hours=SCORE_INTERVAL_HOURS, id="score")

    # 启动时先跑一轮
    logger.info("调度器启动，立即执行首轮任务...")
    logger.info(
        "调度频率: 爬取=%dh, 分析=%dh, 评分=%dh",
        CRAWL_INTERVAL_HOURS,
        ANALYSIS_INTERVAL_HOURS,
        SCORE_INTERVAL_HOURS,
    )

    # 优雅退出
    def shutdown(signum, frame):
        logger.info("收到信号 %s，正在关闭调度器...", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器已停止")


if __name__ == "__main__":
    main()
