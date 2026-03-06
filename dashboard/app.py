"""Streamlit 可视化看板：展示爬取数据和识别结果。

启动方式：streamlit run dashboard/app.py
"""

import json
import sys
import os

# 确保项目根目录在 sys.path 中（streamlit 运行时 cwd 可能不同）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd

from database.models import init_db
from database.db import get_all_posts, get_all_items, get_latest_scores, get_recent_alerts

# 初始化数据库（确保表存在）
init_db()

st.set_page_config(page_title="潮流情报看板", page_icon="🔥", layout="wide")
st.title("🔥 潮流情报看板")

# ───────────────── 侧边栏 ─────────────────

st.sidebar.header("筛选")
view = st.sidebar.radio("查看", ["帖子数据", "识别结果", "趋势评分", "预警记录"])

# ───────────────── 帖子数据 ─────────────────

if view == "帖子数据":
    st.header("📋 爬取的帖子")
    posts = get_all_posts(limit=200)

    if not posts:
        st.info("暂无数据，请先运行爬虫抓取帖子。")
    else:
        df = pd.DataFrame(posts)

        # 统计指标
        col1, col2, col3 = st.columns(3)
        col1.metric("帖子总数", len(df))
        col2.metric("已分析", int(df["is_analyzed"].sum()))
        col3.metric("待分析", int((df["is_analyzed"] == 0).sum()))

        # 平台筛选
        platforms = df["platform"].unique().tolist()
        selected_platform = st.sidebar.selectbox("平台", ["全部"] + platforms)
        if selected_platform != "全部":
            df = df[df["platform"] == selected_platform]

        # 表格展示
        display_cols = ["id", "platform", "title", "author", "likes", "comments", "keyword", "crawled_at", "is_analyzed"]
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

        # 展开查看详情
        st.subheader("帖子详情")
        post_id = st.selectbox("选择帖子 ID", df["id"].tolist())
        if post_id:
            post = df[df["id"] == post_id].iloc[0]
            st.write(f"**标题**: {post['title']}")
            st.write(f"**作者**: {post['author']}")
            st.write(f"**内容**: {post['content']}")
            st.write(f"**链接**: {post['url']}")

            # 展示图片
            try:
                images = json.loads(post["image_urls"]) if post["image_urls"] else []
                if images:
                    st.write("**图片**:")
                    cols = st.columns(min(len(images), 3))
                    for i, img in enumerate(images[:6]):
                        cols[i % 3].image(img, use_container_width=True)
            except (json.JSONDecodeError, TypeError):
                pass

# ───────────────── 识别结果 ─────────────────

elif view == "识别结果":
    st.header("🏷️ Gemini Vision 识别结果")
    items = get_all_items(limit=200)

    if not items:
        st.info("暂无识别结果，请先运行 Gemini Vision 分析。")
    else:
        df = pd.DataFrame(items)

        # 品牌统计
        st.subheader("品牌分布")
        brand_counts = df["brand"].value_counts()
        st.bar_chart(brand_counts)

        # 单品类型统计
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("单品类型分布")
            type_counts = df["item_type"].value_counts()
            st.bar_chart(type_counts)
        with col2:
            st.subheader("平均置信度（按品牌）")
            avg_conf = df.groupby("brand")["confidence"].mean().sort_values(ascending=False)
            st.bar_chart(avg_conf)

        # 筛选
        brands = df["brand"].unique().tolist()
        selected_brand = st.sidebar.selectbox("品牌筛选", ["全部"] + sorted(brands))
        if selected_brand != "全部":
            df = df[df["brand"] == selected_brand]

        # 表格
        display_cols = ["id", "post_id", "brand", "item_type", "colorway", "logo_visible", "confidence", "analyzed_at"]
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

# ───────────────── 趋势评分 ─────────────────

elif view == "趋势评分":
    st.header("📈 趋势评分")
    scores = get_latest_scores(limit=50)

    if not scores:
        st.info("暂无趋势评分数据。")
    else:
        df = pd.DataFrame(scores)

        # 热度排行
        st.subheader("热度 TOP 10")
        top = df.nlargest(10, "hot_score")[["brand", "item_type", "hot_score", "breakout_prob", "mention_count", "score_date"]]
        st.dataframe(top, use_container_width=True, hide_index=True)

        # 爆款概率
        st.subheader("爆款概率分布")
        st.bar_chart(df.set_index("brand")["breakout_prob"])

# ───────────────── 预警记录 ─────────────────

elif view == "预警记录":
    st.header("🚨 预警推送记录")
    alerts = get_recent_alerts(limit=50)

    if not alerts:
        st.info("暂无预警记录。")
    else:
        df = pd.DataFrame(alerts)
        st.dataframe(df, use_container_width=True, hide_index=True)
