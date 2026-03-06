"""微博爬虫：搜索潮流穿搭帖子，提取图片和互动数据。"""

import json
import logging
import os
import re
import time

from playwright.sync_api import Browser, BrowserContext, sync_playwright

from crawlers.base_crawler import BaseCrawler

logger = logging.getLogger("crawler.weibo")

STATE_PATH = "./data/weibo_state.json"
SEARCH_URL = "https://s.weibo.com/weibo?q={keyword}&xsort=hot&suball=1&Refer=g"


class WeiboCrawler(BaseCrawler):
    platform = "weibo"

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
        """检测是否被重定向到登录页。"""
        return "passport.weibo.com" in page.url or "login" in page.url

    def _wait_for_login(self, page) -> bool:
        """等待用户手动登录（扫码/验证码）。"""
        logger.info("=" * 50)
        logger.info("需要登录微博！请在弹出的浏览器窗口中：")
        logger.info("  1. 用微博 App 扫码登录")
        logger.info("  2. 或使用手机验证码登录")
        logger.info("登录成功后会自动继续，最多等待 3 分钟...")
        logger.info("=" * 50)
        try:
            # 轮询检测：每 3 秒检查一次 URL 是否离开了登录页
            for _ in range(100):  # 最多 300 秒（5分钟）
                time.sleep(3)
                current_url = page.url
                if "passport.weibo.com" not in current_url and "login" not in current_url:
                    self.random_delay(2, 3)
                    self._save_state()
                    logger.info("登录成功！已保存登录状态。")
                    return True
            logger.warning("登录等待超时（5分钟）")
            return False
        except Exception as e:
            logger.warning("登录等待出错: %s", e)
            return False

    def _extract_posts(self, page, keyword: str, max_notes: int) -> list[dict]:
        """从微博搜索结果页提取帖子数据。"""
        results = []

        # 微博搜索结果的卡片选择器
        cards = page.locator('div.card-wrap[action-type="feed_list_item"]')
        count = cards.count()
        logger.info("找到 %d 条微博卡片", count)

        for i in range(min(count, max_notes)):
            try:
                card = cards.nth(i)

                # 提取文本内容
                content_el = card.locator('p.txt[node-type="feed_list_content"]').first
                content = content_el.inner_text().strip() if content_el.count() > 0 else ""

                # 完整内容（展开版）
                full_el = card.locator('p.txt[node-type="feed_list_content_full"]').first
                if full_el.count() > 0:
                    content = full_el.inner_text().strip()

                # 提取作者
                author_el = card.locator('a.name').first
                author = author_el.inner_text().strip() if author_el.count() > 0 else ""

                # 提取图片
                images = []
                img_els = card.locator('div.media img, li.pic img')
                for j in range(img_els.count()):
                    src = img_els.nth(j).get_attribute("src") or ""
                    if src:
                        # 微博图片 URL 处理：转为大图
                        src = src.replace("/thumb150/", "/large/")
                        src = src.replace("/orj360/", "/large/")
                        src = src.replace("/thumb180/", "/large/")
                        if src.startswith("//"):
                            src = "https:" + src
                        elif not src.startswith("http"):
                            src = "https://" + src
                        images.append(src)

                # 提取互动数据（转发、评论、点赞）
                likes = 0
                comments_count = 0
                act_els = card.locator('div.card-act li')
                for j in range(act_els.count()):
                    text = act_els.nth(j).inner_text().strip()
                    nums = re.findall(r'\d+', text)
                    if nums:
                        num = int(nums[0])
                        if j == 1:  # 评论
                            comments_count = num
                        elif j == 2:  # 点赞
                            likes = num

                # 提取帖子链接和 ID
                link_el = card.locator('div.from a').first
                post_url = ""
                post_id = ""
                if link_el.count() > 0:
                    href = link_el.get_attribute("href") or ""
                    if href:
                        post_url = href if href.startswith("http") else "https:" + href
                        # 从 URL 提取微博 ID
                        match = re.search(r'/(\w+)\?', post_url)
                        if match:
                            post_id = match.group(1)

                if not post_id:
                    mid = card.get_attribute("mid") or f"weibo_{i}_{int(time.time())}"
                    post_id = mid

                # 用内容前 30 字作为标题
                title = content[:30] + ("..." if len(content) > 30 else "")

                if content or images:
                    results.append({
                        "platform": "weibo",
                        "post_id": post_id,
                        "url": post_url,
                        "title": title,
                        "content": content,
                        "image_urls": images,
                        "likes": likes,
                        "comments": comments_count,
                        "author": author,
                    })

            except Exception as e:
                logger.debug("提取第 %d 条微博失败: %s", i, e)
                continue

        return results

    def _scroll_to_load(self, page, rounds: int = 3) -> None:
        """滚动页面加载更多内容。"""
        for _ in range(rounds):
            page.evaluate("window.scrollBy(0, 800)")
            self.random_delay(1, 2)

    def search(self, keyword: str, max_notes: int = 20) -> list[dict]:
        """搜索微博，headless 失败时自动切换 headed 模式。"""
        # 第一轮：尝试 headless（或用已保存的登录态）
        results = self._try_search(keyword, max_notes, headed_override=False)
        if results:
            return results

        # 第二轮：headed 模式让用户登录
        logger.info("微博 headless 模式需要登录，切换到 headed 模式...")
        results = self._try_search(keyword, max_notes, headed_override=True)
        return results

    def _try_search(self, keyword: str, max_notes: int, headed_override: bool) -> list[dict]:
        """执行一次搜索尝试。"""
        context = self._start_browser(headed_override=headed_override)
        try:
            page = context.new_page()
            url = SEARCH_URL.format(keyword=keyword)
            logger.info("正在搜索微博: %s", keyword)
            page.goto(url, wait_until="domcontentloaded")
            self.random_delay(2, 3)

            # 检测是否需要登录
            if self._is_login_page(page):
                if not headed_override:
                    logger.info("微博要求登录，需要 headed 模式")
                    return []
                # headed 模式，等待用户登录
                if not self._wait_for_login(page):
                    return []
                # 登录后重新加载搜索页
                page.goto(url, wait_until="domcontentloaded")
                self.random_delay(2, 3)

            # 滚动加载更多
            self._scroll_to_load(page, rounds=3)

            # 提取数据
            results = self._extract_posts(page, keyword, max_notes)
            self._save_state()
            logger.info("微博搜索完成，共 %d 条结果", len(results))
            return results

        except Exception as e:
            logger.error("微博搜索出错: %s", e)
            return []
        finally:
            self._close_browser()
