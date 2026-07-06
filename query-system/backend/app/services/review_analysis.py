"""评论分析：情感打分 + 关键词提取。

- 情感：英文用 VADER (vaderSentiment)，中文用 SnowNLP。按评论文本自动判断语言。
- 关键词：中文用 jieba 分词，英文用正则分词，统一去停用词后按 TF 计权取 Top N。
所有第三方库均为可选依赖，缺失时回退到基于星级/词频的简单实现，保证不崩。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import List, Sequence

from ..models import KeywordWeight, Review, ReviewAnalysis

_CJK_RE = re.compile(r"[一-鿿]")
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-']+")

_EN_STOP = {
    "the", "and", "for", "with", "this", "that", "was", "are", "you", "your",
    "have", "has", "had", "but", "not", "very", "would", "they", "them", "its",
    "it's", "get", "got", "one", "all", "can", "will", "just", "out", "use",
    "used", "using", "product", "amazon", "item", "really", "much", "more",
    "than", "when", "what", "from", "been", "were", "which", "about", "some",
    "any", "too", "also", "into", "over", "after", "before", "there", "their",
}
_CN_STOP = {
    "的", "了", "和", "是", "在", "我", "有", "也", "就", "都", "很", "不", "这",
    "那", "个", "上", "还", "为", "与", "以", "及", "对", "但", "让", "被", "把",
    "非常", "可以", "使用", "产品", "东西", "购买", "商品", "感觉", "觉得",
}


def _detect_language(text: str) -> str:
    return "zh" if _CJK_RE.search(text) else "en"


def _sentiment_en(text: str) -> float | None:
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    except ImportError:
        return None
    score = SentimentIntensityAnalyzer().polarity_scores(text)["compound"]
    return (score + 1) / 2  # 归一化到 0-1


def _sentiment_zh(text: str) -> float | None:
    try:
        from snownlp import SnowNLP
    except ImportError:
        return None
    try:
        return float(SnowNLP(text).sentiments)
    except Exception:
        return None


def _sentiment_from_rating(review: Review) -> float:
    return (review.rating / 5.0) if review.rating else 0.5


def _tokens(text: str, lang: str) -> List[str]:
    if lang == "zh":
        try:
            import jieba

            words = [w.strip() for w in jieba.cut(text) if len(w.strip()) > 1]
        except ImportError:
            words = _CJK_RE.findall(text)
        return [w for w in words if w not in _CN_STOP]
    words = [w.lower() for w in _WORD_RE.findall(text)]
    return [w for w in words if w not in _EN_STOP and len(w) > 2]


def analyze_reviews(reviews: Sequence[Review], top_keywords: int = 15) -> ReviewAnalysis:
    if not reviews:
        return ReviewAnalysis()

    corpus = " ".join(r.body for r in reviews if r.body)
    lang = _detect_language(corpus)

    scores: List[float] = []
    for r in reviews:
        text = (r.body or "").strip()
        s = None
        if text:
            s = _sentiment_zh(text) if lang == "zh" else _sentiment_en(text)
        if s is None:
            s = _sentiment_from_rating(r)
        scores.append(s)

    avg = sum(scores) / len(scores)
    pos = sum(1 for s in scores if s >= 0.6) / len(scores)
    neg = sum(1 for s in scores if s < 0.4) / len(scores)
    neu = 1 - pos - neg

    # 关键词：TF * log 长度权重
    counter: Counter = Counter()
    for r in reviews:
        counter.update(_tokens(r.body or "", lang))
    total = sum(counter.values()) or 1
    keywords = [
        KeywordWeight(keyword=w, weight=round((c / total) * math.log(1 + c), 4))
        for w, c in counter.most_common(top_keywords)
    ]

    return ReviewAnalysis(
        total_reviews=len(reviews),
        sentiment_score=round(avg, 4),
        positive_ratio=round(pos, 4),
        neutral_ratio=round(max(neu, 0.0), 4),
        negative_ratio=round(neg, 4),
        top_keywords=keywords,
        language=lang,
    )
