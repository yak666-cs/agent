"""
路径解析工具
"""

import pathlib


def resolve_path(path: str) -> str:
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
