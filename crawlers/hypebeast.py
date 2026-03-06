"""Hypebeast RSS 爬虫：解析 RSS feed 获取潮流资讯。"""

import hashlib
import logging
import re

import feedparser

from crawlers.base_crawler import BaseCrawler

logger = logging.getLogger("crawler.hypebeast")

RSS_URL = "https://hypebeast.com/feed"


class HypebeastCrawler(BaseCrawler):
    platform = "hypebeast"

    def _extract_images(self, entry) -> list[str]:
        """从 RSS entry 中提取图片 URL。"""
        images = []

        # 1. media:content / media:thumbnail
        for media in getattr(entry, "media_content", []):
            url = media.get("url", "")
            if url and ("jpg" in url or "png" in url or "jpeg" in url or "webp" in url):
                images.append(url)

        media_thumb = getattr(entry, "media_thumbnail", [])
        for thumb in media_thumb:
            url = thumb.get("url", "")
            if url and url not in images:
                images.append(url)

        # 2. 从 summary HTML 中提取 <img src="...">
        summary = getattr(entry, "summary", "")
        for match in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', summary):
            if match not in images:
                images.append(match)

        # 3. enclosures
        for enc in getattr(entry, "enclosures", []):
            url = enc.get("href", "") or enc.get("url", "")
            if url and url not in images and any(
                ext in url for ext in (".jpg", ".png", ".jpeg", ".webp")
            ):
                images.append(url)

        return images

    def _clean_html(self, html: str) -> str:
        """去除 HTML 标签，返回纯文本。"""
        text = re.sub(r"<[^>]+>", "", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def search(self, keyword: str, max_notes: int = 20) -> list[dict]:
        """拉取 RSS feed，按关键词过滤标题/描述。"""
        logger.info("正在拉取 Hypebeast RSS feed...")
        feed = feedparser.parse(RSS_URL)

        if feed.bozo and not feed.entries:
            logger.error("RSS feed 解析失败: %s", feed.bozo_exception)
            return []

        logger.info("RSS feed 共 %d 条，按关键词 [%s] 过滤", len(feed.entries), keyword)
        keyword_lower = keyword.lower()
        results = []

        for entry in feed.entries:
            title = getattr(entry, "title", "")
            summary = self._clean_html(getattr(entry, "summary", ""))

            # 关键词过滤（标题或内容包含关键词）
            if keyword_lower not in title.lower() and keyword_lower not in summary.lower():
                continue

            post_url = getattr(entry, "link", "")
            post_id = hashlib.md5(post_url.encode()).hexdigest()[:16] if post_url else ""
            author = getattr(entry, "author", "Hypebeast")
            images = self._extract_images(entry)

            results.append({
                "platform": self.platform,
                "post_id": post_id,
                "url": post_url,
                "title": title,
                "content": summary,
                "image_urls": images,
                "likes": 0,
                "comments": 0,
                "author": author,
            })

            if len(results) >= max_notes:
                break

        logger.info("Hypebeast 过滤完成，共 %d 条结果", len(results))
        return results
