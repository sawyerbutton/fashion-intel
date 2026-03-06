"""手动运行入口：触发一次完整的 爬取 → 识别 → 打印结果 流程。"""

import logging
import sys

from config.settings import KEYWORDS, OVERSEAS_KEYWORDS, DOUBAN_KEYWORDS
from crawlers.xiaohongshu import XiaohongshuCrawler
from crawlers.weibo import WeiboCrawler
from crawlers.hypebeast import HypebeastCrawler
from crawlers.highsnobiety import HighsnobietyCrawler
from crawlers.reddit_crawler import RedditCrawler
from crawlers.douban import DoubanCrawler
from analyzers.gemini_vision import run_batch_analysis
from analyzers.trend_scorer import generate_trend_scores
from notifier.telegram_bot import check_and_alert
from database.db import insert_post, get_all_posts, get_all_items, get_latest_scores
from database.models import init_db

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def crawl(keywords: list[str] | None = None, max_notes: int = 20) -> int:
    """执行爬取，返回新增帖子数。"""
    keywords = keywords or KEYWORDS[:1]  # 默认只跑第一个关键词
    crawler = XiaohongshuCrawler(headless=True)
    total_new = 0

    for kw in keywords:
        logger.info("━━━ 开始爬取关键词: %s ━━━", kw)
        try:
            notes = crawler.search(kw, max_notes=max_notes)
        except Exception as e:
            logger.error("爬取失败: %s", e)
            continue

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

        logger.info("关键词 [%s] 完成: 抓取 %d 条, 新增 %d 条", kw, len(notes), new_count)
        total_new += new_count

    return total_new


def show_stats() -> None:
    """打印数据库中已有的帖子概况。"""
    posts = get_all_posts(limit=200)
    logger.info("━━━ 数据库概况 ━━━")
    logger.info("帖子总数: %d", len(posts))
    if posts:
        platforms = {}
        for p in posts:
            platforms[p["platform"]] = platforms.get(p["platform"], 0) + 1
        for plat, cnt in platforms.items():
            logger.info("  %s: %d 条", plat, cnt)

        analyzed = sum(1 for p in posts if p["is_analyzed"])
        logger.info("已分析: %d / %d", analyzed, len(posts))

    items = get_all_items(limit=500)
    logger.info("识别单品总数: %d", len(items))
    if items:
        brands = {}
        for it in items:
            brands[it["brand"]] = brands.get(it["brand"], 0) + 1
        for brand, cnt in sorted(brands.items(), key=lambda x: -x[1]):
            logger.info("  %s: %d 件", brand, cnt)


def analyze() -> dict:
    """执行 Gemini Vision 批量分析。"""
    logger.info("━━━ 开始 Gemini Vision 分析 ━━━")
    return run_batch_analysis()


def crawl_platform(crawler, keywords: list[str], max_notes: int, label: str) -> int:
    """通用平台爬取：用给定爬虫搜索关键词列表，结果入库。"""
    total_new = 0
    for kw in keywords:
        logger.info("━━━ [%s] 开始爬取: %s ━━━", label, kw)
        try:
            notes = crawler.search(kw, max_notes=max_notes)
        except Exception as e:
            logger.error("[%s] 爬取失败: %s", label, e)
            continue

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

        logger.info("[%s] 关键词 [%s] 完成: 抓取 %d 条, 新增 %d 条", label, kw, len(notes), new_count)
        total_new += new_count
    return total_new


if __name__ == "__main__":
    init_db()

    # 支持命令行参数：
    #   python main.py "Stussy 穿搭" 10    → 小红书爬取 + 分析
    #   python main.py --weibo [keyword] [max]   → 微博爬取
    #   python main.py --hypebeast [keyword] [max]  → Hypebeast RSS
    #   python main.py --highsnobiety [keyword] [max] → Highsnobiety RSS
    #   python main.py --reddit [keyword] [max]  → Reddit 搜索
    #   python main.py --douban [keyword] [max]  → 豆瓣小组搜索
    #   python main.py --overseas    → 一键跑所有海外平台
    #   python main.py --all         → 一键跑所有平台
    #   python main.py --analyze     → 仅分析已有帖子
    #   python main.py --score       → 仅生成趋势评分 + 预警
    #   python main.py --stats       → 仅查看统计
    #   python main.py --full        → 完整流程（爬取→分析→评分→预警）
    cmd = sys.argv[1] if len(sys.argv) > 1 else None

    if cmd == "--stats":
        show_stats()

    elif cmd == "--weibo":
        kw = sys.argv[2] if len(sys.argv) > 2 else "Stussy穿搭"
        max_n = int(sys.argv[3]) if len(sys.argv) > 3 else 15
        crawl_platform(WeiboCrawler(headless=True), [kw], max_n, "微博")
        show_stats()

    elif cmd == "--hypebeast":
        kw = sys.argv[2] if len(sys.argv) > 2 else "Stussy"
        max_n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        crawl_platform(HypebeastCrawler(), [kw], max_n, "Hypebeast")
        show_stats()

    elif cmd == "--highsnobiety":
        kw = sys.argv[2] if len(sys.argv) > 2 else "Stussy"
        max_n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        crawl_platform(HighsnobietyCrawler(), [kw], max_n, "Highsnobiety")
        show_stats()

    elif cmd == "--reddit":
        kw = sys.argv[2] if len(sys.argv) > 2 else "Stussy"
        max_n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        crawl_platform(RedditCrawler(), [kw], max_n, "Reddit")
        show_stats()

    elif cmd == "--douban":
        kw = sys.argv[2] if len(sys.argv) > 2 else "潮牌穿搭"
        max_n = int(sys.argv[3]) if len(sys.argv) > 3 else 15
        crawl_platform(DoubanCrawler(headless=True), [kw], max_n, "豆瓣")
        show_stats()

    elif cmd == "--overseas":
        logger.info("━━━ 一键海外平台爬取 ━━━")
        total = 0
        for kw in OVERSEAS_KEYWORDS[:3]:
            total += crawl_platform(HypebeastCrawler(), [kw], 10, "Hypebeast")
            total += crawl_platform(HighsnobietyCrawler(), [kw], 10, "Highsnobiety")
        try:
            for kw in OVERSEAS_KEYWORDS[:3]:
                total += crawl_platform(RedditCrawler(), [kw], 10, "Reddit")
        except ValueError as e:
            logger.warning("跳过 Reddit: %s", e)
        logger.info("海外平台爬取完成，共新增 %d 条", total)
        show_stats()

    elif cmd == "--all":
        logger.info("━━━ 一键全平台爬取 ━━━")
        total = 0
        # 国内平台
        total += crawl()
        crawl_platform(WeiboCrawler(headless=True), KEYWORDS[:2], 15, "微博")
        crawl_platform(DoubanCrawler(headless=True), DOUBAN_KEYWORDS[:2], 15, "豆瓣")
        # 海外平台
        for kw in OVERSEAS_KEYWORDS[:3]:
            total += crawl_platform(HypebeastCrawler(), [kw], 10, "Hypebeast")
            total += crawl_platform(HighsnobietyCrawler(), [kw], 10, "Highsnobiety")
        try:
            for kw in OVERSEAS_KEYWORDS[:3]:
                total += crawl_platform(RedditCrawler(), [kw], 10, "Reddit")
        except ValueError as e:
            logger.warning("跳过 Reddit: %s", e)
        logger.info("全平台爬取完成")
        show_stats()

    elif cmd == "--analyze":
        result = analyze()
        logger.info("分析结果: %s", result)
        show_stats()
    elif cmd == "--score":
        scores = generate_trend_scores()
        logger.info("生成 %d 条评分", len(scores))
        sent = check_and_alert()
        logger.info("发送 %d 条预警", sent)
        show_stats()
    elif cmd == "--full":
        crawl()
        analyze()
        generate_trend_scores()
        check_and_alert()
        show_stats()
    else:
        kw_arg = cmd if cmd and not cmd.startswith("--") else None
        max_n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        keywords = [kw_arg] if kw_arg else None

        new = crawl(keywords=keywords, max_notes=max_n)
        logger.info("本次新增 %d 条帖子", new)

        result = analyze()
        logger.info("分析结果: %s", result)

        show_stats()
