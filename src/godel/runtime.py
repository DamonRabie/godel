"""Explicit Pi configuration and resource loading for this workspace."""

import os
from pathlib import Path
import sys

from .storage import atomic_json


def local_environment(source=None):
    source = os.environ if source is None else source
    keys = (
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "COLORTERM",
        "TERM_PROGRAM",
        "TERM_PROGRAM_VERSION",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "TMP",
        "TEMP",
    )
    return {key: source[key] for key in keys if key in source}


def bundled_skills(home):
    """Only repository-owned entrypoints; Pi handles metadata and on-demand reads."""
    home = Path(home).resolve()
    paths = sorted((home / "agent/skills").glob("*/SKILL.md"))
    for path in paths:
        if not path.resolve().is_relative_to(home / "agent/skills") or not path.is_file():
            raise ValueError(f"Godel skill must stay inside agent/skills: {path}")
    return paths


def launch_spec(home, project, extra=()):
    home, project = Path(home).resolve(), Path(project).resolve()
    if not project.is_relative_to(home):
        raise ValueError("Projects must be inside this Godel workspace.")
    binary = home / "node_modules" / ".bin" / "pi"
    extension = home / "dist" / "pi" / "extension.js"
    if not binary.exists() or not extension.exists():
        raise ValueError(
            "Run make setup first to install the pinned Pi runtime and build its adapter."
        )
    agent_dir = home / ".godel" / "pi"
    agent_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings = agent_dir / "settings.json"
    if not settings.exists():
        atomic_json(settings, {"quietStartup": False})
    env = local_environment()
    env.update(
        PI_CODING_AGENT_DIR=str(agent_dir),
        PI_TELEMETRY="0",
        GODEL_HOME=str(home),
        GODEL_PYTHON=sys.executable,
    )
    command = [
        str(binary),
        "--no-extensions",
        "--extension",
        str(extension),
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--append-system-prompt",
        str(home / "agent" / "system.md"),
        "--session-dir",
        str(project / ".godel" / "sessions"),
        "--tools",
        "read,write,edit,bash,grep,find,ls,godel_checkpoint,godel_run,godel_review,godel_propose_lesson,godel_history,godel_history_event,godel_evidence,godel_decision",
    ]
    for skill in bundled_skills(home):
        command.extend(["--skill", str(skill)])
    for prompt in sorted((home / "agent" / "prompts").glob("*.md")):
        command.extend(["--prompt-template", str(prompt)])
    command.extend(extra)
    return command, env
