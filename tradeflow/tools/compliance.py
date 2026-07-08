"""#1 合规风控智能体的工具集（底层守门员，被 #2 #3 #5 #6 #7 #8 调用）。

全部数据驱动，经数据层 (0.3) 读 `data/compliance/`，代码里不硬编码词表：
- `check_forbidden_words(text, site)`   —— 极限词/医疗夸大词（分站点，1.1/1.2）
- `match_ip_brand_patent(text)`         —— 品牌/商标/IP/专利话术（1.3）
- `flag_category_risk(category)`        —— 类目审核/侵权风险等级（1.5）
- `compliance_gate(text, category, site)` —— 统一入口（1.6），应用白名单（1.7）

设计原则：宁可误伤不可漏放；命中即给"违规点 + 位置 + 合规替代"。白名单（自有品牌词
/ 已确认合规表达）在 `compliance_gate` 层放行并记录 overridden，避免误伤无出口。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List

from ..data_loader import load_data
from .base import tool

# 表缺失时的兜底极限词，保证"缺文件不崩"仍能拦最典型的违规。
_SEED_FORBIDDEN = ["best", "no.1", "100% cure", "fda approved", "cheapest"]


@lru_cache(maxsize=None)
def _forbidden_table(site: str) -> tuple:
    """读并缓存某站点禁词表；缺表回退内置种子词。返回 tuple 以便 lru_cache 缓存。"""
    rows = load_data("compliance", f"禁词表_{site}.csv", required_columns=["违规词"])
    if not rows:
        rows = [{"违规词": w, "类型": "极限词", "合规替代": "", "说明": "内置兜底"}
                for w in _SEED_FORBIDDEN]
    return tuple(rows)  # type: ignore[arg-type]


@lru_cache(maxsize=None)
def _ip_table() -> tuple:
    return tuple(load_data("compliance", "品牌IP黑名单.csv", required_columns=["名称"]))


@lru_cache(maxsize=None)
def _category_table() -> tuple:
    return tuple(load_data("compliance", "类目风险.csv", required_columns=["类目"]))


@lru_cache(maxsize=None)
def _whitelist() -> tuple:
    """白名单短语（小写）。命中这些短语内部的违规词在 gate 层放行。"""
    rows = load_data("compliance", "白名单.csv")
    return tuple((r.get("短语", "").strip().lower()) for r in rows if r.get("短语"))


def _scan(text: str, table, key: str) -> List[Dict[str, object]]:
    """在 text 中大小写不敏感地找 table 里 key 列的每个词，返回命中列表。"""
    lowered = text.lower()
    hits: List[Dict[str, object]] = []
    for row in table:
        term = (row.get(key, "") or "").strip()
        if not term:
            continue
        pos = lowered.find(term.lower())
        if pos != -1:
            hits.append({
                "词": term,
                "类型": row.get("类型", ""),
                "位置": pos,
                "合规替代": row.get("合规替代", ""),
            })
    return hits


@tool
def check_forbidden_words(text: str, site: str = "US") -> Dict[str, object]:
    """扫描文案，命中禁词表则拦截，指出每个违规点位置并给合规替代。

    site：站点代码（US/UK/DE…），决定读哪张 `data/compliance/禁词表_<站点>.csv`。
    返回 {passed, site, violations:[{词,类型,位置,合规替代}]}。"""
    violations = _scan(text, _forbidden_table(site), "违规词")
    return {"passed": not violations, "site": site, "violations": violations}


@tool
def match_ip_brand_patent(text: str) -> Dict[str, object]:
    """匹配他人品牌/商标/IP/专利话术黑名单，识别侵权风险表达。

    返回 {passed, violations:[{词,类型,位置,合规替代}]}。"""
    violations = _scan(text, _ip_table(), "名称")
    return {"passed": not violations, "violations": violations}


@tool
def flag_category_risk(category: str) -> Dict[str, object]:
    """输入类目，返回审核/侵权风险等级（选品阶段小红旗预警，1.5）。

    对类目风险表做大小写不敏感的包含匹配，取命中项；未命中按低风险处理。
    返回 {category, matched, risk_level, risk_type, note}。"""
    low = category.lower()
    for row in _category_table():
        cat = (row.get("类目", "") or "").strip()
        if cat and (cat.lower() in low or low in cat.lower()):
            return {
                "category": category,
                "matched": True,
                "risk_level": row.get("风险等级", ""),
                "risk_type": row.get("风险类型", ""),
                "note": row.get("说明", ""),
            }
    return {"category": category, "matched": False, "risk_level": "低",
            "risk_type": "", "note": "未在风险表中，按常规类目处理"}


def _apply_whitelist(violations: List[Dict[str, object]], text: str):
    """把落在白名单短语内部的违规点放行，返回 (保留, 放行)。"""
    lowered = text.lower()
    present = [w for w in _whitelist() if w and w in lowered]
    kept, overridden = [], []
    for v in violations:
        term = str(v["词"]).lower()
        pos = int(v["位置"])
        # 命中的词若整体落在某个在场白名单短语的区间内，则放行。
        in_wl = any(
            term in wl and (start := lowered.find(wl)) <= pos < start + len(wl)
            for wl in present
        )
        (overridden if in_wl else kept).append(v)
    return kept, overridden


@tool
def compliance_gate(text: str = "", category: str = "",
                    site: str = "US") -> Dict[str, object]:
    """合规统一入口（1.6）：一次跑完禁词 + IP + 类目风险，并应用白名单（1.7）。

    text：要审的文案（可空，只查类目时）。category：要评估的类目（可空）。
    site：站点。返回 {passed, site, violations[], overridden[], category_risk}。
    passed 只由文案违规决定；category_risk 为预警信息，不直接判负。"""
    violations: List[Dict[str, object]] = []
    overridden: List[Dict[str, object]] = []
    if text:
        raw = check_forbidden_words.func(text, site)["violations"] \
            + match_ip_brand_patent.func(text)["violations"]
        violations, overridden = _apply_whitelist(raw, text)
    category_risk = flag_category_risk.func(category) if category else None
    return {
        "passed": not violations,
        "site": site,
        "violations": violations,
        "overridden": overridden,
        "category_risk": category_risk,
    }


COMPLIANCE_TOOLS = [
    check_forbidden_words,
    match_ip_brand_patent,
    flag_category_risk,
    compliance_gate,
]
