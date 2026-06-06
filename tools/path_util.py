"""
路径解析工具
"""

import pathlib
import os


def _expand_desktop_alias(path: str) -> str:
    normalized = path.replace("/", "\\")
    prefixes = ("桌面\\", "desktop\\", ".\\桌面\\", ".\\desktop\\")
    lower = normalized.lower()

    for prefix in prefixes:
        if lower.startswith(prefix.lower()):
            rel = normalized[len(prefix):]
            desktop = pathlib.Path.home() / "Desktop"
            return str(desktop / rel)

    if normalized in ("桌面", "desktop", ".\\桌面", ".\\desktop"):
        return str(pathlib.Path.home() / "Desktop")

    return path


def resolve_path(path: str) -> str:
    path = os.path.expandvars(os.path.expanduser(_expand_desktop_alias(path)))
    path_obj = pathlib.Path(path)
    if path_obj.is_absolute():
        return path

    candidates = [pathlib.Path.cwd()]
    try:
        project_root = pathlib.Path(__file__).resolve().parent.parent.parent
        candidates.append(project_root)
    except NameError:
        pass

    for base in candidates:
        candidate = base / path
        if candidate.exists():
            return str(candidate.resolve())
    return path
