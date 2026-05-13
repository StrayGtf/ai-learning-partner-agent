from __future__ import annotations

from datetime import datetime
from pathlib import Path

from learning_partner.models import ChapterSpec, LearningPlan
from learning_partner.services.llm_client import LLMClient, LLMError, get_llm_client_from_env
from learning_partner.services.plan_service import load_learning_plan
from learning_partner.services.progress_service import (
    find_next_chapter,
    load_progress,
    mark_chapter_in_progress,
    save_progress,
    sync_progress_with_plan,
)
from learning_partner.services.quiz_service import build_quiz, quiz_to_markdown
from learning_partner.utils.fs import ensure_dir, write_text, write_text_if_absent


def _is_git_topic(plan: LearningPlan) -> bool:
    topic = (plan.profile.topic or "").strip().lower()
    return "git" in topic or "版本控制" in topic


def _git_intro_content_markdown(chapter: ChapterSpec, plan: LearningPlan) -> str:
    return f"""# {chapter.chapter_id} {chapter.title}

## 本章学习目标

- 理解 Git 的核心价值、基本工作流和学习顺序。
- 能区分 Git、GitHub/GitLab、工作区与仓库的关系。
- 能在本地独立完成一次最小闭环：初始化仓库 -> 提交 -> 查看历史。
- 预计耗时：{chapter.estimated_time}

## 知识讲解

### 1. Git 解决的问题

Git 用来管理项目版本历史，核心收益是：

- 能回看每次改动（谁在何时改了什么）
- 能比较任意两个版本差异
- 改坏后可安全回滚

### 2. Git 与 GitHub 的区别

- Git：本地版本控制工具
- GitHub/GitLab：远程托管与协作平台

一句话：先学会 Git，本地就能完整做版本管理。

### 3. 四个关键区域

1. Working Directory（工作区）
2. Staging Area（暂存区）
3. Local Repository（本地仓库）
4. Remote Repository（远程仓库）

核心流转：

```text
编辑文件 -> git add -> git commit -> git push(可选)
```

## 核心概念

1. Commit 是“项目快照”  
每次提交都是历史节点，不是简单备份文件。

2. 暂存区是“提交清单”  
它决定本次提交具体包含哪些改动。

3. 分支是“历史指针”  
分支让并行开发和试错更安全。

## 重点难点

- 难点 1：保存文件与提交历史是两件事
- 难点 2：养成先 `git status` 再 `git add` 的习惯
- 难点 3：提交信息要表达“这次改动的目的”

## 示例

```bash
mkdir git-demo
cd git-demo
git init
echo "# Git Demo" > README.md
git add README.md
git commit -m "feat: add initial README"
git log --oneline
```

## 小结

- 先记住最小闭环：`edit -> add -> commit -> log`
- 暂存区决定提交质量
- 后续章节会进入分支、合并、回滚和协作

## 练习题

1. 本地初始化一个新仓库并完成两次提交。
2. 使用 `git status` 观察“修改后/暂存后/提交后”的差异。
3. 解释一次好的提交信息应包含什么。

## 复习问题

1. Git 与 GitHub 的职责边界是什么？
2. 暂存区存在的意义是什么？
3. 为什么 commit 是“快照”而不是“文件复制”？
"""


def _content_markdown(chapter: ChapterSpec, plan: LearningPlan) -> str:
    if _is_git_topic(plan) and chapter.index == 1:
        return _git_intro_content_markdown(chapter, plan)

    code_note = "本章包含代码实践。" if chapter.code_practice else "本章以概念理解为主。"
    return f"""# {chapter.chapter_id} {chapter.title}

## 本章学习目标

- {chapter.objective}
- 预计耗时：{chapter.estimated_time}
- {code_note}

## 知识讲解

围绕「{chapter.title}」展开，先理解定义，再理解它解决的问题，最后理解在真实场景下如何使用。

## 核心概念

1. 概念 A：定义、边界、典型用途
2. 概念 B：与 A 的关系和区别
3. 概念 C：常见误区与纠偏思路

## 重点难点

- 难点 1：从“会用”到“会解释为什么这样用”
- 难点 2：在不同场景中做取舍与权衡
- 难点 3：避免只记结论不记推理过程

## 示例

- 示例场景：选择一个与你学习目标最相关的案例，写出问题、方案、结果。
- 反例场景：写出一个错误用法，并解释为什么不合适。

## 小结

- 你应该能说清楚本章核心概念
- 你应该能解释关键步骤背后的原因
- 你应该能把本章知识迁移到新场景

## 练习题

1. 用自己的话复述本章三个关键点。
2. 设计一个实际场景，说明如何使用本章内容。
3. 写下你仍不确定的两个问题，准备在复习阶段解决。

## 复习问题

1. 本章最容易混淆的概念是什么？
2. 如果让你教别人 10 分钟，你会怎么讲本章？
3. 下一章与本章的连接点是什么？
"""


def _summary_markdown(chapter: ChapterSpec) -> str:
    return f"""# {chapter.chapter_id} 章节总结

- 章节：{chapter.title}
- 完成时间：待更新
- 关键收获：
  - [ ] 我能清晰解释核心概念
  - [ ] 我能应用到具体场景
  - [ ] 我能指出常见误区并规避
"""


def _chapter_progress_markdown(chapter: ChapterSpec) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    return f"""# 章节进度

- 章节：{chapter.chapter_id} {chapter.title}
- 状态：in_progress
- 更新时间：{now}
"""


def _practice_readme(chapter: ChapterSpec) -> str:
    return f"""# 代码实践说明

本目录用于完成「{chapter.title}」的代码练习。

- `starter-code/`：起始代码
- `solution/`：参考答案
- `run.md`：运行说明
"""


def _practice_run(chapter: ChapterSpec) -> str:
    return f"""# 运行说明

## 目标

完成 {chapter.chapter_id} {chapter.title} 的练习代码，并验证输出结果。

## 建议步骤

1. 阅读 `starter-code/main.py`（或对应语言文件）
2. 根据练习要求补全逻辑
3. 运行代码并观察结果
4. 对照 `solution/` 做复盘

## Python 示例

```bash
python starter-code/main.py
```
"""


def _starter_code(chapter: ChapterSpec) -> str:
    return f"""\"\"\"{chapter.chapter_id} {chapter.title} starter code.\"\"\"


def solve():
    # TODO: implement your logic
    return "TODO"


if __name__ == "__main__":
    print(solve())
"""


def _solution_code(chapter: ChapterSpec) -> str:
    return f"""\"\"\"{chapter.chapter_id} {chapter.title} reference solution.\"\"\"


def solve():
    return "请使用本章知识替换该实现，并解释关键设计。"


if __name__ == "__main__":
    print(solve())
"""


def _generate_bundle_with_llm(
    llm_client: LLMClient,
    plan: LearningPlan,
    chapter: ChapterSpec,
) -> dict[str, str] | None:
    system_prompt = (
        "You are a senior learning content author. "
        "Return strict JSON only. Keep content practical and concise."
    )
    user_prompt = f"""
Create chapter learning materials for:
- topic: {plan.profile.topic}
- chapter id: {chapter.chapter_id}
- chapter title: {chapter.title}
- chapter objective: {chapter.objective}
- learner level: {plan.profile.level}
- learning goal: {plan.profile.goal}
- has code practice: {chapter.code_practice}

Return JSON object with keys:
{{
  "content_md": "markdown string",
  "summary_md": "markdown string",
  "practice_readme_md": "markdown string, optional when code practice is true",
  "practice_run_md": "markdown string, optional when code practice is true",
  "starter_code": "string code, optional when code practice is true",
  "solution_code": "string code, optional when code practice is true"
}}

Rules:
- content_md must include sections: 知识讲解, 核心概念, 重点难点, 示例, 小结, 练习题, 复习问题
- markdown should be directly writable to file
- avoid placeholder wording like "概念A/概念B"
- provide concrete examples and operational steps
- if topic is Git, include real command examples
"""
    try:
        payload = llm_client.chat_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=3200,
        )
    except LLMError:
        return None

    content_md = str(payload.get("content_md", "")).strip()
    summary_md = str(payload.get("summary_md", "")).strip()
    if not content_md:
        return None
    return {
        "content_md": content_md + "\n",
        "summary_md": (summary_md + "\n") if summary_md else _summary_markdown(chapter),
        "practice_readme_md": str(payload.get("practice_readme_md", "")).strip(),
        "practice_run_md": str(payload.get("practice_run_md", "")).strip(),
        "starter_code": str(payload.get("starter_code", "")).strip(),
        "solution_code": str(payload.get("solution_code", "")).strip(),
    }


def generate_chapter_files(workspace: Path, chapter: ChapterSpec, plan: LearningPlan) -> Path:
    chapter_dir = workspace / "chapters" / chapter.dir_name
    ensure_dir(chapter_dir)

    llm_client = get_llm_client_from_env()
    ai_bundle = _generate_bundle_with_llm(llm_client, plan, chapter) if llm_client.enabled else None

    content_md = ai_bundle["content_md"] if ai_bundle else _content_markdown(chapter, plan)
    summary_md = ai_bundle["summary_md"] if ai_bundle else _summary_markdown(chapter)

    write_text_if_absent(chapter_dir / "content.md", content_md)
    write_text_if_absent(chapter_dir / "summary.md", summary_md)
    write_text_if_absent(chapter_dir / "progress.md", _chapter_progress_markdown(chapter))

    quiz_questions = build_quiz(
        chapter,
        llm_client=llm_client if llm_client.enabled else None,
        chapter_context=content_md,
    )
    write_text_if_absent(chapter_dir / "quiz.md", quiz_to_markdown(chapter, quiz_questions))
    write_text_if_absent(chapter_dir / "answers.md", "# 回答记录与反馈\n")

    if chapter.code_practice:
        practice_dir = chapter_dir / "practice"
        ensure_dir(practice_dir)
        ensure_dir(practice_dir / "starter-code")
        ensure_dir(practice_dir / "solution")
        practice_readme = (
            ai_bundle["practice_readme_md"] + "\n"
            if ai_bundle and ai_bundle.get("practice_readme_md")
            else _practice_readme(chapter)
        )
        practice_run = (
            ai_bundle["practice_run_md"] + "\n"
            if ai_bundle and ai_bundle.get("practice_run_md")
            else _practice_run(chapter)
        )
        starter_code = (
            ai_bundle["starter_code"] + "\n"
            if ai_bundle and ai_bundle.get("starter_code")
            else _starter_code(chapter)
        )
        solution_code = (
            ai_bundle["solution_code"] + "\n"
            if ai_bundle and ai_bundle.get("solution_code")
            else _solution_code(chapter)
        )
        write_text_if_absent(practice_dir / "README.md", practice_readme)
        write_text_if_absent(practice_dir / "run.md", practice_run)
        write_text_if_absent(practice_dir / "starter-code" / "main.py", starter_code)
        write_text_if_absent(practice_dir / "solution" / "main.py", solution_code)

    return chapter_dir


def generate_next_chapter(workspace: Path):
    plan_path = workspace / "learning-plan.md"
    progress_path = workspace / "progress.json"
    plan = load_learning_plan(plan_path)
    progress = load_progress(progress_path)
    progress = sync_progress_with_plan(progress, plan)

    chapter = find_next_chapter(plan, progress)
    if not chapter:
        save_progress(progress_path, progress)
        return None

    chapter_dir = generate_chapter_files(workspace, chapter, plan)
    mark_chapter_in_progress(progress, chapter.dir_name)
    progress["next_recommendation"] = (
        f"请先完成 {chapter.chapter_id} 的学习，再执行 answer 提交测验。"
    )
    save_progress(progress_path, progress)
    _update_chapter_progress(chapter_dir / "progress.md", "in_progress", chapter.title)
    return chapter


def _update_chapter_progress(progress_md_path: Path, status: str, title: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    content = f"""# 章节进度

- 章节：{title}
- 状态：{status}
- 更新时间：{now}
"""
    write_text(progress_md_path, content)


def mark_chapter_progress_file(chapter_dir: Path, title: str, status: str) -> None:
    _update_chapter_progress(chapter_dir / "progress.md", status, title)
