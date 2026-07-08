"""#3 图文视频提示词智能体的工具集。

绘图提示词/脚本/构图拆解主要靠人设 + skills（模型产出文本）；工具负责一件确定性活：
- `check_image_rules(description, image_type)` —— 拿图片的**文字描述**对照
  `data/imagery/图片规范.csv` 做规范校验（主图白底、无水印文字等，3.4）。
- 复用 #1 `compliance_gate` —— 校验图上文字是否含极限词/侵权（3.4 可选调 #1）。

v1 边界：只产出提示词文本 + 脚本，不接图像/视频生成 API。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List

from ..data_loader import load_data
from .base import tool
from .compliance import compliance_gate  # 复用 #1


@lru_cache(maxsize=None)
def _rules() -> tuple:
    return tuple(load_data("imagery", "图片规范.csv", required_columns=["规则", "适用"]))


@tool
def check_image_rules(description: str, image_type: str = "main") -> Dict[str, object]:
    """按亚马逊图片规范校验一张图的文字描述（主图白底、无水印文字等）。

    image_type：main（主图）/ scene（场景图）。返回 {passed, violations, checklist}：
    violations 是描述里命中违规关键词的规则；checklist 是该图类型应遵守的全部规则
    （供人工逐条核对，含无法从文字自动判定的项）。"""
    applies = {"main": "主图", "scene": "场景图"}.get(image_type, image_type)
    lowered = description.lower()
    violations: List[Dict[str, str]] = []
    checklist: List[str] = []
    for row in _rules():
        scope = (row.get("适用", "") or "").strip()
        if scope not in (applies, "通用"):
            continue
        rule = row.get("规则", "")
        checklist.append(f"{rule}：{row.get('说明', '')}")
        for kw in (row.get("违规关键词", "") or "").split(";"):
            kw = kw.strip()
            if kw and kw.lower() in lowered:
                violations.append({"规则": rule, "命中": kw, "说明": row.get("说明", "")})
    return {"passed": not violations, "image_type": image_type,
            "violations": violations, "checklist": checklist}


IMAGERY_TOOLS = [check_image_rules, compliance_gate]
