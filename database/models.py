"""SQLite 表结构定义与数据库初始化。"""

import os
import sqlite3

from config.settings import DB_PATH

SQL_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS raw_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT NOT NULL,
    post_id     TEXT UNIQUE,
    url         TEXT,
    title       TEXT,
    content     TEXT,
    image_urls  TEXT,
    likes       INTEGER DEFAULT 0,
    comments    INTEGER DEFAULT 0,
    author      TEXT,
    keyword     TEXT,
    crawled_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_analyzed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS analyzed_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         INTEGER REFERENCES raw_posts(id),
    image_url       TEXT,
    brand           TEXT,
    item_type       TEXT,
    colorway        TEXT,
    logo_visible    INTEGER DEFAULT 0,
    confidence      REAL,
    raw_response    TEXT,
    analyzed_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trend_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    brand           TEXT,
    item_type       TEXT,
    score_date      DATE,
    mention_count   INTEGER DEFAULT 0,
    avg_likes       REAL DEFAULT 0,
    hot_score       REAL DEFAULT 0,
    breakout_prob   REAL DEFAULT 0,
    related_idols   TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type  TEXT,
    brand       TEXT,
    item_type   TEXT,
    message     TEXT,
    sent_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db() -> None:
    """创建数据库文件和所有表。"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SQL_CREATE_TABLES)
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化: {DB_PATH}")
