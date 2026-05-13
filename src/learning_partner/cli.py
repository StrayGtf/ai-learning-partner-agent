from __future__ import annotations

import argparse
from pathlib import Path

from learning_partner.models import UserProfile
from learning_partner.services.chapter_service import generate_next_chapter, mark_chapter_progress_file
from learning_partner.services.initializer import initialize_workspace
from learning_partner.services.llm_client import get_llm_client_from_env
from learning_partner.services.plan_service import load_learning_plan
from learning_partner.services.progress_service import (
    load_progress,
    mark_chapter_completed,
    save_progress,
    sync_progress_with_plan,
)
from learning_partner.services.quiz_service import (
    append_answer_feedback,
    evaluate_answers,
    parse_answers,
    parse_quiz_meta,
)
from learning_partner.utils.fs import read_text


def _str_to_bool(text: str) -> bool:
    return text.strip().lower() in {"1", "true", "yes", "y", "是", "需要"}


def cmd_init(args: argparse.Namespace) -> int:
    profile = UserProfile(
        topic=args.topic,
        level=args.level,
        goal=args.goal,
        depth=args.depth,
        code_practice=_str_to_bool(args.code_practice),
        workspace=str(Path(args.workspace).resolve()),
    )
    workspace = initialize_workspace(profile=profile, force=args.force)
    llm_client = get_llm_client_from_env()
    print(f"学习项目已初始化：{workspace}")
    print(f"LLM 模式：{'已启用' if llm_client.enabled else '未启用（本地模板模式）'}")
    print(f"请先手动检查并编辑：{workspace / 'learning-plan.md'}")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    chapter = generate_next_chapter(workspace)
    if chapter is None:
        print("所有章节已完成，无需生成新内容。")
        return 0
    chapter_dir = workspace / "chapters" / chapter.dir_name
    print(f"已生成章节：{chapter.chapter_id} {chapter.title}")
    print(f"目录：{chapter_dir}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    plan = load_learning_plan(workspace / "learning-plan.md")
    progress = load_progress(workspace / "progress.json")
    progress = sync_progress_with_plan(progress, plan)
    save_progress(workspace / "progress.json", progress)

    completed = len(progress.get("completed_chapters", []))
    total = progress.get("total_chapters", 0)
    llm_client = get_llm_client_from_env()
    print(f"主题：{progress.get('topic', '未知')}")
    print(f"进度：{completed}/{total}")
    print(f"当前章节：{progress.get('current_chapter')}")
    print(f"LLM 模式：{'已启用' if llm_client.enabled else '未启用'}")
    print(progress.get("next_recommendation", ""))
    return 0


def _resolve_target_chapter(progress: dict, chapter_arg: str | None) -> str:
    if chapter_arg:
        return chapter_arg
    current = progress.get("current_chapter")
    if current:
        return current
    for chapter_dir, state in progress.get("chapters", {}).items():
        if state.get("status") == "in_progress":
            return chapter_dir
    raise ValueError("没有找到待提交测验的章节，请先执行 next 生成章节。")


def cmd_answer(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    plan = load_learning_plan(workspace / "learning-plan.md")
    progress_path = workspace / "progress.json"
    progress = load_progress(progress_path)
    progress = sync_progress_with_plan(progress, plan)

    target_chapter_dir = _resolve_target_chapter(progress, args.chapter)
    chapter_dir = workspace / "chapters" / target_chapter_dir
    quiz_path = chapter_dir / "quiz.md"
    answers_path = chapter_dir / "answers.md"

    if args.answers_file:
        raw_answers = read_text(Path(args.answers_file).resolve())
    elif args.answers_text:
        raw_answers = args.answers_text
    else:
        raise ValueError("请通过 --answers-file 或 --answers-text 提供回答内容。")

    answers = parse_answers(raw_answers)
    quiz_meta = parse_quiz_meta(quiz_path)
    chapter_title = progress["chapters"].get(target_chapter_dir, {}).get("title", target_chapter_dir)
    llm_client = get_llm_client_from_env()
    score, mastery, feedback = evaluate_answers(
        quiz_meta,
        answers,
        chapter_title=chapter_title,
        llm_client=llm_client if llm_client.enabled else None,
    )

    append_answer_feedback(answers_path, raw_answers, feedback)
    mark_chapter_completed(plan, progress, target_chapter_dir, score, mastery, feedback)
    save_progress(progress_path, progress)
    mark_chapter_progress_file(chapter_dir, chapter_title, "completed")

    print(f"{target_chapter_dir} 测验已提交，得分：{score}，掌握度：{mastery}")
    print(feedback)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="learning-partner",
        description="本地学习伙伴 Agent：学习路线、章节内容、测验反馈、进度续学。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化学习项目并生成学习路线")
    init_parser.add_argument("--topic", required=True, help="学习主题")
    init_parser.add_argument("--level", required=True, help="当前基础水平")
    init_parser.add_argument("--goal", required=True, help="学习目标")
    init_parser.add_argument("--depth", required=True, help="学习深度（入门/标准/深入）")
    init_parser.add_argument("--code-practice", default="yes", help="是否需要代码实践（yes/no）")
    init_parser.add_argument("--workspace", default="./learning-workspace", help="学习工作区路径")
    init_parser.add_argument("--force", action="store_true", help="强制重建 learning-plan.md 与 progress.json")
    init_parser.set_defaults(func=cmd_init)

    next_parser = subparsers.add_parser("next", help="按当前进度生成下一章内容")
    next_parser.add_argument("--workspace", default="./learning-workspace", help="学习工作区路径")
    next_parser.set_defaults(func=cmd_next)

    answer_parser = subparsers.add_parser("answer", help="提交章节测验回答并更新进度")
    answer_parser.add_argument("--workspace", default="./learning-workspace", help="学习工作区路径")
    answer_parser.add_argument("--chapter", help="目标章节目录名（默认使用当前章节）")
    answer_group = answer_parser.add_mutually_exclusive_group(required=True)
    answer_group.add_argument("--answers-file", help="回答文件路径，使用 Q1:... 格式")
    answer_group.add_argument("--answers-text", help="直接传入回答文本，使用 Q1:... 格式")
    answer_parser.set_defaults(func=cmd_answer)

    status_parser = subparsers.add_parser("status", help="查看学习进度摘要")
    status_parser.add_argument("--workspace", default="./learning-workspace", help="学习工作区路径")
    status_parser.set_defaults(func=cmd_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
