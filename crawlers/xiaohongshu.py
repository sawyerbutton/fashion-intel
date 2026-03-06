"""小红书爬虫：基于 Playwright + Vue 状态提取搜索结果。

使用前须知：
  1. 首次运行需执行 `playwright install chromium`
  2. 小红书搜索页需要登录态才能拿到完整结果
     - 首次运行会弹出浏览器窗口，手动登录后脚本自动保存 cookie
     - 后续运行自动复用 cookie（保存在 ./data/xhs_state.json）
"""

import json
import logging
import os
import time

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

from config.settings import DB_PATH
from crawlers.base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

# 浏览器状态文件（保存 cookie/localStorage）
STATE_PATH = os.path.join(os.path.dirname(DB_PATH), "xhs_state.json")

SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={keyword}&source=web_search_result_notes"

# 从 Vue __INITIAL_STATE__ 提取搜索结果的 JS 脚本
JS_EXTRACT_FEEDS = """() => {
    var s = (window.__INITIAL_STATE__ || {}).search;
    if (!s || !s.feeds) return [];
    var feeds = s.feeds._rawValue || s.feeds._value || s.feeds;
    if (!Array.isArray(feeds)) return [];
    return feeds.map(function(f) {
        var nc = f.noteCard || {};
        var user = nc.user || {};
        var interact = nc.interactInfo || {};
        var images = (nc.imageList || []).map(function(img) {
            var info = (img.infoList || []);
            var url = '';
            for (var i = 0; i < info.length; i++) {
                if (info[i].url) { url = info[i].url; break; }
            }
            if (!url && img.urlDefault) url = img.urlDefault;
            return url;
        }).filter(function(u) { return u; });
        var cover = nc.cover || {};
        var coverUrl = '';
        var coverInfo = cover.infoList || [];
        for (var i = 0; i < coverInfo.length; i++) {
            if (coverInfo[i].url) { coverUrl = coverInfo[i].url; break; }
        }
        if (!coverUrl && cover.urlDefault) coverUrl = cover.urlDefault;
        if (!images.length && coverUrl) images = [coverUrl];
        return {
            id: f.id || '',
            title: nc.displayTitle || '',
            desc: nc.desc || '',
            author: user.nickname || user.nickName || '',
            likes: parseInt(interact.likedCount || '0', 10),
            comments: parseInt(interact.commentCount || '0', 10),
            collected: parseInt(interact.collectedCount || '0', 10),
            images: images,
            coverUrl: coverUrl,
            type: nc.type || ''
        };
    });
}"""


class XiaohongshuCrawler(BaseCrawler):
    platform = "xiaohongshu"

    def __init__(self, headless: bool = True):
        super().__init__()
        self.headless = headless
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    # ───────────────── 浏览器生命周期 ─────────────────

    def _start_browser(self) -> BrowserContext:
        """启动浏览器并返回上下文。优先加载已保存的登录态。"""
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)

        kwargs = {
            "user_agent": self.random_ua(),
            "viewport": {"width": 1920, "height": 1080},
        }
        if os.path.exists(STATE_PATH):
            self.logger.info("加载已保存的登录态: %s", STATE_PATH)
            kwargs["storage_state"] = STATE_PATH

        self._context = self._browser.new_context(**kwargs)
        return self._context

    def _save_state(self) -> None:
        """保存浏览器登录态到文件。"""
        if self._context:
            os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
            self._context.storage_state(path=STATE_PATH)
            self.logger.info("登录态已保存: %s", STATE_PATH)

    def _close_browser(self) -> None:
        """关闭浏览器，释放资源。"""
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    # ───────────────── 登录检测 ─────────────────

    def _check_login(self, page: Page) -> bool:
        """检测当前页面是否已登录。"""
        login_indicators = page.locator(
            'text="登录后查看搜索结果", text="手机号登录", '
            '[class*="qrcode-img"]'
        )
        if login_indicators.count() > 0:
            return False
        login_btn = page.locator('.side-bar >> text="登录"')
        if login_btn.count() > 0:
            return False
        return True

    def _ensure_login(self, page: Page, search_url: str) -> Page:
        """确保已登录，如未登录则弹窗等待手动登录。返回可用的 page。"""
        if self._check_login(page):
            return page

        # 切到有头模式让用户登录
        self._close_browser()
        self.headless = False
        context = self._start_browser()
        page = context.new_page()
        page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")
        self.random_delay(2, 3)

        self.logger.warning("=" * 50)
        self.logger.warning("请在浏览器窗口中登录小红书（扫码或手机号）")
        self.logger.warning("登录成功后脚本将自动继续...")
        self.logger.warning("=" * 50)

        # 轮询等待登录成功（最多 5 分钟）
        deadline = time.time() + 300
        while time.time() < deadline:
            time.sleep(3)
            login_modal = page.locator(
                'text="手机号登录", [class*="qrcode-img"]'
            )
            login_btn = page.locator('.side-bar >> text="登录"')
            if login_modal.count() == 0 and login_btn.count() == 0:
                time.sleep(3)
                self.logger.info("检测到登录成功！")
                self._save_state()
                # 跳转到搜索页
                page.goto(search_url, wait_until="domcontentloaded")
                self.random_delay(3, 5)
                return page

        raise TimeoutError("等待登录超时（5分钟），请重试")

    # ───────────────── 核心搜索逻辑 ─────────────────

    def search(self, keyword: str, max_notes: int = 20) -> list[dict]:
        """搜索关键词，抓取笔记列表。

        通过提取页面 Vue 状态 (window.__INITIAL_STATE__) 获取数据，
        比 DOM 选择器更稳定可靠。

        Args:
            keyword: 搜索关键词，如 "Stussy 穿搭"
            max_notes: 最多抓取笔记数

        Returns:
            帖子字典列表，每条包含 platform/post_id/url/title/...
        """
        context = self._start_browser()

        try:
            page = context.new_page()
            url = SEARCH_URL.format(keyword=keyword)
            self.logger.info("正在搜索: %s", keyword)
            page.goto(url, wait_until="domcontentloaded")
            self.random_delay(3, 5)

            # 确保登录
            page = self._ensure_login(page, url)

            # 滚动加载更多
            self._scroll_to_load(page, max_notes)

            # 从 Vue 状态提取数据
            raw_feeds = page.evaluate(JS_EXTRACT_FEEDS)
            self.logger.info("从 Vue 状态提取到 %d 条笔记", len(raw_feeds))

            # 转换为统一格式
            results = []
            for feed in raw_feeds[:max_notes]:
                if not feed.get("id"):
                    continue
                results.append({
                    "platform": self.platform,
                    "post_id": feed["id"],
                    "url": f"https://www.xiaohongshu.com/explore/{feed['id']}",
                    "title": feed.get("title", ""),
                    "content": feed.get("desc", ""),
                    "image_urls": feed.get("images", []),
                    "likes": feed.get("likes", 0),
                    "comments": feed.get("comments", 0),
                    "author": feed.get("author", ""),
                })

            self._save_state()
            self.logger.info("搜索完成，共 %d 条结果", len(results))
            return results

        except Exception as e:
            self.logger.error("搜索过程出错: %s", e)
            raise
        finally:
            self._close_browser()

    # ───────────────── 辅助方法 ─────────────────

    def _scroll_to_load(self, page: Page, target_count: int, max_scrolls: int = 10) -> None:
        """向下滚动页面以触发更多数据加载。"""
        for i in range(max_scrolls):
            # 检查当前 feeds 数量
            count = page.evaluate(
                "() => { var s = (window.__INITIAL_STATE__ || {}).search;"
                "var f = s && s.feeds ? (s.feeds._rawValue || s.feeds._value || s.feeds) : [];"
                "return Array.isArray(f) ? f.length : 0; }"
            )
            if count >= target_count:
                break
            page.evaluate("window.scrollBy(0, 800)")
            self.random_delay(1, 2)

    @staticmethod
    def _parse_count(text: str) -> int:
        """把 '1.2万' / '1.2w' / '1,234' 等转为整数。"""
        text = text.strip().replace(",", "")
        if not text or text == "赞" or text == "评论":
            return 0
        try:
            if "万" in text or "w" in text.lower():
                num = float(text.replace("万", "").replace("w", "").replace("W", ""))
                return int(num * 10000)
            return int(float(text))
        except (ValueError, TypeError):
            return 0
