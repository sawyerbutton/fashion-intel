"""爬虫基类：统一接口 + 反爬工具。"""

import logging
import random
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


class BaseCrawler(ABC):
    """爬虫基类。所有平台爬虫继承此类并实现 search() 方法。"""

    platform: str = ""

    def __init__(self):
        self.logger = logging.getLogger(f"crawler.{self.platform}")

    @abstractmethod
    def search(self, keyword: str, max_notes: int = 20) -> list[dict]:
        """搜索关键词，返回帖子字典列表。

        每条帖子至少包含：
            platform, post_id, url, title, content,
            image_urls (list), likes, comments, author
        """

    @staticmethod
    def random_delay(min_sec: float = 2.0, max_sec: float = 5.0) -> None:
        """随机延迟，防触发反爬。"""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)

    @staticmethod
    def random_ua() -> str:
        """随机返回一个 User-Agent。"""
        return random.choice(USER_AGENTS)
