"""数据库连接和 CRUD 操作。"""

import json
import sqlite3
from datetime import date, datetime
from typing import Optional

from config.settings import DB_PATH


def get_conn() -> sqlite3.Connection:
    """获取数据库连接，开启 Row 模式方便按列名取值。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────── raw_posts CRUD ───────────────────────


def insert_post(
    platform: str,
    post_id: str,
    url: str,
    title: str,
    content: str,
    image_urls: list[str],
    likes: int,
    comments: int,
    author: str,
    keyword: str,
) -> Optional[int]:
    """插入一条帖子，重复 post_id 则跳过。返回新行 id 或 None（已存在）。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO raw_posts
               (platform, post_id, url, title, content, image_urls,
                likes, comments, author, keyword)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                platform,
                post_id,
                url,
                title,
                content,
                json.dumps(image_urls),
                likes,
                comments,
                author,
                keyword,
            ),
        )
        conn.commit()
        return cur.lastrowid if cur.rowcount > 0 else None
    finally:
        conn.close()


def get_unanalyzed_posts(limit: int = 50) -> list[dict]:
    """获取未分析的帖子（is_analyzed=0）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM raw_posts WHERE is_analyzed = 0 ORDER BY crawled_at LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_post_analyzed(post_id: int) -> None:
    """标记帖子为已分析。"""
    conn = get_conn()
    try:
        conn.execute("UPDATE raw_posts SET is_analyzed = 1 WHERE id = ?", (post_id,))
        conn.commit()
    finally:
        conn.close()


def get_all_posts(limit: int = 100) -> list[dict]:
    """获取所有帖子，按时间倒序。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM raw_posts ORDER BY crawled_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────── analyzed_items CRUD ──────────────────────


def insert_analyzed_item(
    post_id: int,
    image_url: str,
    brand: str,
    item_type: str,
    colorway: str,
    logo_visible: bool,
    confidence: float,
    raw_response: str,
) -> int:
    """插入一条识别结果，返回新行 id。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO analyzed_items
               (post_id, image_url, brand, item_type, colorway,
                logo_visible, confidence, raw_response)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                post_id,
                image_url,
                brand,
                item_type,
                colorway,
                int(logo_visible),
                confidence,
                raw_response,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_items_by_brand(brand: str, limit: int = 100) -> list[dict]:
    """按品牌查询识别结果。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM analyzed_items WHERE brand = ? ORDER BY analyzed_at DESC LIMIT ?",
            (brand, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_items(limit: int = 500) -> list[dict]:
    """获取所有识别结果，按时间倒序。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM analyzed_items ORDER BY analyzed_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────── trend_scores CRUD ────────────────────────


def insert_trend_score(
    brand: str,
    item_type: str,
    score_date: date,
    mention_count: int,
    avg_likes: float,
    hot_score: float,
    breakout_prob: float,
    related_idols: list[str],
) -> int:
    """插入一条趋势评分，返回新行 id。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO trend_scores
               (brand, item_type, score_date, mention_count,
                avg_likes, hot_score, breakout_prob, related_idols)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                brand,
                item_type,
                score_date.isoformat(),
                mention_count,
                avg_likes,
                hot_score,
                breakout_prob,
                json.dumps(related_idols),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_latest_scores(limit: int = 20) -> list[dict]:
    """获取最新的趋势评分。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM trend_scores ORDER BY score_date DESC, hot_score DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────── alerts_log CRUD ──────────────────────────


def insert_alert(
    alert_type: str,
    brand: str,
    item_type: str,
    message: str,
) -> int:
    """插入一条预警记录，返回新行 id。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO alerts_log (alert_type, brand, item_type, message) VALUES (?, ?, ?, ?)",
            (alert_type, brand, item_type, message),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_recent_alerts(limit: int = 50) -> list[dict]:
    """获取最近的预警记录。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM alerts_log ORDER BY sent_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
