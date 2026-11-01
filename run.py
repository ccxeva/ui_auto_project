#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DemoBlaze 购物车 UI 自动化 - Python 一键入口
与 scripts/run.sh 功能对等，供偏好统一 Python 技术栈 / Windows 环境使用

用法：
    python run.py                       # 全量执行 + 生成报告
    python run.py -m P0                 # 仅 P0 冒烟（参数原样透传给 pytest）
    python run.py --module 加入购物车    # 按模块
    python run.py --ui-headed           # 有头调试
    python run.py -k 0001 --no-report   # 单条调试，跳过报告生成
    python run.py report                # 只生成报告（不执行用例）
    python run.py serve                 # 起本地服务实时预览报告（Ctrl+C 退出）

设计说明（为什么内部仍有一处 subprocess）：
    pytest 提供 Python API（pytest.main），可直接调用；
    但 Allure 报告生成器是独立的命令行程序（allure generate），
    官方没有 Python API，只能通过 subprocess 调用——这是唯一无法纯 Python 化的环节
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "reports" / "allure-results"
REPORT_DIR = ROOT / "reports" / "allure-report"


def _ensure_import_path() -> None:
    """保证项目根目录在 sys.path，替代 shell 里的 export PYTHONPATH"""
    sys.path.insert(0, str(ROOT))


def _check_dependencies() -> None:
    """依赖缺失时给出明确提示（不自动安装——Python 入口保持行为可预期）"""
    missing = []
    for mod in ("pytest", "playwright", "allure", "yaml", "requests"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        sys.exit(
            f"[!] 缺少依赖：{', '.join(missing)}\n"
            f"    请先执行：pip install -r {ROOT / 'requirements.txt'}\n"
            f"    以及：python -m playwright install chromium"
        )


def _clean_results() -> None:
    """每次执行前清理上一轮结果，避免历史 attachment 干扰报告"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "reports" / "logs").mkdir(parents=True, exist_ok=True)
    for f in RESULTS_DIR.iterdir():
        if f.suffix in (".json", ".txt", ".html"):
            f.unlink()


def _has_allure_cli() -> bool:
    return shutil.which("allure") is not None


def _generate_report() -> int:
    """生成静态 Allure HTML 报告（必须调外部 allure CLI，无 Python API）"""
    if not any(RESULTS_DIR.glob("*-result.json")):
        print(f"[!] 结果目录为空：{RESULTS_DIR}，请先执行用例")
        return 1
    if not _has_allure_cli():
        print("[!] 未检测到 allure 命令，跳过 HTML 报告生成")
        print("    安装：npm install -g allure-commandline（推荐，无需 Java）")
        print("    已有结果可直接预览：allure serve " + str(RESULTS_DIR))
        return 1
    print("[i] 生成 Allure 报告 ...")
    ret = subprocess.run(
        ["allure", "generate", str(RESULTS_DIR), "-o", str(REPORT_DIR), "--clean"]
    ).returncode
    if ret == 0:
        print(f"[✓] 报告已生成：{REPORT_DIR / 'index.html'}")
        print(f"    打开方式：allure open {REPORT_DIR}")
    return ret


def _serve() -> int:
    """临时起服务预览报告（等价 allure serve）"""
    if not _has_allure_cli():
        print("[!] 未检测到 allure 命令：npm install -g allure-commandline")
        return 1
    return subprocess.run(["allure", "serve", str(RESULTS_DIR)]).returncode


def _run_tests(pytest_args: list[str], clean: bool = True) -> int:
    """执行用例：pytest.main 的 Python API，无需 subprocess"""
    import pytest

    os.environ["PYTHONPATH"] = f"{ROOT}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"
    print("=" * 62)
    print(" DemoBlaze UI 自动化")
    print(f" 项目目录 : {ROOT}")
    print(f" 结果目录 : {RESULTS_DIR.relative_to(ROOT)}")
    print(" 用例文件 : data/cart_cases.yaml")
    print("=" * 62)

    if clean:
        _clean_results()
    code = pytest.main(pytest_args)

    print("-" * 62)
    if code == 0:
        print("[✓] 用例全部通过")
    else:
        print(f"[✗] pytest 退出码={code}（5=无用例被收集，1=存在失败，2=中断）")
    return code


def main(argv: list[str]) -> int:
    _ensure_import_path()

    # 子命令：report / serve
    if argv and argv[0] in ("report", "serve"):
        _ensure_import_path()
        return _generate_report() if argv[0] == "report" else _serve()

    # 分离自定义开关与 pytest 透传参数
    gen_report = "--no-report" not in argv
    pytest_args = [a for a in argv if a != "--no-report"]
    # 收集/列表等只读操作不清理历史结果，避免误删报告源数据
    readonly = any(a in ("--collect-only", "--co", "--list", "--markers", "--help")
                   for a in pytest_args)

    _check_dependencies()
    code = _run_tests(pytest_args, clean=not readonly)

    if gen_report and code in (0, 1):   # 有失败用例也生成报告，便于排查
        _generate_report()
    return 0 if code == 0 else code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
