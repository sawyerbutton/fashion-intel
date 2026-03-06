"""Instagram 爬虫：基于 Playwright 抓取标签/搜索结果。

Instagram 反爬非常严格，本模块采用以下策略：
  1. 使用已登录的浏览器状态
  2. 通过标签页（/explore/tags/xxx）获取帖子
  3. 从页面 __NEXT_DATA__ 或 GraphQL 响应中提取数据
  4. 严格的速率控制（每次请求间隔 5-10 秒）
"""

import json
import logging
import os
import time

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

from config.settings import DB_PATH
from crawlers.base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

STATE_PATH = os.path.join(os.path.dirname(DB_PATH), "ig_state.json")

TAG_URL = "https://www.instagram.com/explore/tags/{tag}/"


class InstagramCrawler(BaseCrawler):
    platform = "instagram"

    def __init__(self, headless: bool = True):
        super().__init__()
        self.headless = headless
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    # ───────────────── 浏览器生命周期 ─────────────────

    def _start_browser(self) -> BrowserContext:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        kwargs = {
            "user_agent": self.random_ua(),
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-US",
        }
        if os.path.exists(STATE_PATH):
            self.logger.info("加载 Instagram 登录态: %s", STATE_PATH)
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

    # ───────────────── 登录 ─────────────────

    def _check_login(self, page: Page) -> bool:
        """检测是否已登录 Instagram。"""
        # 未登录时会重定向到登录页
        if "/accounts/login" in page.url:
            return False
        login_form = page.locator('input[name="username"]')
        return login_form.count() == 0

    def _ensure_login(self, page: Page) -> Page:
        if self._check_login(page):
            return page

        self._close_browser()
        self.headless = False
        context = self._start_browser()
        page = context.new_page()
        page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")

        self.logger.warning("=" * 50)
        self.logger.warning("请在浏览器中登录 Instagram")
        self.logger.warning("登录成功后脚本将自动继续...")
        self.logger.warning("=" * 50)

        deadline = time.time() + 300
        while time.time() < deadline:
            time.sleep(3)
            if "/accounts/login" not in page.url:
                time.sleep(3)
                self.logger.info("Instagram 登录成功！")
                self._save_state()
                return page

        raise TimeoutError("Instagram 登录超时")

    # ───────────────── 核心搜索逻辑 ─────────────────

    def search(self, keyword: str, max_notes: int = 20) -> list[dict]:
        """通过标签页搜索帖子。

        keyword 会被转换为标签格式（去空格、小写）。
        """
        tag = keyword.replace(" ", "").lower()
        context = self._start_browser()

        try:
            page = context.new_page()

            # 拦截 GraphQL 响应以获取帖子数据
            graphql_data = []

            def on_response(response):
                url = response.url
                if "graphql" in url or "/api/v1/tags/" in url:
                    try:
                        body = response.json()
                        graphql_data.append(body)
                    except Exception:
                        pass

            page.on("response", on_response)

            url = TAG_URL.format(tag=tag)
            self.logger.info("正在搜索 Instagram 标签: #%s", tag)
            page.goto(url, wait_until="domcontentloaded")
            self.random_delay(5, 8)

            page = self._ensure_login(page)

            # 如果登录后需要重新导航
            if "/explore/tags/" not in page.url:
                page.goto(url, wait_until="domcontentloaded")
                self.random_delay(5, 8)

            # 滚动加载更多
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 1000)")
                self.random_delay(3, 5)

            # 从拦截的 GraphQL 数据中提取帖子
            results = self._extract_from_graphql(graphql_data, tag, max_notes)

            # 如果 GraphQL 没拿到数据，尝试从页面 DOM 提取
            if not results:
                results = self._extract_from_dom(page, tag, max_notes)

            self._save_state()
            self.logger.info("Instagram 搜索完成，共 %d 条结果", len(results))
            return results

        except Exception as e:
            self.logger.error("Instagram 搜索出错: %s", e)
            raise
        finally:
            self._close_browser()

    # ───────────────── 数据提取 ─────────────────

    def _extract_from_graphql(self, data_list: list, tag: str, max_notes: int) -> list[dict]:
        """从拦截的 GraphQL 响应中提取帖子数据。"""
        results = []
        for data in data_list:
            edges = []
            # Instagram GraphQL 响应结构可能嵌套较深
            if "data" in data:
                d = data["data"]
                # 标签页响应
                if "hashtag" in d:
                    media = d["hashtag"].get("edge_hashtag_to_media", {})
                    edges = media.get("edges", [])
                # 搜索响应
                elif "recent" in d:
                    edges = d["recent"].get("sections", [])

            for edge in edges[:max_notes - len(results)]:
                node = edge.get("node", edge)
                post = self._parse_graphql_node(node, tag)
                if post:
                    results.append(post)

            if len(results) >= max_notes:
                break

        return results[:max_notes]

    def _parse_graphql_node(self, node: dict, tag: str) -> dict | None:
        """解析 GraphQL 节点为统一帖子格式。"""
        shortcode = node.get("shortcode", "")
        if not shortcode:
            return None

        # 提取图片 URL
        images = []
        if "display_url" in node:
            images.append(node["display_url"])
        if "thumbnail_src" in node:
            images.append(node["thumbnail_src"])
        # 多图帖子
        sidecar = node.get("edge_sidecar_to_children", {})
        for child in sidecar.get("edges", []):
            child_url = child.get("node", {}).get("display_url", "")
            if child_url and child_url not in images:
                images.append(child_url)

        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
        caption = caption_edges[0]["node"]["text"] if caption_edges else ""

        owner = node.get("owner", {})

        return {
            "platform": self.platform,
            "post_id": shortcode,
            "url": f"https://www.instagram.com/p/{shortcode}/",
            "title": caption[:100] if caption else "",
            "content": caption,
            "image_urls": images[:10],
            "likes": node.get("edge_liked_by", {}).get("count", 0)
                     or node.get("edge_media_preview_like", {}).get("count", 0),
            "comments": node.get("edge_media_to_comment", {}).get("count", 0),
            "author": owner.get("username", ""),
            "keyword": tag,
        }

    def _extract_from_dom(self, page: Page, tag: str, max_notes: int) -> list[dict]:
        """从页面 DOM 中提取帖子链接作为兜底方案。"""
        results = []
        links = page.locator('a[href*="/p/"]')
        count = min(links.count(), max_notes)

        for i in range(count):
            href = links.nth(i).get_attribute("href") or ""
            if "/p/" in href:
                shortcode = href.split("/p/")[1].strip("/")
                img = links.nth(i).locator("img").first
                img_url = img.get_attribute("src") if img.count() > 0 else ""

                results.append({
                    "platform": self.platform,
                    "post_id": shortcode,
                    "url": f"https://www.instagram.com/p/{shortcode}/",
                    "title": "",
                    "content": "",
                    "image_urls": [img_url] if img_url else [],
                    "likes": 0,
                    "comments": 0,
                    "author": "",
                    "keyword": tag,
                })

        return results
