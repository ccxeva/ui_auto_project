# -*- coding: utf-8 -*-
"""
YAML 步骤执行引擎（数据驱动的核心）
职责：把 YAML 里声明的 action 解释为 CartFlow / AssertionFlow 上的方法调用
优势：
- 新增用例只需改 YAML，无需写 Python 代码
- action 注册表集中管理，拼写错误在加载期即可发现（而不是执行到一半才报错）
- 每个 action 的执行参数、结果都会写入 Allure，便于追溯数据驱动过程

action 一览（与 data/cart_cases.yaml 对应）：
    环境类 : open_site / login / ensure_login / logout / login_expect_failure
    浏览类 : select_laptops / open_product / open_product_via_list / open_cart
    加购类 : add_to_cart / add_to_cart_times / add_products / add_to_cart_api
    删除类 : delete_first / delete_by_title / delete_all / refresh_cart
    数据类 : api_clear_cart / api_cart_items
    断言类 : assert_*（见 ASSERTION_ACTIONS）
"""
from typing import Callable, Dict

from common.allure_helper import attach_json, step
from common.logger import get_logger
from config.settings import settings
from flows.assertion_flow import AssertionFlow
from flows.cart_flow import CartFlow
from flows.edge_flow import EdgeFlow

log = get_logger("step_executor")


class StepExecutor:
    """按 action 名分发到具体业务方法"""

    def __init__(self, page, api=None):
        self.page = page
        self.flow = CartFlow(page, api=api)
        self.assert_flow = AssertionFlow(self.flow)
        self.edge = EdgeFlow(self.flow)
        self.results: Dict[str, object] = {}

        # ---------------- action 注册表 ----------------
        self.actions: Dict[str, Callable] = {
            # 环境与登录
            "open_site": self._open_site,
            "login": self._login,
            "ensure_login": self.flow.ensure_login,
            "logout": self.flow.logout,
            "login_expect_failure": self._login_expect_failure,
            # 浏览
            "select_laptops": self._select_laptops,
            "open_product": self._open_product,
            "open_product_via_list": self._open_product_via_list,
            "open_cart": self._open_cart,
            # 加购
            "add_to_cart": self._add_to_cart,
            "add_to_cart_times": self._add_to_cart_times,
            "add_products": self._add_products,
            "add_to_cart_api": self.flow.add_to_cart_api,
            # 删除
            "delete_first": self.flow.delete_first,
            "delete_by_title": self._delete_by_title,
            "delete_all": self.flow.delete_all,
            "refresh_cart": self.flow.refresh_cart,
            # 数据准备
            "api_clear_cart": self.flow.api_clear_cart,
            "api_cart_items": self.flow.api_cart_items,
            # 异常 / 安全 / 会话
            "add_invalid_product_api": self.edge.add_invalid_product,
            "add_to_cart_with_fake_token": self.edge.add_with_fake_token,
            "replay_delete": self.edge.replay_delete,
            "delete_not_exist_id": self.edge.delete_not_exist_id,
            "cross_account_delete": self.edge.cross_account_delete,
            "clear_auth_cookie": self.edge.clear_auth_cookie,
            "delete_with_offline": self.edge.delete_with_offline,
            "browser_back_forward": self.edge.browser_back_forward,
        }
        # 断言 action：统一转发到 AssertionFlow
        self.assert_actions = {
            "assert_logged_in": self.assert_flow.assert_logged_in,
            "assert_guest": self.assert_flow.assert_guest,
            "assert_login_failed": self._assert_login_failed,
            "assert_category_count": self.assert_flow.assert_category_count,
            "assert_category_titles": self.assert_flow.assert_category_titles,
            "assert_product_detail": self._assert_product_detail,
            "assert_url_contains": self.assert_flow.assert_url_contains,
            "assert_add_success": self._assert_add_success,
            "assert_cart_count": self.assert_flow.assert_cart_count,
            "assert_cart_titles": self.assert_flow.assert_cart_titles,
            "assert_cart_total": self.assert_flow.assert_cart_total,
            "assert_cart_prices": self.assert_flow.assert_cart_prices,
            "assert_dialog_count": self.assert_flow.assert_dialog_count,
            "assert_cart_empty": self.assert_flow.assert_cart_empty,
            "assert_row_deleted": self.assert_flow.assert_row_deleted,
            "assert_row_kept": self.assert_flow.assert_row_kept,
            "assert_delete_persisted": self.assert_flow.assert_delete_persisted,
            "assert_api_cart_count": self.assert_flow.assert_api_cart_count,
            "assert_api_total": self.assert_flow.assert_api_total,
            "assert_api_contains_product": self._assert_api_contains_product,
            "assert_rows_equal_api": self.assert_flow.assert_rows_equal_api,
            # 异常 / 安全类断言
            "assert_fake_token_rejected": self._assert_fake_token_rejected,
            "assert_delete_idempotent": self._assert_delete_idempotent,
            "assert_not_found_response": self._assert_not_found_response,
            "assert_cross_account_protected": self._assert_cross_account_protected,
            "assert_delete_link_clickable": self._assert_delete_link_clickable,
            "assert_no_fake_delete": self._assert_no_fake_delete,
        }

    # ==================================================================
    # 执行入口
    # ==================================================================
    def execute(self, steps) -> Dict[str, object]:
        """按顺序执行 YAML 中的步骤列表（执行前做一次前置数据归一化）"""
        steps = self._normalize_precondition(steps)
        for idx, s in enumerate(steps, 1):
            action = s.get("action")
            params = {k: v for k, v in s.items() if k != "action"}
            desc = s.get("desc") or ""
            title = f"步骤{idx}：{desc or action}"
            with step(title):
                attach_json(f"步骤{idx} 参数", {"action": action, **params})
                self._dispatch(action, params)
        return self.results

    def _normalize_precondition(self, steps) -> list:
        """
        用例前置统一归一化：
        若用例涉及购物车断言但未显式声明 api_clear_cart，则自动插入一次清理，
        位置放在 ensure_login / login 之后（需要有 token 才能定位到账号的购物车），
        避免上一轮残留数据造成误判，也避免显式清理被重复执行。
        """
        acts = [s.get("action") for s in steps]
        if "api_clear_cart" in acts:
            return steps
        cart_related = {"open_cart", "add_to_cart", "add_to_cart_times",
                        "prepare_cart_api", "assert_cart_count", "assert_cart_empty",
                        "delete_first", "delete_by_title", "delete_all"}
        if not any(a in cart_related for a in acts):
            return steps
        # 游客态用例的购物车归属由 document.cookie 决定，与登录账号无关，不做清理
        if "assert_guest" in acts or "guest" in acts:
            return steps

        # 插到登录动作之后；无登录动作则放最前面
        anchor = max((i for i, a in enumerate(acts) if a in
                      ("ensure_login", "login", "login_ui")), default=-1)
        new_steps = list(steps)
        new_steps.insert(anchor + 1, {
            "action": "api_clear_cart",
            "desc": "前置归一化：清空购物车（用例未显式声明，自动补齐）",
        })
        log.info("自动补入前置清理，位置：第 %d 步", anchor + 2)
        return new_steps

    def _dispatch(self, action: str, params: dict):
        if action in self.actions:
            return self._call(self.actions[action], params, action)
        if action in self.assert_actions:
            return self._call(self.assert_actions[action], params, action)
        raise KeyError(
            f"未注册的 action `{action}`，可用：\n"
            f"  {sorted(list(self.actions) + list(self.assert_actions))}"
        )

    @staticmethod
    def _call(func: Callable, params: dict, action: str):
        """按函数签名过滤参数，避免 YAML 中多余的说明性字段导致 TypeError"""
        import inspect
        sig = inspect.signature(func)
        accepted = set(sig.parameters)
        kwargs = {k: v for k, v in params.items() if k in accepted}
        ignored = set(params) - set(kwargs)
        if ignored:
            log.debug("action %s 忽略参数：%s", action, ignored)
        return func(**kwargs)

    # ==================================================================
    # 具体封装（需要做参数转换或结果暂存的）
    # ==================================================================
    def _open_site(self, **_):
        self.flow.open_site()
        self.results["home_count"] = self.flow.ctx.get("home_product_count")

    def _login(self, username=None, password=None, **_):
        alert = self.flow.login(username, password)
        self.results["login_alert"] = alert
        return alert

    def _login_expect_failure(self, username=None, password=None, **_):
        alert = self.flow.login_ui_expect_failure(username or "", password or "")
        self.results["login_alert"] = alert
        return alert

    def _select_laptops(self, expect_count=6, **_):
        titles = self.flow.select_laptops(expect_count=int(expect_count))
        self.results["laptops_titles"] = titles
        return titles

    def _open_product(self, product, via_list=False, **_):
        data = self.flow.open_product(product, via_list=False)
        self.results["product"] = data
        return data

    def _open_product_via_list(self, product, expect_count=6, **_):
        self.flow.select_laptops(expect_count=int(expect_count))
        data = self.flow.open_product(product, via_list=True)
        self.results["product"] = data
        return data

    def _open_cart(self, expect_rows=None, **_):
        snap = self.flow.open_cart(None if expect_rows is None else int(expect_rows))
        self.results["cart"] = snap
        return snap

    def _add_to_cart(self, product, **_):
        msg = self.flow.add_to_cart(product)
        self.results["add_alert"] = msg
        return msg

    def _add_to_cart_times(self, product, times=3, **_):
        msgs = self.flow.add_to_cart_times(product, int(times))
        self.results["add_alerts"] = msgs
        return msgs

    def _add_products(self, products, **_):
        msgs = self.flow.add_products(list(products))
        self.results["add_alerts"] = msgs
        return msgs

    def _delete_by_title(self, title, **_):
        snap = self.flow.delete_by_title(title)
        self.results["cart"] = snap
        return snap

    # ---------------- 断言封装 ----------------
    def _assert_login_failed(self, expect=None, **_):
        alert = self.results.get("login_alert", "")
        self.assert_flow.assert_login_failed(alert, expect or settings.texts["wrong_password"])

    def _assert_product_detail(self, product=None, **_):
        data = self.results.get("product") or self.flow.ctx.get("product")
        if product:
            expected = settings.product(product)
            data = {"title": expected["title"], "price": expected["price"]}
        self.assert_flow.assert_product_detail(data)

    def _assert_add_success(self, guest=False, **_):
        guest = bool(guest)
        alerts = self.results.get("add_alerts")
        alert = alerts[-1] if alerts else self.results.get("add_alert", "")
        self.assert_flow.assert_add_success(alert, guest=guest)

    def _assert_api_contains_product(self, product, **_):
        self.assert_flow.assert_api_contains_product(product)

    # ---------------- 异常 / 安全类断言 ----------------
    def _assert_fake_token_rejected(self, expected=None, **_):
        expected = expected or settings.texts["token_malformed"]
        with step(f"断言：伪造 token 被拒绝（{expected}）"):
            body = self.edge.last_body
            assert isinstance(body, dict) and body.get("errorMessage"), \
                f"伪造 token 未被拒绝，响应：{body}"
            assert expected in str(body.get("errorMessage")), \
                f"鉴权错误文案不符，期望含「{expected}」，实际「{body}」"

    def _assert_delete_idempotent(self, **_):
        with step("断言：重复删除幂等（返回 Not found. 且数据已清空）"):
            resp = self.edge.replay_delete_result if hasattr(self.edge, "replay_delete_result") else None
            body = self.edge.last_body
            assert body, "重放删除未获得响应"
            msg = body.get("errorMessage") if isinstance(body, dict) else str(body)
            assert msg and settings.texts["item_not_found"] in msg, \
                f"重复删除响应不符，期望含「{settings.texts['item_not_found']}」，实际「{body}」"
            items = self.flow.api.view_cart()
            assert not items, f"删除后接口侧仍有 {len(items)} 条记录"

    def _assert_not_found_response(self, expected=None, **_):
        expected = expected or settings.texts["item_not_found"]
        with step(f"断言：非法 id 删除返回「{expected}」"):
            body = self.edge.last_body
            msg = body.get("errorMessage") if isinstance(body, dict) else str(body)
            assert msg and expected in msg, f"响应不符，期望含「{expected}」，实际「{body}」"

    def _assert_cross_account_protected(self, **_):
        with step("断言：跨账号删除被保护（B 的数据仍存在）"):
            # 重新构造一次并检查结果
            result = self.edge.cross_account_delete()
            assert result["b_after"] >= 1, \
                f"越权删除成功（B 的购物车被清空）：{result}"
            assert result["b_after"] == result["b_before"], \
                f"B 的记录数发生变化：{result}"

    def _assert_delete_link_clickable(self, **_):
        with step("断言：Delete 链接可见且可点击"):
            cart = self.flow.cart
            assert cart.delete_link_visible(0), "Delete 链接不可见"
            cursor = cart.delete_link_cursor(0)
            assert cursor == "pointer", f"Delete 链接光标异常：{cursor}（期望 pointer）"

    def _assert_no_fake_delete(self, **_):
        with step("断言：离线删除后不产生假删除（数据仍存在）"):
            self.page.reload(wait_until="load")
            self.page.wait_for_timeout(2000)
            rows = self.flow.cart.row_count()
            items = self.flow.api.view_cart()
            assert len(items) == 1, f"服务端数据异常，期望 1 条，实际 {len(items)} 条（疑似假删除）"
            assert rows <= 1, f"页面行数异常：{rows}"
