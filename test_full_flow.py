"""
全流程测试：9 话题 x 2 篇 = 18 篇，脉脉+头条+公众号全走 MultiPost
从 posts/test_flow_posts.txt 读取帖子内容
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from adapter.image_search import search_and_download
from config import PROJECT_ROOT
from publisher.multipost import MultiPostPublisher

# 9 个话题名称（= 脉脉标题 = 脉脉话题，2篇共用一个话题）
TOPICS = [
    ("华为何庭波发布V2版韬定律论文", "Huawei semiconductor chip technology"),
    ("美团开源LongCat2.0", "AI artificial intelligence large language model"),
    ("优必选回应99万机器人续航撑不过一晚", "humanoid robot technology future"),
    ("TikTok全球多地裁员，印尼电商业务大幅收缩", "TikTok social media app office layoff"),
    ("传WPS滥收费、背刺用户，金山回应", "software subscription payment digital"),
    ("A股集体高开，存储芯片等走强", "semiconductor memory chip technology"),
    ("腾讯发布并开源混元Hy3模型", "AI model technology neural network"),
    ("原抖音直播负责人钱景离职", "corporate office executive meeting departure"),
    ("保时捷计划再裁4000人，行政成重灾区", "Porsche luxury car factory"),
]


def load_posts(filepath):
    """从文本文件加载帖子，用 --- 分隔"""
    content = Path(filepath).read_text(encoding="utf-8")
    bodies = [b.strip() for b in content.split("---") if b.strip()]
    assert len(bodies) == 18, f"Expected 18 posts, got {len(bodies)}"
    return bodies


def search_images(topics):
    """为每个话题搜索1张配图（Pexels英文关键词）"""
    img_dir = str(PROJECT_ROOT / "posts" / "test_flow_images")
    Path(img_dir).mkdir(parents=True, exist_ok=True)

    topic_images = {}
    for i, (topic, query) in enumerate(topics, 1):
        from loguru import logger
        logger.info(f"🔍 [{i}/{len(topics)}] 搜图: {topic} → {query}")
        img_path = search_and_download(
            query, img_dir, skip_web=True, pexels_query=query,
        )
        if img_path:
            topic_images[topic] = [img_path]
            logger.info(f"  ✓ 图片: {img_path}")
        else:
            logger.warning(f"  ⚠️ 未搜到图片，跳过")
            topic_images[topic] = []
        time.sleep(1)

    return topic_images


def main():
    from loguru import logger

    # ===== 第1步：加载帖子 =====
    logger.info("=" * 55)
    logger.info("📄 第1步：加载帖子内容")
    logger.info("=" * 55)
    bodies = load_posts(PROJECT_ROOT / "posts" / "test_flow_posts.txt")
    logger.info(f"  ✓ 加载 {len(bodies)} 篇帖子")

    # ===== 第2步：搜图 =====
    logger.info("\n" + "=" * 55)
    logger.info("📷 第2步：搜索配图（Pexels API）")
    logger.info("=" * 55)
    topic_images = search_images(TOPICS)

    # ===== 第3步：组装帖子 =====
    # 标题 = 话题名称，正文 = 原文不改，话题 = 话题名称
    posts = []
    for i in range(18):
        topic_idx = i // 2  # 每话题2篇
        topic_name = TOPICS[topic_idx][0]
        posts.append({
            "title": topic_name,       # 标题 = 话题名
            "body": bodies[i],          # 正文 = 原文不改
            "image_paths": topic_images.get(topic_name, []),
            "topic": topic_name,        # 脉脉话题 = 话题名
        })

    with_img = sum(1 for p in posts if p.get("image_paths"))
    logger.info(f"\n📋 共 {len(posts)} 篇帖子（有配图: {with_img}，无配图: {len(posts) - with_img}）")

    # ===== 第4步：批量发布 =====
    logger.info("\n" + "=" * 55)
    logger.info("🚀 第3步：批量发布（脉脉+头条+公众号，3分钟间隔）")
    logger.info("=" * 55)

    mp = MultiPostPublisher()
    if not mp.connect():
        logger.error("❌ Chrome 连接失败")
        return

    result = mp.batch_post(
        posts=posts,
        platforms=["脉脉", "今日头条", "微信公众号"],
        interval=180,
        dry_run=False,
        cleanup_images=True,
    )

    mp.disconnect()

    logger.info(f"\n🏁 最终结果: 成功 {result['success']}, 失败 {result['failed']}")
    for r in result["results"]:
        logger.info(f"  第{r['index']}篇: {r['status']}")


if __name__ == "__main__":
    main()
