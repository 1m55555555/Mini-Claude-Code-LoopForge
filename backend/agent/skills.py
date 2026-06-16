from dataclasses import dataclass
from pathlib import Path

from agent.errors import ToolError
from agent.tools.registry import ToolResult


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    path: Path

    def catalog_line(self) -> str:
        return f"- `{self.name}`: {self.description}"


class SkillRegistry:
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir.resolve()
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._skills = self._scan()

    def definitions(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def load_skill(self, arguments: dict[str, object]) -> ToolResult:
        name = str(arguments.get("name", "")).strip()
        if not name:
            raise ToolError("skill name is required")

        skill = self._skills.get(name)
        if skill is None:
            raise ToolError(f"unknown skill: {name}")

        return ToolResult(output=skill.path.read_text(encoding="utf-8"))

    def _scan(self) -> dict[str, SkillDefinition]:
        skills: dict[str, SkillDefinition] = {}
        for path in sorted(self.skills_dir.glob("*/SKILL.md")):
            name, description = _parse_skill_file(path)
            if not name:
                name = path.parent.name
            skills[name] = SkillDefinition(name=name, description=description, path=path)
        return skills


def _parse_skill_file(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    metadata = _parse_frontmatter(text)
    name = metadata.get("name", "")
    description = metadata.get("description", "")

    if not description:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line != "---" and ":" not in line:
                description = line
                break

    return name, description or "No description"


def _parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    metadata: dict[str, str] = {}
    for line in lines[1:]:
        line = line.strip()
        if line == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata

