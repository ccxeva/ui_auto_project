# -*- coding: utf-8 -*-
"""
pytest 全局夹具与钩子
职责：
1. 命令行参数扩展（--module / --priority / --tags / --headed / --slowmo）
2. browser / context / page 三层夹具：每个用例独立 context，保证 Cookie 与购物车互不干扰
3. 用例数据加载与参数化：从 YAML 读取，自动映射 P0~P3 标记
4. Allure 环境信息、失败自动截图、用例级日志
"""
import sys
from pathlib import Path
from typing import List

import allure
import pytest
from playwright.sync_api import sync_playwright

# 保证以项目根目录为 import 起点
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.allure_helper import (  # noqa: E402
    attach_json, attach_screenshot, attach_steps_table, attach_yaml_case, case_meta,
)
from common.logger import get_logger  # noqa: E402
from common.yaml_loader import load_cases  # noqa: E402
from config.settings import settings  # noqa: E402

log = get_logger("conftest")


# ==============================================================================
# 1. 命令行参数
# ==============================================================================
def pytest_configure(config):
    """
    集中在此注入 Allure 结果目录（绝对路径），避免 ini 中相对路径随工作目录漂移
    同时注册项目元信息，出现在报告的 Environment 与 Overview 区块
    """
    if config.option.allure_report_dir is None:
        allure_dir = Path(settings.root_dir) / settings.report["allure_results"]
        allure_dir.mkdir(parents=True, exist_ok=True)
        config.option.allure_report_dir = str(allure_dir)
    config.stash if hasattr(config, "stash") else None  # 兼容 pytest 7/8/9 API
    log.info("Allure 结果目录：%s", config.option.allure_report_dir)


def pytest_addoption(parser):
    group = parser.getgroup("demoblaze", "DemoBlaze UI 自动化参数")
    group.addoption("--module", action="append", default=None,
                    help="按模块过滤，可多次指定，如 --module 加入购物车")
    group.addoption("--priority", action="append", default=None,
                    help="按优先级过滤，如 --priority P0（也可直接用 -m P0）")
    group.addoption("--tags", action="append", default=None,
                    help="按标签过滤，如 --tags smoke")
    group.addoption("--ui-headed", action="store_true", default=False,
                    help="有头模式运行（本地调试）；与 playwright 插件 --headed 等价但独立")
    group.addoption("--ui-slowmo", action="store", default=0, type=int,
                    help="每步放慢毫秒数")
    group.addoption("--case-file", action="store", default=None,
                    help="指定用例数据文件，默认取 config.yaml 中的 data.case_file")


# ==============================================================================
# 2. 用例数据与参数化
# ==============================================================================
def _case_params(config) -> List[dict]:
    case_file = config.getoption("--case-file") or settings.case_file
    cases = load_cases(
        case_file,
        marker="@data",
        modules=config.getoption("--module"),
        priorities=config.getoption("--priority"),
        tags=config.getoption("--tags"),
    )
    if not cases:
        log.warning("未匹配到任何用例，请检查 --module / --priority / --tags 过滤条件")
    return cases


def pytest_generate_tests(metafunc):
    """
    把 YAML 用例参数化到 test_ 函数上（函数需声明 case 参数）
    - 若测试函数声明了 case_module，则只注入该模块的用例（收集阶段即拆分，数量精确）
    - 否则注入全部用例
    """
    if "case" not in metafunc.fixturenames:
        return

    cases = _case_params(metafunc.config)
    module = getattr(metafunc.function, "case_module", None)
    if module:
        cases = [c for c in cases if c.get("module") == module]

    metafunc.parametrize(
        "case",
        cases,
        ids=[f"{c['id']}-{c['priority']}" for c in cases],
        scope="function",
    )


def pytest_collection_modifyitems(config, items):
    """根据用例的 priority / module / tags 自动打标记，支持 -m 过滤"""
    for item in items:
        case = getattr(item, "callspec", None)
        case = case.params.get("case") if case else None
        if not case:
            continue
        pri = case.get("priority", "P2")
        item.add_marker(getattr(pytest.mark, pri))
        for tag in (case.get("tags") or []):
            marker = getattr(pytest.mark, tag, None)
            if marker:
                item.add_marker(marker)
        # 按模块自动打 marked：加入购物车 -> cart，删除记录 -> delete
        module = case.get("module", "")
        if "加入购物车" in module:
            item.add_marker(pytest.mark.cart)
        elif "删除记录" in module:
            item.add_marker(pytest.mark.delete)
        elif "主流程" in module:
            item.add_marker(pytest.mark.e2e)
        if case.get("skip") or case.get("enabled") is False:
            item.add_marker(pytest.mark.skip(reason="用例数据中标记为跳过"))
        # 缺陷复现用例：当前版本预期失败，修复后自动转为通过（strict=False）
        # 报告中显示为 xfail（预期失败），与真正的失败区分开，避免污染通过率统计
        if case.get("expect_fail"):
            item.add_marker(pytest.mark.xfail(
                reason=f"缺陷复现：{case.get('remark', '已知问题待修复')}",
                strict=False,
            ))


# ==============================================================================
# 3. Playwright 浏览器夹具
# ==============================================================================
@pytest.fixture(scope="session")
def playwright_instance():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright_instance, request):
    cfg = settings.browser
    headed = request.config.getoption("--ui-headed") or cfg.get("headed", False)
    slow_mo = request.config.getoption("--ui-slowmo") or cfg.get("slow_mo", 0)
    browser_type = getattr(playwright_instance, cfg.get("name", "chromium"))
    log.info("启动浏览器：%s（headed=%s, slow_mo=%s）", cfg.get("name"), headed, slow_mo)
    b = browser_type.launch(headless=not headed, slow_mo=slow_mo,
                            args=["--disable-dev-shm-usage", "--no-sandbox"])
    yield b
    b.close()
    log.info("浏览器已关闭")


@pytest.fixture(scope="function")
def context(browser, request):
    """每个用例一个独立 context：保证 Cookie / localStorage / 购物车互不污染"""
    cfg = settings.browser
    ctx = browser.new_context(
        viewport=cfg.get("viewport", {"width": 1440, "height": 900}),
        locale=cfg.get("locale", "en-US"),
        ignore_https_errors=cfg.get("ignore_https_errors", True),
        base_url=settings.base_url,
    )
    ctx.set_default_timeout(settings.timeout["implicit"])
    ctx.set_default_navigation_timeout(settings.timeout["navigation"])
    yield ctx
    # 失败用例保留上下文信息再关闭
    ctx.close()


@pytest.fixture(scope="function")
def page(context, request):
    pg = context.new_page()
    # 收集控制台日志，失败时附到报告
    console_logs = []
    pg.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
    pg._console_logs = console_logs  # 供钩子读取
    yield pg
    if settings.report.get("attach_console_log") and console_logs:
        try:
            attach_json("浏览器控制台日志", console_logs[-50:])
        except Exception:  # noqa: BLE001
            pass
    pg.close()


@pytest.fixture(scope="function")
def api():
    """接口客户端：所有用例共享一个实例，保证 token 一致"""
    from common.api_client import ApiClient
    return ApiClient()


# ==============================================================================
# 4. 用例级钩子：Allure 元数据 / 失败截图
# ==============================================================================
@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """失败/错误时附加现场信息（截图 + URL），需在报告生成前执行"""
    report = yield

    if report.when in ("setup", "call") and report.failed:
        page = item.funcargs.get("page") if hasattr(item, "funcargs") else None
        if page is not None:
            try:
                attach_screenshot(page, f"失败截图-{report.when}")
                attach_json("失败现场", {"url": page.url, "title": page.title()})
                logs = getattr(page, "_console_logs", None)
                if logs:
                    attach_json("失败时控制台日志", logs[-30:])
            except Exception as exc:  # noqa: BLE001
                log.warning("失败现场采集失败：%s", exc)
    return report


def pytest_runtest_setup(item):
    """用例开始：写入 Allure 元数据与数据驱动信息"""
    case = None
    if hasattr(item, "callspec") and "case" in item.callspec.params:
        case = item.callspec.params["case"]
    if not case:
        return
    case_meta(case, layer="UI", owner="QA")
    attach_yaml_case(case)
    attach_steps_table(case)


# ==============================================================================
# 5. Allure 环境信息
# ==============================================================================
def pytest_sessionstart(session):
    results_dir = Path(settings.root_dir) / settings.report["allure_results"]
    results_dir.mkdir(parents=True, exist_ok=True)
    env_file = results_dir / "environment.properties"
    env_file.write_text(
        "\n".join([
            # Allure 读取 properties 默认 ISO-8859-1，中文会乱码，故值统一用 ASCII
            "Environment=DemoBlaze-Demo",
            f"Base.URL={settings.base_url}",
            f"API.URL={settings.api_base_url}",
            f"Browser={settings.browser.get('name')}",
            f"Headless={not settings.browser.get('headed', False)}",
            f"Python={sys.version.split()[0]}",
            f"Platform={sys.platform}",
            "Test.Account=yang-zoe",
            "Framework=Pytest + Playwright + Allure",
            "Pattern=POM + YAML Data-Driven",
        ]),
        encoding="utf-8",
    )
    log.info("Allure 环境信息已写入：%s", env_file)


def pytest_sessionfinish(session, exitstatus):
    log.info("本次执行结束，exitstatus=%s", exitstatus)
