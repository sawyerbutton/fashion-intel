"""Gemini Vision 图片单品识别：批量分析帖子图片，识别潮牌单品。"""

import json
import logging
import re
import time

from google import genai
from google.genai import types

from config.settings import GEMINI_API_KEY, VISION_PROMPT
from database.db import (
    get_unanalyzed_posts,
    insert_analyzed_item,
    mark_post_analyzed,
)

# 品牌名称标准化映射（统一 Gemini 返回的各种拼写变体）
BRAND_NORMALIZE = {
    "stüssy": "Stussy",
    "STÜSSY": "Stussy",
    "stussy": "Stussy",
    "STUSSY": "Stussy",
    "Stüssy": "Stussy",
    "supreme": "Supreme",
    "SUPREME": "Supreme",
    "bape": "BAPE",
    "Bape": "BAPE",
    "A Bathing Ape": "BAPE",
    "carhartt": "Carhartt",
    "CARHARTT": "Carhartt",
    "Carhartt WIP": "Carhartt",
    "palace": "Palace",
    "PALACE": "Palace",
    "nike": "Nike",
    "NIKE": "Nike",
    "adidas": "Adidas",
    "ADIDAS": "Adidas",
    "new balance": "New Balance",
    "NEW BALANCE": "New Balance",
    "the north face": "The North Face",
    "THE NORTH FACE": "The North Face",
    "TNF": "The North Face",
    "converse": "Converse",
    "CONVERSE": "Converse",
    "vans": "Vans",
    "VANS": "Vans",
    "champion": "Champion",
    "CHAMPION": "Champion",
    "dickies": "Dickies",
    "DICKIES": "Dickies",
    "wtaps": "WTAPS",
    "Wtaps": "WTAPS",
    "neighborhood": "NEIGHBORHOOD",
    "Neighborhood": "NEIGHBORHOOD",
    "human made": "HUMAN MADE",
    "Human Made": "HUMAN MADE",
    "chrome hearts": "Chrome Hearts",
    "CHROME HEARTS": "Chrome Hearts",
    "goyard": "Goyard",
    "GOYARD": "Goyard",
    "mlb": "MLB",
    "new era": "New Era",
    "NEW ERA": "New Era",
    "issey miyake": "Issey Miyake",
    "ISSEY MIYAKE": "Issey Miyake",
    "Bao Bao Issey Miyake": "Issey Miyake",
    "prada": "Prada",
    "PRADA": "Prada",
    "chanel": "Chanel",
    "CHANEL": "Chanel",
    "% Arabica": "% ARABICA",
    "% ARABICA": "% ARABICA",
    "eM°t": "eMt",
    "EMT": "eMt",
    "eMto": "eMt",
    "MONCLER": "Moncler",
    "moncler": "Moncler",
    "STONE ISLAND": "Stone Island",
    "stone island": "Stone Island",
    "DR.MARTENS": "Dr. Martens",
    "Dr.Martens": "Dr. Martens",
    "dr. martens": "Dr. Martens",
    "DR. MARTENS": "Dr. Martens",
    "fragment design": "Fragment Design",
    "FRAGMENT DESIGN": "Fragment Design",
    "FILA": "Fila",
    "fila": "Fila",
    "FILA FUSION": "Fila",
    "Fila Fusion": "Fila",
    "drew house": "Drew House",
    "DREW HOUSE": "Drew House",
    "Drew house": "Drew House",
    "LOUIS VUITTON": "Louis Vuitton",
    "louis vuitton": "Louis Vuitton",
    "LV": "Louis Vuitton",
    "RICKOWENS": "Rick Owens",
    "Rick owens": "Rick Owens",
    "rick owens": "Rick Owens",
}

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
_client = None


def _get_client() -> genai.Client:
    """惰性初始化 Gemini 客户端（避免无 API Key 时导入即报错）。"""
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY 未设置，请在 .env 文件中配置")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _normalize_brand(brand: str) -> str:
    """标准化品牌名称，统一各种拼写变体。"""
    if not brand or brand.lower() in ("unknown", "未知", "无品牌"):
        return "unknown"
    return BRAND_NORMALIZE.get(brand, brand)


def _fix_json_text(text: str) -> str:
    """修复 Gemini 返回的非标准 JSON。"""
    # 去掉可能的 markdown 代码块包裹
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
        text = text.strip()

    # 修复缺少闭合大括号的数组元素（如 "confidence": 1.0 ,\n    { → "confidence": 1.0 },\n    {）
    text = re.sub(
        r'("confidence"\s*:\s*[\d.]+)\s*,(\s*\{)',
        r"\1},\2",
        text,
    )
    # 去尾部逗号
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # JS 风格布尔值
    text = text.replace(": True", ": true").replace(": False", ": false")
    # 单引号替换为双引号
    text = re.sub(r"(?<=[\[{,])\s*'([^']+)'\s*:", r' "\1":', text)
    text = re.sub(r":\s*'([^']*)'", r': "\1"', text)

    return text


def analyze_image(image_url: str, post_context: str = "") -> dict | None:
    """用 Gemini Vision 分析单张图片，返回解析后的 JSON 结果。

    Args:
        image_url: 图片 URL
        post_context: 帖子上下文（标题、关键词等），帮助 Gemini 更准确地识别品牌
    """
    prompt = VISION_PROMPT.replace("{post_context}", post_context or "无")
    try:
        response = _get_client().models.generate_content(
            model=MODEL,
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_uri(file_uri=image_url, mime_type="image/jpeg"),
                        types.Part.from_text(text=prompt),
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )

        text = _fix_json_text(response.text.strip())
        return json.loads(text)

    except json.JSONDecodeError as e:
        logger.warning("Gemini 返回内容无法解析为 JSON: %s | 原文: %s", e, text[:200])
        return None
    except Exception as e:
        logger.error("Gemini API 调用失败 (%s): %s", image_url, e)
        return None


def process_post(post: dict) -> int:
    """处理单条帖子的所有图片，返回识别出的单品数。"""
    post_db_id = post["id"]
    image_urls = json.loads(post["image_urls"]) if post["image_urls"] else []

    if not image_urls:
        logger.debug("帖子 %d 无图片，跳过", post_db_id)
        mark_post_analyzed(post_db_id)
        return 0

    # 构建帖子上下文，帮助 Gemini 更准确识别
    context_parts = []
    if post.get("title"):
        context_parts.append(f"帖子标题: {post['title']}")
    if post.get("keyword"):
        context_parts.append(f"搜索关键词: {post['keyword']}")
    if post.get("content"):
        context_parts.append(f"帖子正文: {post['content'][:200]}")
    post_context = "\n".join(context_parts)

    total_items = 0

    for img_url in image_urls:
        result = analyze_image(img_url, post_context=post_context)
        if not result or "items" not in result:
            continue

        raw_response = json.dumps(result, ensure_ascii=False)

        for item in result["items"]:
            insert_analyzed_item(
                post_id=post_db_id,
                image_url=img_url,
                brand=_normalize_brand(item.get("brand", "unknown")),
                item_type=item.get("item_type", "unknown"),
                colorway=item.get("colorway", ""),
                logo_visible=item.get("logo_visible", False),
                confidence=item.get("confidence", 0.0),
                raw_response=raw_response,
            )
            total_items += 1

        # Gemini API 限流保护：每张图之间间隔一下
        time.sleep(1)

    mark_post_analyzed(post_db_id)
    return total_items


def run_batch_analysis(limit: int = 50) -> dict:
    """批量分析未处理的帖子。

    Returns:
        {"posts_processed": int, "items_found": int}
    """
    posts = get_unanalyzed_posts(limit=limit)
    if not posts:
        logger.info("没有待分析的帖子")
        return {"posts_processed": 0, "items_found": 0}

    logger.info("开始批量分析，共 %d 条待处理帖子", len(posts))
    total_items = 0

    for i, post in enumerate(posts):
        logger.info(
            "[%d/%d] 分析帖子: %s",
            i + 1,
            len(posts),
            post.get("title", "")[:30],
        )
        try:
            count = process_post(post)
            total_items += count
            logger.info("  → 识别出 %d 个单品", count)
        except Exception as e:
            logger.error("  → 处理失败: %s", e)

    result = {"posts_processed": len(posts), "items_found": total_items}
    logger.info("批量分析完成: %s", result)
    return result
