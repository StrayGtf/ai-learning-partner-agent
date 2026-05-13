from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class UserProfile:
    topic: str
    level: str
    goal: str
    depth: str
    code_practice: bool
    workspace: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChapterSpec:
    index: int
    title: str
    dir_name: str
    estimated_time: str
    code_practice: bool
    objective: str

    @property
    def chapter_id(self) -> str:
        return f"{self.index:02d}"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "title": self.title,
            "dir_name": self.dir_name,
            "estimated_time": self.estimated_time,
            "code_practice": self.code_practice,
            "objective": self.objective,
        }


@dataclass
class LearningPlan:
    profile: UserProfile
    overall_goal: str
    prerequisites: list[str] = field(default_factory=list)
    recommended_order: list[str] = field(default_factory=list)
    review_milestones: list[str] = field(default_factory=list)
    chapters: list[ChapterSpec] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile.to_dict(),
            "overall_goal": self.overall_goal,
            "prerequisites": self.prerequisites,
            "recommended_order": self.recommended_order,
            "review_milestones": self.review_milestones,
            "chapters": [chapter.to_dict() for chapter in self.chapters],
        }
