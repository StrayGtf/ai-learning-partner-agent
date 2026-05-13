from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from learning_partner.models import LearningPlan
from learning_partner.utils.fs import dump_json, load_json


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_initial_progress(plan: LearningPlan) -> dict[str, Any]:
    chapter_states: dict[str, Any] = {}
    for chapter in plan.chapters:
        chapter_states[chapter.dir_name] = {
            "chapter_id": chapter.chapter_id,
            "title": chapter.title,
            "status": "not_started",
            "has_code_practice": chapter.code_practice,
            "estimated_time": chapter.estimated_time,
            "objective": chapter.objective,
            "completed_at": None,
            "quiz": {"last_score": None, "mastery": None, "attempts": []},
        }
    return {
        "topic": plan.profile.topic,
        "total_chapters": len(plan.chapters),
        "completed_chapters": [],
        "current_chapter": None,
        "chapters": chapter_states,
        "next_recommendation": "从第 1 章开始学习。",
        "created_at": _now(),
        "updated_at": _now(),
    }


def load_progress(path: Path) -> dict[str, Any]:
    return load_json(path)


def save_progress(path: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = _now()
    dump_json(path, payload)


def sync_progress_with_plan(progress: dict[str, Any], plan: LearningPlan) -> dict[str, Any]:
    chapter_map = progress.setdefault("chapters", {})
    active_dirs = {chapter.dir_name for chapter in plan.chapters}

    for chapter in plan.chapters:
        if chapter.dir_name not in chapter_map:
            chapter_map[chapter.dir_name] = {
                "chapter_id": chapter.chapter_id,
                "title": chapter.title,
                "status": "not_started",
                "has_code_practice": chapter.code_practice,
                "estimated_time": chapter.estimated_time,
                "objective": chapter.objective,
                "completed_at": None,
                "quiz": {"last_score": None, "mastery": None, "attempts": []},
            }
        else:
            chapter_state = chapter_map[chapter.dir_name]
            chapter_state["chapter_id"] = chapter.chapter_id
            chapter_state["title"] = chapter.title
            chapter_state["has_code_practice"] = chapter.code_practice
            chapter_state["estimated_time"] = chapter.estimated_time
            chapter_state["objective"] = chapter.objective
            chapter_state.setdefault("quiz", {"last_score": None, "mastery": None, "attempts": []})

    removed_dirs = [name for name in chapter_map.keys() if name not in active_dirs]
    for removed in removed_dirs:
        chapter_map[removed]["status"] = "removed_from_plan"

    completed_active = []
    for chapter in plan.chapters:
        state = chapter_map.get(chapter.dir_name, {})
        if state.get("status") == "completed":
            completed_active.append(chapter.dir_name)

    progress["topic"] = plan.profile.topic
    progress["total_chapters"] = len(plan.chapters)
    progress["completed_chapters"] = completed_active

    current = progress.get("current_chapter")
    if current and chapter_map.get(current, {}).get("status") == "removed_from_plan":
        progress["current_chapter"] = None

    if not progress.get("current_chapter"):
        next_chapter = find_next_chapter(plan, progress)
        progress["current_chapter"] = next_chapter.dir_name if next_chapter else None

    progress["next_recommendation"] = build_next_recommendation(plan, progress)
    return progress


def find_next_chapter(plan: LearningPlan, progress: dict[str, Any]):
    chapter_map = progress.get("chapters", {})
    for chapter in plan.chapters:
        state = chapter_map.get(chapter.dir_name, {})
        if state.get("status") != "completed":
            return chapter
    return None


def build_next_recommendation(plan: LearningPlan, progress: dict[str, Any]) -> str:
    next_chapter = find_next_chapter(plan, progress)
    if not next_chapter:
        return "所有章节已完成，建议进入阶段复习并整理 notes.md。"
    return f"下一步建议：学习 {next_chapter.chapter_id} {next_chapter.title}"


def mark_chapter_in_progress(progress: dict[str, Any], chapter_dir: str) -> None:
    chapter_state = progress["chapters"][chapter_dir]
    if chapter_state["status"] == "not_started":
        chapter_state["status"] = "in_progress"
    progress["current_chapter"] = chapter_dir


def mark_chapter_completed(
    plan: LearningPlan,
    progress: dict[str, Any],
    chapter_dir: str,
    score: float,
    mastery: str,
    feedback: str,
) -> None:
    chapter_state = progress["chapters"][chapter_dir]
    chapter_state["status"] = "completed"
    chapter_state["completed_at"] = _now()
    chapter_state.setdefault("quiz", {"attempts": []})
    chapter_state["quiz"]["last_score"] = score
    chapter_state["quiz"]["mastery"] = mastery
    chapter_state["quiz"].setdefault("attempts", []).append(
        {"time": _now(), "score": score, "mastery": mastery, "feedback": feedback}
    )

    completed = []
    for chapter in plan.chapters:
        state = progress["chapters"].get(chapter.dir_name, {})
        if state.get("status") == "completed":
            completed.append(chapter.dir_name)
    progress["completed_chapters"] = completed

    next_chapter = find_next_chapter(plan, progress)
    progress["current_chapter"] = next_chapter.dir_name if next_chapter else None
    progress["next_recommendation"] = build_next_recommendation(plan, progress)
