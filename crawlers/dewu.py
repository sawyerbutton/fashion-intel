"""得物价格监控爬虫：抓取得物上潮牌单品的价格信息。

得物（Poizon/Dewu）是国内主要的潮牌交易平台。
本模块通过搜索关键词获取商品价格、销量等数据。
"""

import json
import logging
import os
import time

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

from config.settings import DB_PATH
from crawlers.base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

STATE_PATH = os.path.join(os.path.dirname(DB_PATH), "dewu_state.json")

SEARCH_URL = "https://www.dewu.com/search/result?keyword={keyword}"


class DewuCrawler(BaseCrawler):
    platform = "dewu"

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

    def _do_search(self, keyword: str, max_notes: int, headed_override: bool = False) -> list[dict]:
        """执行搜索逻辑。"""
        context = self._start_browser(headed_override=headed_override)

        try:
            page = context.new_page()

            # 拦截 API 响应
            api_data = []

            def on_response(response):
                url = response.url
                if "search" in url and ("api" in url or "dewu.com" in url):
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        try:
                            api_data.append(response.json())
                        except Exception:
                            pass

            page.on("response", on_response)

            url = SEARCH_URL.format(keyword=keyword)
            self.logger.info("正在搜索得物: %s", keyword)
            page.goto(url, wait_until="domcontentloaded")
            self.random_delay(3, 5)

            # 如果是 headed 模式且页面没有加载出商品，等待用户操作
            if headed_override:
                cards = page.locator('[class*="product"], [class*="goods"], a[href*="product/detail"]')
                if cards.count() == 0:
                    self.logger.info("得物页面未加载商品，可能需要人工验证/登录...")
                    self.logger.info("请在浏览器中完成操作，页面加载出商品后将自动继续")
                    try:
                        page.wait_for_selector(
                            '[class*="product"], [class*="goods"], a[href*="product/detail"]',
                            timeout=120000,
                        )
                        self.random_delay(2, 3)
                    except Exception:
                        self.logger.warning("等待超时，尝试从已有数据提取")

            # 滚动加载
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 800)")
                self.random_delay(1, 2)

            # 优先从 API 数据提取
            results = self._extract_from_api(api_data, keyword, max_notes)

            # 兜底从 DOM 提取
            if not results:
                results = self._extract_from_dom(page, keyword, max_notes)

            self._save_state()
            return results

        finally:
            self._close_browser()

    def search(self, keyword: str, max_notes: int = 20) -> list[dict]:
        """搜索得物商品，返回价格信息。headless 失败时自动切换到 headed 模式。"""
        try:
            results = self._do_search(keyword, max_notes)
            if results:
                self.logger.info("得物搜索完成，共 %d 条结果", len(results))
                return results

            # headless 无结果，切换到 headed 模式
            self.logger.info("得物 headless 模式无结果，切换到 headed 模式...")
            results = self._do_search(keyword, max_notes, headed_override=True)
            self.logger.info("得物搜索完成，共 %d 条结果", len(results))
            return results

        except Exception as e:
            self.logger.error("得物搜索出错: %s", e)
            raise

    def _extract_from_api(self, data_list: list, keyword: str, max_notes: int) -> list[dict]:
        """从拦截的 API 响应中提取商品数据。"""
        results = []
        for data in data_list:
            # 得物 API 响应格式
            product_list = (
                data.get("data", {}).get("productList", [])
                or data.get("data", {}).get("list", [])
                or data.get("data", {}).get("root", {}).get("list", [])
            )
            for item in product_list[:max_notes - len(results)]:
                post = self._parse_product(item, keyword)
                if post:
                    results.append(post)
            if len(results) >= max_notes:
                break
        return results[:max_notes]

    def _parse_product(self, item: dict, keyword: str) -> dict | None:
        """解析得物商品数据。"""
        spuid = str(item.get("spuId", item.get("productId", "")))
        if not spuid:
            return None

        # 价格（得物以分为单位）
        price = item.get("price", 0)
        if isinstance(price, (int, float)) and price > 100:
            price = price / 100  # 分转元

        title = item.get("title", item.get("productName", ""))
        image = item.get("logoUrl", item.get("imageUrl", item.get("pic", "")))

        return {
            "platform": self.platform,
            "post_id": f"dewu_{spuid}",
            "url": f"https://www.dewu.com/product/detail?spuId={spuid}",
            "title": title,
            "content": f"价格: ¥{price:.0f}" if price else "",
            "image_urls": [image] if image else [],
            "likes": item.get("soldNum", item.get("salesVolume", 0)),  # 用销量代替点赞
            "comments": 0,
            "author": item.get("brandName", ""),
            "keyword": keyword,
        }

    def _extract_from_dom(self, page: Page, keyword: str, max_notes: int) -> list[dict]:
        """从页面 DOM 提取商品信息（兜底方案）。"""
        results = []
        cards = page.locator('[class*="product-card"], [class*="goods-item"], a[href*="product/detail"]')
        count = min(cards.count(), max_notes)

        for i in range(count):
            card = cards.nth(i)

            # 提取链接
            link = card.locator("a").first
            href = (link.get_attribute("href") or "") if link.count() > 0 else ""
            spuid = ""
            if "spuId=" in href:
                spuid = href.split("spuId=")[1].split("&")[0]

            # 标题
            title_el = card.locator('[class*="title"], [class*="name"]').first
            title = title_el.inner_text().strip() if title_el.count() > 0 else ""

            # 价格
            price_el = card.locator('[class*="price"]').first
            price_text = price_el.inner_text().strip() if price_el.count() > 0 else ""

            # 图片
            img_el = card.locator("img").first
            img_url = (img_el.get_attribute("src") or "") if img_el.count() > 0 else ""

            if title or spuid:
                results.append({
                    "platform": self.platform,
                    "post_id": f"dewu_{spuid}" if spuid else f"dewu_{i}",
                    "url": f"https://www.dewu.com{href}" if href.startswith("/") else href,
                    "title": title,
                    "content": price_text,
                    "image_urls": [img_url] if img_url else [],
                    "likes": 0,
                    "comments": 0,
                    "author": "",
                    "keyword": keyword,
                })

        return results
