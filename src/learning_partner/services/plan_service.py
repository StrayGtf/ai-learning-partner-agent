from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from learning_partner.models import ChapterSpec, LearningPlan, UserProfile
from learning_partner.services.llm_client import LLMClient, LLMError
from learning_partner.utils.fs import read_text, write_text
from learning_partner.utils.text import code_flag_text, slugify, truthy

LP_META_START = "<!-- LP_METADATA_START -->"
LP_META_END = "<!-- LP_METADATA_END -->"
LP_CHAPTERS_START = "<!-- LP_CHAPTERS_START -->"
LP_CHAPTERS_END = "<!-- LP_CHAPTERS_END -->"


def target_chapter_count(depth: str) -> int:
    token = depth.strip().lower()
    if any(k in token for k in ["入门", "浅", "quick", "basic"]):
        return 4
    if any(k in token for k in ["进阶", "深入", "深", "advanced", "deep"]):
        return 8
    return 6


def _default_prerequisites(profile: UserProfile) -> list[str]:
    items = [
        "具备基本信息检索能力。",
        "每周有固定学习时间（建议 3-6 小时）。",
        "愿意通过复盘和练习巩固知识。",
    ]
    if profile.code_practice:
        items.append("本地可运行代码（命令行或 IDE）。")
    return items


def _base_blueprints(topic: str, include_code: bool) -> list[tuple[str, str, bool]]:
    return [
        ("主题总览与学习地图", f"理解 {topic} 的核心范围、价值和学习路径。", False),
        ("核心概念与术语", f"建立 {topic} 的概念体系和术语映射。", False),
        ("关键机制与思维模型", f"掌握 {topic} 的关键原理并能解释原因。", include_code),
        ("典型场景与常见误区", f"识别 {topic} 的常见应用场景与误区。", include_code),
        ("综合练习与问题拆解", f"把 {topic} 用到完整问题并形成解题套路。", include_code),
        ("阶段复盘与能力固化", f"复盘 {topic} 重点并沉淀可迁移方法。", False),
        ("进阶专题与最佳实践", f"掌握 {topic} 的工程化最佳实践。", include_code),
        ("长期路线与能力拓展", f"形成 {topic} 的长期迭代学习策略。", include_code),
    ]


def _estimate_time(index: int, total: int) -> str:
    if index == total:
        return "1.5h"
    if index % 3 == 0:
        return "3h"
    return "2h"


def _build_review_milestones(chapters: list[ChapterSpec]) -> list[str]:
    nodes: list[str] = []
    for idx, chapter in enumerate(chapters, start=1):
        if idx % 2 == 0 or idx == len(chapters):
            nodes.append(f"完成 {chapter.chapter_id} 后做一次阶段复习。")
    return nodes


def build_default_plan(profile: UserProfile) -> LearningPlan:
    chapter_count = target_chapter_count(profile.depth)
    blueprints = _base_blueprints(profile.topic, profile.code_practice)[:chapter_count]
    chapters: list[ChapterSpec] = []
    for index, (title, objective, code_flag) in enumerate(blueprints, start=1):
        dir_name = f"{index:02d}-{slugify(f'{profile.topic}-{title}', f'chapter-{index:02d}')}"
        chapters.append(
            ChapterSpec(
                index=index,
                title=f"{profile.topic}：{title}",
                dir_name=dir_name,
                estimated_time=_estimate_time(index, chapter_count),
                code_practice=bool(code_flag),
                objective=objective,
            )
        )
    return LearningPlan(
        profile=profile,
        overall_goal=profile.goal,
        prerequisites=_default_prerequisites(profile),
        recommended_order=[chapter.dir_name for chapter in chapters],
        review_milestones=_build_review_milestones(chapters),
        chapters=chapters,
    )


def build_plan(profile: UserProfile, llm_client: LLMClient | None = None) -> LearningPlan:
    if llm_client and llm_client.enabled:
        try:
            ai_plan = _build_plan_with_llm(profile, llm_client)
            if ai_plan:
                return ai_plan
        except LLMError:
            pass
    return build_default_plan(profile)


def _build_plan_with_llm(profile: UserProfile, llm_client: LLMClient) -> LearningPlan | None:
    chapter_count = target_chapter_count(profile.depth)
    system_prompt = (
        "You are an expert learning designer. "
        "Return strict JSON only. Do not wrap in markdown."
    )
    user_prompt = f"""
Generate a learning plan for:
- topic: {profile.topic}
- learner level: {profile.level}
- learning goal: {profile.goal}
- depth: {profile.depth}
- code practice required: {profile.code_practice}

Return JSON object with keys:
{{
  "overall_goal": "string",
  "prerequisites": ["string", "..."],
  "review_milestones": ["string", "..."],
  "chapters": [
    {{
      "title": "string",
      "objective": "string",
      "estimated_time": "string like 2h",
      "code_practice": true
    }}
  ]
}}

Requirements:
- chapters count must be {chapter_count}
- titles should be concrete and sequenced for progressive learning
- keep each objective to one sentence
"""
    payload = llm_client.chat_json(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=2600,
    )

    chapters_raw = payload.get("chapters")
    if not isinstance(chapters_raw, list) or not chapters_raw:
        return None

    chapters: list[ChapterSpec] = []
    for idx, raw in enumerate(chapters_raw[:chapter_count], start=1):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "")).strip() or f"{profile.topic} Chapter {idx}"
        objective = str(raw.get("objective", "")).strip() or f"Master chapter {idx} of {profile.topic}."
        est = str(raw.get("estimated_time", "")).strip() or _estimate_time(idx, chapter_count)
        code_flag = _to_bool(raw.get("code_practice"), default=profile.code_practice)
        dir_name = f"{idx:02d}-{slugify(f'{profile.topic}-{title}', f'chapter-{idx:02d}')}"
        chapters.append(
            ChapterSpec(
                index=idx,
                title=title,
                dir_name=dir_name,
                estimated_time=est,
                code_practice=code_flag,
                objective=objective,
            )
        )

    if not chapters:
        return None

    prerequisites = _to_string_list(payload.get("prerequisites")) or _default_prerequisites(profile)
    review_milestones = _to_string_list(payload.get("review_milestones")) or _build_review_milestones(chapters)
    overall_goal = str(payload.get("overall_goal", "")).strip() or profile.goal

    return LearningPlan(
        profile=profile,
        overall_goal=overall_goal,
        prerequisites=prerequisites,
        recommended_order=[chapter.dir_name for chapter in chapters],
        review_milestones=review_milestones,
        chapters=chapters,
    )


def _to_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        text = str(entry).strip()
        if text:
            items.append(text)
    return items


def _to_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    token = str(value).strip().lower()
    if token in {"1", "true", "yes", "y"}:
        return True
    if token in {"0", "false", "no", "n"}:
        return False
    return default


def learning_plan_to_markdown(plan: LearningPlan) -> str:
    metadata = {
        "topic": plan.profile.topic,
        "level": plan.profile.level,
        "goal": plan.profile.goal,
        "depth": plan.profile.depth,
        "code_practice": plan.profile.code_practice,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    chapter_lines = [
        f"{chapter.chapter_id} | {chapter.title} | {chapter.dir_name} | "
        f"{chapter.estimated_time} | {code_flag_text(chapter.code_practice)} | {chapter.objective}"
        for chapter in plan.chapters
    ]
    prerequisite_lines = "\n".join(f"- {item}" for item in plan.prerequisites)
    order_lines = "\n".join(f"- {item}" for item in plan.recommended_order)
    review_lines = "\n".join(f"- {item}" for item in plan.review_milestones)

    return f"""# 学习路线（可编辑）

> 你可以删除不想学的章节，或调整章节顺序。系统后续会以你修改后的版本为准。
> 请保留章节索引格式（`01 | 标题 | 目录名 | 时长 | code | 学习目标`）。

## 学习目标

{plan.overall_goal}

## 学习者画像

- 当前水平：{plan.profile.level}
- 学习深度：{plan.profile.depth}
- 是否代码实践：{code_flag_text(plan.profile.code_practice)}

## 前置知识

{prerequisite_lines}

## 章节清单（可增删改顺序）

{LP_CHAPTERS_START}
01 | 示例章节标题 | 01-example-chapter | 2h | yes/no | 示例目标（可删除本行）
{chr(10).join(chapter_lines)}
{LP_CHAPTERS_END}

## 推荐学习顺序

{order_lines}

## 阶段复习节点

{review_lines}

{LP_META_START}
{json.dumps(metadata, ensure_ascii=False, indent=2)}
{LP_META_END}
"""


def save_learning_plan(path: Path, plan: LearningPlan) -> None:
    write_text(path, learning_plan_to_markdown(plan))


def _extract_block(content: str, start_tag: str, end_tag: str) -> str:
    start = content.find(start_tag)
    end = content.find(end_tag)
    if start == -1 or end == -1 or end <= start:
        return ""
    return content[start + len(start_tag) : end].strip("\n\r ")


def _parse_chapter_line(raw: str) -> ChapterSpec | None:
    stripped = raw.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "示例章节标题" in stripped:
        return None
    parts = [part.strip() for part in stripped.split("|")]
    if len(parts) < 6:
        return None

    idx_text, title, dir_name, estimated_time, code_flag, objective = parts[:6]
    if not re.fullmatch(r"\d{2}", idx_text):
        return None
    index = int(idx_text)
    clean_dir = dir_name or f"{idx_text}-chapter-{idx_text}"
    return ChapterSpec(
        index=index,
        title=title or f"章节 {idx_text}",
        dir_name=clean_dir,
        estimated_time=estimated_time or "2h",
        code_practice=truthy(code_flag),
        objective=objective or f"完成章节 {idx_text} 学习目标。",
    )


def load_learning_plan(path: Path, fallback_profile: UserProfile | None = None) -> LearningPlan:
    content = read_text(path)
    chapters_block = _extract_block(content, LP_CHAPTERS_START, LP_CHAPTERS_END)
    lines = [line for line in chapters_block.splitlines() if line.strip()]
    chapters: list[ChapterSpec] = []
    for line in lines:
        parsed = _parse_chapter_line(line)
        if parsed:
            chapters.append(parsed)

    metadata: dict[str, Any] = {}
    meta_block = _extract_block(content, LP_META_START, LP_META_END)
    if meta_block:
        try:
            metadata = json.loads(meta_block)
        except json.JSONDecodeError:
            metadata = {}

    if fallback_profile is None:
        fallback_profile = UserProfile(
            topic=str(metadata.get("topic", "未命名主题")),
            level=str(metadata.get("level", "未知")),
            goal=str(metadata.get("goal", "掌握该主题")),
            depth=str(metadata.get("depth", "标准")),
            code_practice=bool(metadata.get("code_practice", False)),
            workspace=str(path.parent),
        )
    else:
        if metadata.get("topic"):
            fallback_profile = replace(fallback_profile, topic=str(metadata["topic"]))
        if metadata.get("level"):
            fallback_profile = replace(fallback_profile, level=str(metadata["level"]))
        if metadata.get("goal"):
            fallback_profile = replace(fallback_profile, goal=str(metadata["goal"]))
        if metadata.get("depth"):
            fallback_profile = replace(fallback_profile, depth=str(metadata["depth"]))
        if "code_practice" in metadata:
            fallback_profile = replace(fallback_profile, code_practice=bool(metadata["code_practice"]))

    if not chapters:
        chapters = build_default_plan(fallback_profile).chapters

    return LearningPlan(
        profile=fallback_profile,
        overall_goal=fallback_profile.goal,
        prerequisites=_default_prerequisites(fallback_profile),
        recommended_order=[chapter.dir_name for chapter in chapters],
        review_milestones=_build_review_milestones(chapters),
        chapters=chapters,
    )
