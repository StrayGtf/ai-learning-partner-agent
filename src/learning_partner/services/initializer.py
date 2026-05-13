from __future__ import annotations

from pathlib import Path

from learning_partner.models import UserProfile
from learning_partner.services.llm_client import get_llm_client_from_env
from learning_partner.services.plan_service import build_plan, load_learning_plan, save_learning_plan
from learning_partner.services.progress_service import build_initial_progress, save_progress
from learning_partner.utils.fs import ensure_dir, write_text_if_absent


def _workspace_readme(profile: UserProfile, ai_enabled: bool) -> str:
    return f"""# 学习项目：{profile.topic}

这是一个由 AI Learning Partner Agent 生成的本地学习工程。

## 如何使用

1. 查看并编辑 `learning-plan.md`（可删除不想学的章节）
2. 执行 `learning-partner next --workspace <路径>` 逐章生成内容
3. 每章完成后，用 `learning-partner answer` 提交测验回答
4. 用 `learning-partner status` 查看最新进度

## 学习者输入

- 当前基础：{profile.level}
- 学习目标：{profile.goal}
- 学习深度：{profile.depth}
- 代码实践：{"是" if profile.code_practice else "否"}

## AI 模式

- 当前是否启用大模型 API：{"是" if ai_enabled else "否（使用本地模板兜底）"}
"""


def initialize_workspace(profile: UserProfile, force: bool = False) -> Path:
    workspace = Path(profile.workspace).resolve()
    ensure_dir(workspace)
    ensure_dir(workspace / "chapters")
    ensure_dir(workspace / "reviews")
    ensure_dir(workspace / "resources")

    llm_client = get_llm_client_from_env()
    ai_enabled = llm_client.enabled

    write_text_if_absent(workspace / "README.md", _workspace_readme(profile, ai_enabled))
    write_text_if_absent(workspace / "notes.md", "# 学习笔记\n\n> 这里保留你的个人笔记，程序默认不会覆盖。\n")
    write_text_if_absent(workspace / "resources" / "references.md", "# 参考资料\n\n- 待补充\n")
    write_text_if_absent(workspace / "resources" / "glossary.md", "# 术语表\n\n- 待补充\n")
    write_text_if_absent(workspace / "reviews" / "review-01.md", "# 阶段复习 01\n\n- 待补充\n")

    plan_path = workspace / "learning-plan.md"
    progress_path = workspace / "progress.json"

    if force or not plan_path.exists():
        plan = build_plan(profile, llm_client=llm_client)
        save_learning_plan(plan_path, plan)

    plan = load_learning_plan(plan_path, fallback_profile=profile)
    if force or not progress_path.exists():
        progress = build_initial_progress(plan)
        save_progress(progress_path, progress)

    return workspace
