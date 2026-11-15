#!/usr/bin/env python3
"""静态卫生检查：重复定义与未使用的导入。

这两类问题测试自己发现不了——被同名覆盖的那一份根本不执行，没被用到的导入也不影响行为。
它们会安静地留下来（本项目就出现过 5 个测试方法被同名覆盖、72 行永远不跑），所以在这里
用 AST 兜一层：零依赖、离线、和其余套件一起进 CI。
"""

from __future__ import annotations

import ast
import glob
import os
import unittest
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = sorted(glob.glob(os.path.join(ROOT, "scripts", "**", "*.py"), recursive=True))
SOURCES += sorted(glob.glob(os.path.join(ROOT, "tests", "*.py")))

#: 这些名字注入后只在特定语句里生效，按语义豁免
IGNORED_IMPORT_NAMES = {"annotations"}


def parse(path: str) -> ast.Module:
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def duplicate_definitions(path: str) -> list[str]:
    """同一个作用域（模块或类）里定义两次的函数。"""
    tree = parse(path)
    scopes = [(tree, "<module>")]
    scopes += [(node, node.name) for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    problems = []
    for scope, label in scopes:
        names = [node.name for node in scope.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for name, count in Counter(names).items():
            if count > 1:
                problems.append(f"{path}: {label}.{name} 定义了 {count} 次")
    return problems


def unused_imports(path: str) -> list[str]:
    """导入后从未被引用（含注解）的名字。"""
    tree = parse(path)
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    used |= {node.value.id for node in ast.walk(tree)
             if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)}
    # __all__ 里列出的名字算“使用”：它们是对外导出的公共接口
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)):
            used |= {item.value for item in ast.walk(node.value) if isinstance(item, ast.Constant)}
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound = [(alias.asname or alias.name).split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__" or any(alias.name == "*" for alias in node.names):
                continue
            bound = [alias.asname or alias.name for alias in node.names]
        else:
            continue
        for name in bound:
            if name in IGNORED_IMPORT_NAMES or name in used:
                continue
            problems.append(f"{path}:{node.lineno} 未使用的导入 {name}")
    return problems


class HygieneTest(unittest.TestCase):
    def test_no_duplicate_definitions(self):
        problems = [item for path in SOURCES for item in duplicate_definitions(path)]
        self.assertEqual(problems, [], "\n".join(problems))

    def test_no_unused_imports(self):
        problems = [item for path in SOURCES for item in unused_imports(path)]
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
