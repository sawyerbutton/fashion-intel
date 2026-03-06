"""Reddit 爬虫：通过 PRAW 搜索潮流相关 subreddit。"""

import logging

import praw

from config.settings import REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
from crawlers.base_crawler import BaseCrawler

logger = logging.getLogger("crawler.reddit")

# 默认搜索的 subreddit 列表
TARGET_SUBREDDITS = ["streetwear", "sneakers"]


class RedditCrawler(BaseCrawler):
    platform = "reddit"

    def __init__(self):
        super().__init__()
        if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
            raise ValueError(
                "Reddit API 凭据未配置。请在 .env 中设置 "
                "REDDIT_CLIENT_ID 和 REDDIT_CLIENT_SECRET"
            )
        self._reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT,
        )

    def _extract_images(self, submission) -> list[str]:
        """从 Reddit submission 提取图片 URL。"""
        images = []

        # 直接图片链接
        url = submission.url or ""
        if any(url.endswith(ext) for ext in (".jpg", ".png", ".jpeg", ".gif", ".webp")):
            images.append(url)

        # Reddit 图片预览
        if hasattr(submission, "preview") and submission.preview:
            for img in submission.preview.get("images", []):
                source = img.get("source", {})
                src_url = source.get("url", "").replace("&amp;", "&")
                if src_url and src_url not in images:
                    images.append(src_url)

        # Reddit gallery
        if hasattr(submission, "is_gallery") and submission.is_gallery:
            media_meta = getattr(submission, "media_metadata", {}) or {}
            for item in media_meta.values():
                if item.get("status") == "valid":
                    src = item.get("s", {}).get("u", "").replace("&amp;", "&")
                    if src and src not in images:
                        images.append(src)

        return images

    def search(self, keyword: str, max_notes: int = 20) -> list[dict]:
        """在目标 subreddit 中搜索关键词。"""
        results = []
        per_sub = max(max_notes // len(TARGET_SUBREDDITS), 5)

        for sub_name in TARGET_SUBREDDITS:
            logger.info("正在搜索 r/%s: %s", sub_name, keyword)
            try:
                subreddit = self._reddit.subreddit(sub_name)
                submissions = subreddit.search(keyword, sort="relevance", limit=per_sub)

                for submission in submissions:
                    images = self._extract_images(submission)
                    content = submission.selftext or ""
                    title = submission.title or ""

                    results.append({
                        "platform": self.platform,
                        "post_id": submission.id,
                        "url": f"https://reddit.com{submission.permalink}",
                        "title": title,
                        "content": content,
                        "image_urls": images,
                        "likes": submission.score,
                        "comments": submission.num_comments,
                        "author": str(submission.author) if submission.author else "",
                    })

                    if len(results) >= max_notes:
                        break

            except Exception as e:
                logger.error("搜索 r/%s 失败: %s", sub_name, e)
                continue

            if len(results) >= max_notes:
                break

        logger.info("Reddit 搜索完成，共 %d 条结果", len(results))
        return results[:max_notes]
