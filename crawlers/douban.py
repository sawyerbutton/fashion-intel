"""豆瓣爬虫：搜索豆瓣小组帖子，提取潮流穿搭讨论。"""

import json
import logging
import os
import re
import time
from urllib.parse import quote

from playwright.sync_api import Browser, BrowserContext, sync_playwright

from crawlers.base_crawler import BaseCrawler

logger = logging.getLogger("crawler.douban")

STATE_PATH = "./data/douban_state.json"
SEARCH_URL = "https://www.douban.com/group/search?q={keyword}"


class DoubanCrawler(BaseCrawler):
    platform = "douban"

    def __init__(self, headless: bool = True):
        super().__init__()
        self.headless = headless
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    def _start_browser(self, headed_override: bool = False) -> BrowserContext:
        headless = False if headed_override else self.headless
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        kwargs = {
            "user_agent": self.random_ua(),
            "viewport": {"width": 1920, "height": 1080},
        }
        if os.path.exists(STATE_PATH):
            kwargs["storage_state"] = STATE_PATH
        self._context = self._browser.new_context(**kwargs)
        return self._context

    def _save_state(self) -> None:
        if self._context:
            os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
            self._context.storage_state(path=STATE_PATH)

    def _close_browser(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def _is_login_page(self, page) -> bool:
        """检测是否需要登录。"""
        return "accounts.douban.com" in page.url or "login" in page.url

    def _wait_for_login(self, page) -> bool:
        """等待用户手动登录。"""
        logger.info("=" * 50)
        logger.info("需要登录豆瓣！请在弹出的浏览器窗口中登录。")
        logger.info("登录成功后会自动继续，最多等待 3 分钟...")
        logger.info("=" * 50)
        try:
            for _ in range(60):  # 最多 180 秒
                time.sleep(3)
                current_url = page.url
                if "accounts.douban.com" not in current_url and "login" not in current_url:
                    self.random_delay(2, 3)
                    self._save_state()
                    logger.info("登录成功！已保存登录状态。")
                    return True
            logger.warning("登录等待超时")
            return False
        except Exception as e:
            logger.warning("登录等待出错: %s", e)
            return False

    def _extract_posts(self, page, max_notes: int) -> list[dict]:
        """从豆瓣小组搜索结果页提取帖子数据。"""
        results = []

        # 搜索结果列表
        items = page.locator("div.result")
        count = items.count()
        logger.info("找到 %d 条豆瓣小组搜索结果", count)

        for i in range(min(count, max_notes)):
            try:
                item = items.nth(i)

                # 标题和链接
                title_el = item.locator("h3 a").first
                title = title_el.inner_text().strip() if title_el.count() > 0 else ""
                post_url = title_el.get_attribute("href") or "" if title_el.count() > 0 else ""

                # 从 URL 提取 post_id
                post_id = ""
                match = re.search(r"/topic/(\d+)/", post_url)
                if match:
                    post_id = match.group(1)
                else:
                    post_id = f"douban_{i}_{int(time.time())}"

                # 内容摘要
                content_el = item.locator("div.content p").first
                content = content_el.inner_text().strip() if content_el.count() > 0 else ""

                # 图片
                images = []
                img_els = item.locator("img")
                for j in range(img_els.count()):
                    src = img_els.nth(j).get_attribute("src") or ""
                    if src and "icon" not in src:
                        images.append(src)

                results.append({
                    "platform": self.platform,
                    "post_id": post_id,
                    "url": post_url,
                    "title": title,
                    "content": content,
                    "image_urls": images,
                    "likes": 0,
                    "comments": 0,
                    "author": "",
                })

            except Exception as e:
                logger.debug("提取第 %d 条豆瓣帖子失败: %s", i, e)
                continue

        return results

    def _scroll_to_load(self, page, rounds: int = 3) -> None:
        """滚动页面加载更多。"""
        for _ in range(rounds):
            page.evaluate("window.scrollBy(0, 800)")
            self.random_delay(1, 2)

    def search(self, keyword: str, max_notes: int = 20) -> list[dict]:
        """搜索豆瓣小组，headless 失败时切换 headed 模式。"""
        results = self._try_search(keyword, max_notes, headed_override=False)
        if results:
            return results

        logger.info("豆瓣 headless 模式需要登录，切换到 headed 模式...")
        return self._try_search(keyword, max_notes, headed_override=True)

    def _try_search(self, keyword: str, max_notes: int, headed_override: bool) -> list[dict]:
        """执行一次搜索尝试。"""
        context = self._start_browser(headed_override=headed_override)
        try:
            page = context.new_page()
            url = SEARCH_URL.format(keyword=quote(keyword))
            logger.info("正在搜索豆瓣小组: %s", keyword)
            page.goto(url, wait_until="domcontentloaded")
            self.random_delay(2, 3)

            # 检测登录
            if self._is_login_page(page):
                if not headed_override:
                    logger.info("豆瓣要求登录，需要 headed 模式")
                    return []
                if not self._wait_for_login(page):
                    return []
                page.goto(url, wait_until="domcontentloaded")
                self.random_delay(2, 3)

            # 滚动加载
            self._scroll_to_load(page, rounds=2)

            # 提取数据
            results = self._extract_posts(page, max_notes)
            self._save_state()
            logger.info("豆瓣搜索完成，共 %d 条结果", len(results))
            return results

        except Exception as e:
            logger.error("豆瓣搜索出错: %s", e)
            return []
        finally:
            self._close_browser()
