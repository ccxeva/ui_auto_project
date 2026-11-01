# -*- coding: utf-8 -*-
"""
YAML 数据驱动加载器
职责：
1. 读取 data/*.yaml，展开为 pytest 可直接参数化的用例列表
2. 支持用例级/步骤级变量 ${var} 替换，实现同一份数据多场景复用
3. 支持 skip / xfail 标记、tags 过滤、按模块筛选
4. 数据结构校验，数据写错时给出明确行号与原因，而不是在用例内报 KeyError

YAML 用例结构（见 data/cart_cases.yaml）：
- id: 用例编号
  title: 用例标题
  module: 所属模块
  priority: P0
  marker: "@data"
  tags: [smoke, cart]
  account: primary | guest | none
  prepare:               # 前置数据准备（走接口，快速且稳定）
    clear_cart: true
  steps:                 # 业务动作步骤（由 flows 层解释执行）
    - action: login
    - action: open_product
      product: macbook_air
  assert:                # 断言步骤
    - action: assert_cart_count
      expected: 1
"""
import re
from pathlib import Path
from typing import Any

import yaml

from common.logger import get_logger

log = get_logger("yaml_loader")

_VAR_PATTERN = re.compile(r"\$\{([^}^{]+)\}")

REQUIRED_FIELDS = ("id", "title", "steps")
VALID_ACCOUNTS = ("primary", "secondary", "guest", "none")


# --------------------------------------------------------------------------
# 变量替换
# --------------------------------------------------------------------------
def _resolve_var(expr: str, context: dict) -> Any:
    """解析 ${a.b.c} 形式的取值表达式"""
    cur: Any = context
    for part in expr.strip().split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, (list, tuple)) and part.isdigit():
            cur = cur[int(part)]
        else:
            return None
    return cur


def substitute(value: Any, context: dict) -> Any:
    """递归替换数据结构中的 ${var}"""
    if isinstance(value, str):
        # 整串就是一个变量引用：保留原始类型（数字/字典）
        m = _VAR_PATTERN.fullmatch(value.strip())
        if m:
            resolved = _resolve_var(m.group(1), context)
            return value if resolved is None else resolved
        # 字符串内嵌变量：转为字符串拼接
        def _repl(mo):
            r = _resolve_var(mo.group(1), context)
            return mo.group(0) if r is None else str(r)
        return _VAR_PATTERN.sub(_repl, value)
    if isinstance(value, dict):
        return {k: substitute(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, context) for v in value]
    return value


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------
def _validate(case: dict, index: int, source: Path):
    where = f"{source.name} 第 {index + 1} 条用例"
    for field in REQUIRED_FIELDS:
        if not case.get(field):
            raise ValueError(f"{where} 缺少必填字段 `{field}`")
    if not isinstance(case.get("steps"), list) or not case["steps"]:
        raise ValueError(f"{where} 的 steps 必须是非空列表")
    for s in case["steps"]:
        if not isinstance(s, dict) or "action" not in s:
            raise ValueError(f"{where} 的步骤缺少 action 字段：{s}")
    account = case.get("account", "primary")
    if account not in VALID_ACCOUNTS:
        raise ValueError(f"{where} 的 account 非法（{account}），可选：{VALID_ACCOUNTS}")
    pri = str(case.get("priority", "P2")).upper()
    if pri not in ("P0", "P1", "P2", "P3"):
        raise ValueError(f"{where} 的 priority 非法：{pri}")
    case["priority"] = pri


# --------------------------------------------------------------------------
# 加载
# --------------------------------------------------------------------------
def load_yaml(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"用例数据文件不存在：{p}")
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def load_cases(path: str | Path,
               marker: str | None = "@data",
               modules: list[str] | None = None,
               tags: list[str] | None = None,
               priorities: list[str] | None = None,
               only_enabled: bool = True) -> list[dict]:
    """
    加载并过滤用例
    :param marker: 仅加载带该标记的用例；None 表示不按标记过滤
    :param modules: 按模块名过滤（精确匹配）
    :param tags: 命中任一 tag 即保留
    :param priorities: 按优先级过滤
    """
    raw = load_yaml(path)
    defaults = raw.get("defaults", {}) or {}
    variables = raw.get("variables", {}) or {}
    cases_raw = raw.get("cases", []) or []

    result: list[dict] = []
    for idx, case in enumerate(cases_raw):
        merged = {**defaults, **case}
        # 用例级 variables 覆盖全局 variables
        ctx = {**variables, **merged.get("variables", {})}
        merged = substitute(merged, ctx)
        _validate(merged, idx, Path(path))

        if only_enabled and merged.get("enabled") is False:
            continue
        if marker and merged.get("marker") != marker:
            continue
        if modules and merged.get("module") not in modules:
            continue
        if priorities and merged["priority"].upper() not in [p.upper() for p in priorities]:
            continue
        if tags:
            case_tags = set(merged.get("tags") or [])
            if not case_tags & set(tags):
                continue
        merged["_source"] = str(path)
        result.append(merged)

    log.info("加载用例 %d 条（文件 %s）", len(result), Path(path).name)
    return result


def load_cases_by_module(path: str | Path, module_keyword: str, **kwargs) -> list[dict]:
    """按模块关键字模糊匹配（如 '加入购物车'）"""
    cases = load_cases(path, **kwargs)
    return [c for c in cases if module_keyword in c.get("module", "")]


if __name__ == "__main__":
    from config.settings import settings
    cs = load_cases(settings.case_file)
    for c in cs:
        print(c["id"], c["priority"], c["module"], "| steps:", len(c["steps"]))
