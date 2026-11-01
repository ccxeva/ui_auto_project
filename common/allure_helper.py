# -*- coding: utf-8 -*-
"""
Allure 定制化渲染工具
目标：让报告不仅是"通过/失败"，而是可读的业务过程回放
能力：
1. step()            —— 中文步骤嵌套，失败自动定位到具体动作
2. case_meta()       —— 批量写入 feature/story/severity/tag/description/link
3. attach_text/json/table/screenshot —— 统一命名与格式
4. attach_api_exchange() —— 接口请求/响应以可折叠 JSON 形式挂到报告
5. attach_step_table()   —— 用例步骤与预期以表格形式渲染
"""
import json
from contextlib import contextmanager
from typing import Any, Iterable, Optional

import allure

from common.logger import get_logger

log = get_logger("allure_helper")

# 优先级 -> Allure severity
SEVERITY_MAP = {
    "P0": allure.severity_level.BLOCKER,
    "P1": allure.severity_level.CRITICAL,
    "P2": allure.severity_level.NORMAL,
    "P3": allure.severity_level.MINOR,
}


# --------------------------------------------------------------------------
# 步骤
# --------------------------------------------------------------------------
@contextmanager
def step(title: str, with_args: bool = False):
    """业务步骤，报告内以嵌套层级展示；异常自动标注该步骤为 failed"""
    log.info("STEP ▸ %s", title)
    with allure.step(title):
        yield


def step_pass(title: str) -> None:
    with allure.step(title):
        pass


# --------------------------------------------------------------------------
# 用例元数据
# --------------------------------------------------------------------------
def case_meta(case: dict, layer: str = "UI", owner: str = "QA") -> None:
    """根据 yaml 用例字段批量渲染 Allure 元数据"""
    allure.dynamic.feature(case.get("feature") or case.get("module", "未分类"))
    allure.dynamic.story(case.get("story") or case.get("sub_module", ""))
    allure.dynamic.title(f"[{case['id']}] {case['title']}")
    allure.dynamic.severity(SEVERITY_MAP.get(case.get("priority", "P2"), allure.severity_level.NORMAL))
    allure.dynamic.label("layer", layer)
    allure.dynamic.label("owner", owner)
    allure.dynamic.label("priority", case.get("priority", "P2"))
    allure.dynamic.label("module", case.get("module", ""))
    allure.dynamic.label("case_id", case["id"])
    if case.get("tags"):
        for tag in case["tags"]:
            allure.dynamic.tag(str(tag))
    desc = build_description(case)
    if desc:
        allure.dynamic.description_html(desc)


def build_description(case: dict) -> str:
    """生成 HTML 描述：表格形式呈现前置条件/输入数据/预期，比纯文本更易读"""
    rows = []
    mapping = [
        ("用例编号", case.get("id")),
        ("所属模块", case.get("module")),
        ("重要级别", case.get("priority")),
        ("账号类型", case.get("account")),
        ("前置条件", case.get("precondition") or "见数据准备步骤"),
        ("测试数据", case.get("input")),
        ("备注", case.get("remark")),
    ]
    for k, v in mapping:
        if v:
            rows.append(f"<tr><td style='width:90px;background:#f2f6fa'><b>{k}</b></td>"
                        f"<td>{_esc(str(v))}</td></tr>")
    if not rows:
        return ""
    return ("<div style='font-family:Segoe UI,Microsoft YaHei'>"
            "<table style='border-collapse:collapse;width:100%;font-size:12px' "
            "border='1' cellpadding='4'>" + "".join(rows) + "</table></div>")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\n", "<br/>"))


# --------------------------------------------------------------------------
# 附件
# --------------------------------------------------------------------------
def attach_text(name: str, content: str, attachment_type=None) -> None:
    if content is None or content == "":
        return
    allure.attach(str(content), name=name,
                  attachment_type=attachment_type or allure.attachment_type.TEXT)


def attach_json(name: str, data: Any) -> None:
    if data is None:
        return
    if not isinstance(data, (dict, list)):
        attach_text(name, str(data))
        return
    allure.attach(json.dumps(data, ensure_ascii=False, indent=2),
                  name=name, attachment_type=allure.attachment_type.JSON)


def attach_table(name: str, headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> None:
    """表格附件：在报告里渲染为真正的 HTML 表格"""
    headers = list(headers)
    trs = []
    for r in rows:
        tds = "".join(
            f"<td style='border:1px solid #d0d7de;padding:4px 6px'>{_esc(str(c))}</td>" for c in r
        )
        trs.append(f"<tr>{tds}</tr>")
    ths = "".join(
        f"<th style='border:1px solid #d0d7de;padding:4px 6px;background:#1f3b63;color:#fff'>{h}</th>"
        for h in headers
    )
    html = ("<div style='font-family:Segoe UI,Microsoft YaHei;font-size:12px'>"
            "<table style='border-collapse:collapse;width:100%'>"
            f"<thead><tr>{ths}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>")
    allure.attach(html, name=name, attachment_type=allure.attachment_type.HTML)


def attach_screenshot(page, name: str = "失败截图") -> None:
    try:
        allure.attach(page.screenshot(full_page=True), name=name,
                      attachment_type=allure.attachment_type.PNG)
    except Exception as exc:  # noqa: BLE001
        log.warning("截图失败：%s", exc)


def attach_api_exchange(title: str, request: dict, response: Any, elapsed_ms: Optional[float] = None) -> None:
    """接口报文以两段 JSON 挂载，报告里可展开查看"""
    payload = {"request": request, "response": response}
    if elapsed_ms is not None:
        payload["elapsed_ms"] = round(elapsed_ms, 1)
    attach_json(f"接口报文 · {title}", payload)


def attach_steps_table(case: dict) -> None:
    """把 YAML 中的步骤落到报告，便于评审对照"""
    steps = case.get("steps") or []
    rows = []
    for i, s in enumerate(steps, 1):
        action = s.get("action", "")
        extra = ", ".join(f"{k}={v}" for k, v in s.items() if k != "action")
        rows.append([i, action, extra or "-"])
    if rows:
        attach_table("用例步骤（YAML 数据驱动）", ["#", "action", "参数"], rows)


def attach_yaml_case(case: dict) -> None:
    attach_json("用例原始数据（YAML）", case)
