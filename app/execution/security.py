"""Static safety checks for code submitted to the learning sandbox."""
from __future__ import annotations

import ast
from typing import Optional


BLOCKED_MODULES = {
    "ctypes", "multiprocessing", "resource", "shutil", "signal",
    "socket", "subprocess",
}
BLOCKED_CALLS = {
    "breakpoint", "compile", "eval", "exec", "globals", "help",
    "locals", "memoryview", "vars", "__import__",
}
BLOCKED_ATTRIBUTES = {
    "fork", "forkpty", "kill", "killpg", "popen", "posix_spawn",
    "posix_spawnp", "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe", "system",
    "remove", "removedirs", "rename", "renames", "replace", "rmdir",
    "unlink",
}
BLOCKED_DUNDER_ATTRIBUTES = {
    "__bases__", "__builtins__", "__class__", "__closure__", "__code__",
    "__func__", "__getattribute__", "__globals__", "__mro__",
    "__subclasses__",
}


def validate_code(code: str) -> Optional[str]:
    """Return a learner-facing rejection reason, or ``None`` when safe to run."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Let the runner return its normal, more useful syntax diagnostic.
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                root = name.split(".", 1)[0]
                if root in BLOCKED_MODULES:
                    return f"Importing '{root}' is not permitted."

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                return f"Calling '{node.func.id}' is not permitted."
            if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_ATTRIBUTES:
                return f"Calling '.{node.func.attr}()' is not permitted."

        if isinstance(node, ast.Attribute) and node.attr in BLOCKED_DUNDER_ATTRIBUTES:
            return "Access to interpreter internals is not permitted."

    return None
