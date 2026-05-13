from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from learning_partner.models import ChapterSpec
from learning_partner.services.llm_client import LLMClient, LLMError
from learning_partner.utils.fs import read_text, write_text

QUIZ_META_START = "<!-- QUIZ_META_START -->"
QUIZ_META_END = "<!-- QUIZ_META_END -->"


@dataclass
class QuizQuestion:
    id: str
    qtype: str
    prompt: str
    keywords: list[str]


def _keyword_candidates(chapter: ChapterSpec) -> list[str]:
    pieces = re.split(r"[，,。；;\s\-_/]+", f"{chapter.title} {chapter.objective}")
    candidates = []
    for token in pieces:
        token = token.strip()
        if len(token) < 2:
            continue
        candidates.append(token.lower())
    if not candidates:
        candidates = ["核心概念", "应用场景", "实践"]
    return list(dict.fromkeys(candidates))[:8]


def build_quiz(
    chapter: ChapterSpec,
    llm_client: LLMClient | None = None,
    chapter_context: str = "",
) -> list[QuizQuestion]:
    if llm_client and llm_client.enabled:
        try:
            ai_quiz = _build_quiz_with_llm(chapter, llm_client, chapter_context=chapter_context)
            if ai_quiz:
                return ai_quiz
        except LLMError:
            pass
    return _build_quiz_local(chapter)


def _build_quiz_local(chapter: ChapterSpec) -> list[QuizQuestion]:
    keywords = _keyword_candidates(chapter)
    base = [
        QuizQuestion(
            id="Q1",
            qtype="基础概念题",
            prompt=f"请解释「{chapter.title}」中的一个核心概念，并说明它为何重要。",
            keywords=keywords[:3],
        ),
        QuizQuestion(
            id="Q2",
            qtype="简答题",
            prompt=f"结合本章目标，说明你会如何判断自己是否真正掌握了「{chapter.title}」。",
            keywords=keywords[1:4] or keywords[:2],
        ),
        QuizQuestion(
            id="Q3",
            qtype="应用题",
            prompt=f"给出一个你可能在实际学习或工作中应用「{chapter.title}」的场景，并描述解题步骤。",
            keywords=keywords[2:6] or keywords[:3],
        ),
    ]
    if chapter.code_practice:
        base.append(
            QuizQuestion(
                id="Q4",
                qtype="代码题",
                prompt="阅读本章示例代码后，说明你会如何优化其中一个实现细节。",
                keywords=["代码", "优化", "实现", "重构"],
            )
        )
    return base


def _build_quiz_with_llm(
    chapter: ChapterSpec,
    llm_client: LLMClient,
    *,
    chapter_context: str,
) -> list[QuizQuestion]:
    system_prompt = "You design chapter quizzes. Return strict JSON only."
    user_prompt = f"""
Generate quiz questions for this chapter:
- chapter title: {chapter.title}
- objective: {chapter.objective}
- has code practice: {chapter.code_practice}

Optional chapter context:
{chapter_context[:4000]}

Return JSON object:
{{
  "questions": [
    {{
      "id": "Q1",
      "qtype": "基础概念题/简答题/应用题/代码题",
      "prompt": "question text",
      "keywords": ["keyword1", "keyword2", "..."]
    }}
  ]
}}

Requirements:
- Always include Q1,Q2,Q3
- If has code practice=true, include Q4 code question
- keywords should be 3-6 concise terms for evaluation
"""
    payload = llm_client.chat_json(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=1200,
    )

    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        return []

    questions: list[QuizQuestion] = []
    for idx, raw in enumerate(raw_questions, start=1):
        if not isinstance(raw, dict):
            continue
        qid = str(raw.get("id", f"Q{idx}")).upper()
        qtype = str(raw.get("qtype", "简答题")).strip() or "简答题"
        prompt = str(raw.get("prompt", "")).strip()
        if not prompt:
            continue
        keywords = _normalize_keywords(raw.get("keywords")) or _keyword_candidates(chapter)[:4]
        questions.append(QuizQuestion(id=qid, qtype=qtype, prompt=prompt, keywords=keywords))

    if not questions:
        return []
    return questions


def _normalize_keywords(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        text = str(entry).strip()
        if text:
            items.append(text.lower())
    return items[:8]


def quiz_to_markdown(chapter: ChapterSpec, questions: list[QuizQuestion]) -> str:
    lines = [f"# 测验：{chapter.title}", "", "请按 `Q1: ...` 格式回答。", ""]
    for q in questions:
        lines.append(f"## {q.id}（{q.qtype}）")
        lines.append(q.prompt)
        lines.append("")
    payload = {"chapter_dir": chapter.dir_name, "questions": [asdict(q) for q in questions]}
    lines.append(QUIZ_META_START)
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
    lines.append(QUIZ_META_END)
    return "\n".join(lines) + "\n"


def parse_quiz_meta(quiz_path: Path) -> dict:
    content = read_text(quiz_path)
    start = content.find(QUIZ_META_START)
    end = content.find(QUIZ_META_END)
    if start == -1 or end == -1 or end <= start:
        return {"questions": []}
    raw = content[start + len(QUIZ_META_START) : end].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"questions": []}


def parse_answers(raw_text: str) -> dict[str, str]:
    pattern = re.compile(r"^(Q\d+)\s*:\s*(.*)$", flags=re.IGNORECASE)
    results: dict[str, str] = {}
    for line in raw_text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        qid, answer = match.groups()
        results[qid.upper()] = answer.strip()
    return results


def evaluate_answers(
    quiz_meta: dict,
    answers: dict[str, str],
    *,
    chapter_title: str = "",
    llm_client: LLMClient | None = None,
) -> tuple[float, str, str]:
    if llm_client and llm_client.enabled:
        try:
            ai_result = _evaluate_answers_with_llm(quiz_meta, answers, chapter_title=chapter_title, llm_client=llm_client)
            if ai_result is not None:
                return ai_result
        except LLMError:
            pass
    return _evaluate_answers_local(quiz_meta, answers)


def _evaluate_answers_with_llm(
    quiz_meta: dict,
    answers: dict[str, str],
    *,
    chapter_title: str,
    llm_client: LLMClient,
) -> tuple[float, str, str] | None:
    questions = quiz_meta.get("questions", [])
    if not isinstance(questions, list) or not questions:
        return None

    system_prompt = (
        "You are a strict but constructive learning evaluator. "
        "Return strict JSON only."
    )
    user_prompt = json.dumps(
        {
            "chapter_title": chapter_title,
            "questions": questions,
            "answers": answers,
            "instructions": {
                "score_range": "0-100",
                "mastery_levels": ["熟练", "良好", "基础", "待加强"],
                "language": "zh-CN",
                "tone": "supportive and actionable",
            },
            "expected_output_schema": {
                "score": 0,
                "mastery": "基础",
                "summary": "string",
                "details": [{"id": "Q1", "feedback": "string"}],
                "next_actions": ["string"],
            },
        },
        ensure_ascii=False,
    )
    payload = llm_client.chat_json(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=1400,
    )

    score = _clamp_score(payload.get("score"))
    mastery = str(payload.get("mastery", "")).strip() or score_to_mastery(score)
    summary = str(payload.get("summary", "")).strip() or f"总分 {score}，掌握度：{mastery}。"
    details_raw = payload.get("details")
    detail_lines: list[str] = []
    if isinstance(details_raw, list):
        for item in details_raw:
            if not isinstance(item, dict):
                continue
            qid = str(item.get("id", "")).strip().upper()
            fb = str(item.get("feedback", "")).strip()
            if qid and fb:
                detail_lines.append(f"{qid}: {fb}")

    next_actions_raw = payload.get("next_actions")
    next_actions: list[str] = []
    if isinstance(next_actions_raw, list):
        for item in next_actions_raw:
            text = str(item).strip()
            if text:
                next_actions.append(text)

    blocks = [summary]
    if detail_lines:
        blocks.extend(detail_lines)
    if next_actions:
        blocks.append("下一步建议：")
        blocks.extend(f"- {text}" for text in next_actions[:3])
    feedback = "\n".join(blocks)
    return score, mastery, feedback


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, round(score, 2)))


def _evaluate_answers_local(quiz_meta: dict, answers: dict[str, str]) -> tuple[float, str, str]:
    questions = quiz_meta.get("questions", [])
    if not questions:
        return 0.0, "待加强", "未读取到可评分题目，请检查 quiz.md。"

    detail_lines = []
    total_points = 0.0
    for q in questions:
        qid = str(q.get("id", "")).upper()
        keywords = [str(item).lower() for item in q.get("keywords", []) if item]
        answer = answers.get(qid, "")
        answer_lower = answer.lower()
        if not answer:
            detail_lines.append(f"{qid}: 未作答。")
            continue
        hit = sum(1 for kw in keywords if kw and kw in answer_lower)
        hit_ratio = hit / max(len(keywords), 1)
        length_bonus = 0.2 if len(answer) >= 25 else 0.0
        point = min(1.0, hit_ratio + length_bonus)
        total_points += point
        if point >= 0.7:
            detail_lines.append(f"{qid}: 回答较完整。")
        elif point >= 0.4:
            detail_lines.append(f"{qid}: 回答基本正确，但可补充关键点：{', '.join(keywords[:3])}")
        else:
            detail_lines.append(f"{qid}: 关键点不足，建议围绕 {', '.join(keywords[:3])} 重答。")

    score = round((total_points / len(questions)) * 100, 2)
    mastery = score_to_mastery(score)
    summary = f"总分 {score}，掌握度：{mastery}。"
    feedback = "\n".join([summary] + detail_lines)
    return score, mastery, feedback


def score_to_mastery(score: float) -> str:
    if score >= 85:
        return "熟练"
    if score >= 70:
        return "良好"
    if score >= 50:
        return "基础"
    return "待加强"


def append_answer_feedback(answers_path: Path, answer_text: str, feedback: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    block = (
        f"\n## {timestamp}\n\n"
        "### 用户回答\n\n"
        f"{answer_text.strip() or '（空）'}\n\n"
        "### Agent 反馈\n\n"
        f"{feedback.strip()}\n"
    )
    if answers_path.exists():
        current = read_text(answers_path)
        write_text(answers_path, current.rstrip() + "\n" + block)
    else:
        header = "# 回答记录与反馈\n"
        write_text(answers_path, header + block)
