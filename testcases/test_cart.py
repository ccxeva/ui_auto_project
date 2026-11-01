# -*- coding: utf-8 -*-
"""
测试用例入口（薄壳层）
设计说明：
- 本层不写任何业务逻辑与断言，只做"取数据 -> 执行 -> 交给 YAML 断言"
- 三个测试函数分别对应三个业务模块，conftest 依据 case_module 在收集阶段精确拆分参数，
  因此每个函数只收集自己模块的用例，pytest 统计的用例数与 YAML 条数一致
- 真正的步骤在 data/cart_cases.yaml 中声明，新增用例无需改本文件
"""
import pytest

from common.allure_helper import attach_json, step
from flows.step_executor import StepExecutor

MODULE_ADD = "电商系统 → 购物车模块 → 加入购物车"
MODULE_DEL = "电商系统 → 购物车模块 → 删除记录"
MODULE_E2E = "电商系统 → 主流程 → 登录到购物车删除"


def _run(case, page, api):
    """统一执行骨架：构造执行器 -> 按 YAML 步骤顺序执行 -> 附加执行上下文"""
    executor = StepExecutor(page, api=api)
    with step(f"执行用例 {case['id']}：{case['title']}"):
        executor.execute(case["steps"])
    attach_json("执行结果上下文", {
        "case_id": case["id"],
        "priority": case["priority"],
        "module": case["module"],
        "results": {k: v for k, v in executor.results.items()
                    if isinstance(v, (str, int, float, list, dict))},
    })
    return executor


def test_add_to_cart(case: dict, page, api):
    """加入购物车模块：MALL-CART-FUNC-0001 ~ 0013（P0/P1/P2）"""
    _run(case, page, api)


test_add_to_cart.case_module = MODULE_ADD


def test_delete_cart_item(case: dict, page, api):
    """删除购物车记录模块：MALL-CARTDEL-FUNC-0001 ~ 0012"""
    _run(case, page, api)


test_delete_cart_item.case_module = MODULE_DEL


def test_main_flow_e2e(case: dict, page, api):
    """主流程端到端：MALL-E2E-FUNC-0001 ~ 0006"""
    _run(case, page, api)


test_main_flow_e2e.case_module = MODULE_E2E


def test_smoke_usage_note():
    """
    使用说明用例（无业务逻辑，恒通过）
    常用命令见 docstring 与 Allure 附件，避免误删
    """
    with step("记录常用执行命令"):
        attach_json("执行命令速查", {
            "全量": "pytest",
            "P0 冒烟": "pytest -m P0",
            "购物车模块": "pytest --module 加入购物车",
            "删除模块": "pytest --module 删除记录",
            "主流程": "pytest --module 主流程",
            "接口类用例": "pytest -m api",
            "单条用例": "pytest -k MALL-CART-FUNC-0001",
            "生成报告": "allure generate reports/allure-results -o reports/allure-report --clean",
        })
