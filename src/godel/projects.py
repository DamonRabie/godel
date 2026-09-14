from pathlib import Path
import re
import shutil
import subprocess
import uuid

from .storage import atomic_json, identifier, read_json, tags, text


def project_path(home, name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
        raise ValueError(
            "Use a project name with lowercase letters, digits, hyphens or underscores."
        )
    path = Path(home) / "projects" / name
    if not path.resolve().is_relative_to(Path(home).resolve()):
        raise ValueError("Project path leaves the Godel workspace.")
    return path.resolve()


def read_project(root):
    data = read_json(Path(root) / "project.json")
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise ValueError("Unsupported project.json; expected schemaVersion 1.")
    identifier(data.get("id"))
    text(data.get("name"), "project name", 120)
    text(data.get("goal"), "goal")
    data["tags"] = tags(data.get("tags"))
    for field, maximum in (("maxRunSeconds", 86400), ("maxRunsPerSession", 1000)):
        if type(data.get(field)) is not int or not 1 <= data[field] <= maximum:
            raise ValueError(f"{field} must be an integer between 1 and {maximum}.")
    cap = data.get("maxCandidatesPerSession")
    if cap is not None and (type(cap) is not int or not 1 <= cap <= 10000):
        raise ValueError("maxCandidatesPerSession must be an integer between 1 and 10000.")
    evaluation = data.get("evaluation")
    if evaluation is not None:
        if not isinstance(evaluation, dict):
            raise ValueError("evaluation must be null or an object.")
        for key in ("datasetId", "splitId", "metric"):
            text(evaluation.get(key), key, 200)
        if evaluation.get("direction") not in ("minimize", "maximize"):
            raise ValueError("Metric direction must be minimize or maximize.")
    return data


def init_project(home, name, goal="Define the ML objective with the user."):
    root = project_path(home, name)
    if root.exists():
        raise ValueError(
            f"Directory already exists: {root}; initialization never overwrites a project."
        )
    if not shutil.which("git"):
        raise ValueError("Git is required to create independent ML project repositories.")
    template = Path(home) / "templates" / "project"
    root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, root)
    for path in root.rglob("*"):
        if path.is_file():
            path.write_text(path.read_text().replace("__PROJECT_NAME__", name))
    project = dict(
        schemaVersion=1,
        id=str(uuid.uuid4()),
        name=name,
        goal=text(goal, "goal"),
        tags=[],
        maxRunSeconds=300,
        maxRunsPerSession=5,
        evaluation=None,
    )
    atomic_json(root / "project.json", project)
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    return root, project
