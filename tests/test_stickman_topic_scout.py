import pytest
from hevi.stickman.topic_scout import scout_topics, calculate_viral_score, parse_topic_records


def test_calculate_viral_score():
    # Channel with low uploads (2/mo) and huge views (500k vs 50k subs)
    res = calculate_viral_score(views=500_000, subscribers=50_000, monthly_uploads=2.0)
    assert res["viral_ratio"] == 10.0
    assert res["freq_weight"] == 2.5  # 10 / (2+2) = 2.5
    assert res["score"] >= 25.0
    assert res["tag"] == "极少发特大爆款"

    # High frequency channel (30 uploads/month) with low viral ratio (10k views, 50k subs)
    res2 = calculate_viral_score(views=10_000, subscribers=50_000, monthly_uploads=30.0)
    assert res2["viral_ratio"] == 0.2
    assert res2["freq_weight"] < 0.5
    assert res2["score"] < 1.0
    assert res2["tag"] == "常规平销"


def test_scout_topics_csv():
    csv_data = """channel_name,title,views,subscribers,monthly_uploads,likes,comments
极简思维,为什么冰块放水里会浮放油里沉下去,850000,45000,2,35000,2100
量产搬运,10个神奇冷知识,120000,100000,40,2000,150
硬核拆解,沉没成本陷阱：越努力为什么越穷,620000,50000,3,28000,1800
"""
    results = scout_topics(csv_data)
    assert len(results) == 3
    # Top 1 should be 极简思维 due to low upload (2/mo) and huge views (850k vs 45k)
    assert results[0]["title"] == "为什么冰块放水里会浮放油里沉下去"
    assert results[0]["rank"] == 1
    assert results[0]["score"] > results[1]["score"]
    # Lowest should be 量产搬运 (40 uploads/month)
    assert results[-1]["channel_name"] == "量产搬运"
    assert results[-1]["rank"] == 3


def test_scout_topics_dict_and_filter():
    records = [
        {"title": "选题A", "views": 1000, "subscribers": 500, "monthly_uploads": 1},
        {"title": "选题B", "views": 50000, "subscribers": 2000, "monthly_uploads": 2},
    ]
    res = scout_topics(records, min_views=5000)
    assert len(res) == 1
    assert res[0]["title"] == "选题B"
    assert res[0]["rank"] == 1
