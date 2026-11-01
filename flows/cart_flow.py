# -*- coding: utf-8 -*-
"""
购物车业务流（登录 → 分类 → 详情 → 加购 → 购物车 → 删除）
特点：
1. 面向业务语义，不含断言逻辑（断言在 business/assertion 分离到 assertion_flow）
2. 每个动作都有日志与 Allure 步骤，报告可还原完整操作轨迹
3. 既支持"UI 操作"，也支持"接口数据准备"，用例可按需组合
"""
from typing import List, Optional

import allure

from common.allure_helper import attach_json, attach_table, step
from common.api_client import ApiClient
from common.logger import get_logger
from config.settings import settings
from pages.cart_page import CartPage
from pages.home_page import HomePage
from pages.login_modal import LoginModal
from pages.product_page import ProductPage

log = get_logger("cart_flow")


class CartFlow:
    """购物车相关业务编排"""

    def __init__(self, page, api: Optional[ApiClient] = None):
        self.page = page
        self.api = api or ApiClient()
        self.home = HomePage(page)
        self.login_modal = LoginModal(page)
        self.product = ProductPage(page)
        self.cart = CartPage(page)
        # 记录业务上下文，便于用例断言与报告展示
        self.ctx: dict = {}

    # ==================================================================
    # 导航与登录
    # ==================================================================
    def open_site(self) -> "CartFlow":
        with step("打开 DemoBlaze 首页"):
            self.home.open_home()
            self.ctx["home_product_count"] = self.home.product_count()
            attach_json("首页加载信息", {
                "url": self.home.url,
                "product_count": self.ctx["home_product_count"],
            })
        return self

    def login(self, username: Optional[str] = None, password: Optional[str] = None,
              auto_register: bool = True) -> str:
        """
        UI 登录，返回空串表示成功；失败返回 alert 文案
        auto_register=True 时先走接口确认账号存在（公共演示环境账号可能被清理），
        避免多账号切换场景因副账号不存在而失败
        """
        acc = settings.account
        username = username or acc["username"]
        password = password or acc["password"]
        with step(f"登录：{username}"):
            if auto_register and username != "guest" and password:
                with step(f"接口确认账号可用：{username}"):
                    prepared = self.api.ensure_account(username, password)
                    attach_json("账号准备结果", prepared)
                    assert prepared["ok"], f"账号 {username} 不可用：{prepared['body']}"
            self.home.open_login_modal()
            fields = self.login_modal.visible_fields()
            assert all(fields.values()), f"登录弹窗元素不完整：{fields}"
            msg = self.login_modal.login(username, password)
            if not msg:
                welcome = self.home.wait_logged_in()
                self.ctx["welcome_text"] = welcome
                attach_json("登录成功", self.home.login_state())
            else:
                attach_json("登录失败提示", {"alert": msg})
        return msg

    def ensure_login(self) -> "CartFlow":
        """
        保证处于登录态：
        账号可用性校验与自动注册已在 login() 内完成，此处只负责 UI 登录与结果断言
        """
        with step("确保登录态（账号校验 + UI 登录 + 导航栏断言）"):
            self.login()
            assert self.home.is_logged_in(), "UI 登录后未进入登录态"
            attach_json("登录态", self.home.login_state())
        return self

    def logout(self) -> "CartFlow":
        with step("退出登录"):
            self.home.logout()
            self.ctx["logged_in_after_logout"] = self.home.is_logged_in()
        return self

    def login_ui_expect_failure(self, username: str, password: str) -> str:
        """UI 登录失败场景：返回 alert 文案"""
        with step(f"以异常凭据登录（{username or '空'} / {password or '空'}）"):
            self.home.open_login_modal()
            msg = self.login_modal.login(username, password)
            attach_json("失败提示", {"alert": msg})
        return msg

    # ==================================================================
    # 分类与详情
    # ==================================================================
    def select_laptops(self, expect_count: int = 6) -> List[str]:
        with step("左侧分类选择 Laptops"):
            self.home.select_category("Laptops", expect_count=expect_count)
            titles = self.home.product_titles_list()
            self.ctx["laptops_titles"] = titles
            attach_table("Laptops 商品列表", ["序号", "商品标题"],
                         [[i + 1, t] for i, t in enumerate(titles)])
        return titles

    def open_product(self, key_or_idp, via_list: bool = False) -> dict:
        """
        打开商品详情
        :param key_or_idp: 配置中的商品 key（如 macbook_air）或 idp 数字
        :param via_list: True 走列表点击（验证列表跳转），False 走 URL 直达（更稳定）
        """
        p = settings.product(key_or_idp)
        with step(f"打开商品详情：{p['title']}（idp={p['idp']}）"):
            if via_list:
                self.home.open_product(p["title"])
            else:
                self.product.open_by_id(p["idp"])
            data = {
                "url": self.product.url,
                "title": self.product.title_text(),
                "price_text": self.product.price_text(),
                "price_value": self.product.price_value(),
            }
            self.ctx["product"] = data
            attach_json("详情页信息", data)
        return data

    # ==================================================================
    # 加入购物车
    # ==================================================================
    def add_to_cart(self, key_or_idp) -> str:
        """在详情页点击 Add to cart，返回 alert 文案"""
        p = settings.product(key_or_idp)
        with step(f"加入购物车：{p['title']}（${p['price']}）"):
            msg = self.product.add_to_cart()
            self.ctx.setdefault("add_messages", []).append(msg)
            attach_json("加购提示", {"product": p["title"], "alert": msg})
        return msg
    # def add_to_cart(self, key_or_idp) -> str:
    #     """在详情页点击 Add to cart，返回 alert 文案"""
    #     p = settings.product(key_or_idp)
    #     with step(f"加入购物车：{p['title']}（${p['price']}）"):
    #         msg = self.product.add_to_cart()
    #         if not msg:  # ① alert 没捕获到，立刻暴露
    #             raise AssertionError(f"加购未捕获到 alert，商品：{p['title']}")
    #         self.ctx.setdefault("add_messages", []).append(msg)
    #         attach_json("加购提示", {"product": p['title'], "alert": msg})
    #     return msg

    #
    def add_to_cart_times(self, key_or_idp, times: int) -> List[str]:
        p = settings.product(key_or_idp)
        with step(f"连续加购 {times} 次：{p['title']}"):
            msgs = self.product.add_to_cart_times(times)
            attach_table("连续加购结果", ["次数", "alert 文案"],
                         [[i + 1, m] for i, m in enumerate(msgs)])
            self.ctx["add_messages"] = msgs
        return msgs
    # def add_to_cart_times(self, key_or_idp, times: int) -> List[str]:
    #     p = settings.product(key_or_idp)
    #     with step(f"连续加购 {times} 次：{p['title']}"):
    #         msgs = self.product.add_to_cart_times(times)
    #
    #         missed = [i + 1 for i, m in enumerate(msgs) if not m]
    #         if missed:  # ② 定位哪一次点击失效
    #             raise AssertionError(
    #                 f"第 {missed} 次加购未捕获到 alert（共 {times} 次），商品：{p['title']}")
    #
    #         self.ctx.setdefault("add_messages", []).extend(msgs)  # ③ 统一累积语义
    #         attach_table("连续加购结果", ["次数", "alert 文案"],
    #                      [[i + 1, m] for i, m in enumerate(msgs)])
    #     return msgs

    def add_products(self, keys: List[str]) -> List[str]:
        """依次加购多个商品（每个商品都重新打开详情页，模拟真实路径）"""
        msgs = []
        for key in keys:
            self.open_product(key)
            msgs.append(self.add_to_cart(key))
        self.ctx["add_messages"] = msgs
        return msgs

    def add_to_cart_api(self, product, key_or_idp=None) -> None:
        """
        接口加购（数据准备），比 UI 快且稳定
        参数名兼容 product / key_or_idp 两种写法，避免 YAML 与签名不一致导致 TypeError
        """
        target = product if product is not None else key_or_idp
        assert target is not None, "add_to_cart_api 需要 product 参数（商品 key 或 idp）"
        p = settings.product(target)
        with step(f"接口预置加购：{p['title']}"):
            self.api.add_to_cart(p["idp"])
            attach_json("接口加购", {"prod_id": p["idp"], "title": p["title"]})

    # ==================================================================
    # 购物车
    # ==================================================================
    def open_cart(self, expect_rows: Optional[int] = None) -> dict:
        """
        进入购物车
        expect_rows=None 不校验行数；0 期望空车；N 期望 N 行
        """
        with step("进入购物车页面"):
            self.cart.open_cart(expect_rows=expect_rows)
            snap = self.cart.snapshot()
            self.ctx["cart"] = snap
            attach_table(
                "购物车快照",
                ["行数", "商品标题", "价格", "Total"],
                [[snap["row_count"], " / ".join(snap["titles"]) or "-",
                  " / ".join(snap["prices"]) or "-", snap["total_text"] or "0"]],
            )
        return snap

    def delete_first(self) -> dict:
        with step("删除购物车第 1 行记录"):
            before = self.cart.row_count()
            self.cart.delete_by_index(0)
            snap = self.cart.snapshot()
            self.ctx["delete"] = {"before": before, "after": snap["row_count"], "snapshot": snap}
            attach_json("删除结果", self.ctx["delete"])
        return snap

    def delete_by_title(self, title: str) -> dict:
        with step(f"删除购物车中的 {title}"):
            before = self.cart.row_count()
            self.cart.delete_by_title(title)
            snap = self.cart.snapshot()
            self.ctx["delete"] = {"before": before, "after": snap["row_count"], "snapshot": snap}
            attach_json("删除结果", self.ctx["delete"])
        return snap

    def delete_all(self) -> dict:
        with step("逐条删除全部购物车记录"):
            self.cart.delete_all()
            snap = self.cart.snapshot()
            self.ctx["delete"] = {"after": snap["row_count"], "snapshot": snap}
        return snap

    def refresh_cart(self) -> dict:
        with step("刷新购物车页面（验证持久化）"):
            self.cart.refresh_and_wait()
            self.cart.wait_rows(timeout=settings.timeout["cart_list"]) \
                if self.cart.row_count() else None
            snap = self.cart.snapshot()
            self.ctx["cart_after_refresh"] = snap
            attach_json("刷新后购物车", snap)
        return snap

    # ==================================================================
    # 接口侧校验
    # ==================================================================
    def api_cart_items(self) -> list:
        with step("接口查询购物车（服务端数据）"):
            items = self.api.view_cart()
            attach_table("接口侧购物车", ["#", "条目 id", "prod_id"],
                         [[i + 1, it.get("id"), it.get("prod_id")] for i, it in enumerate(items)])
            self.ctx["api_items"] = items
        return items

    def api_clear_cart(self) -> int:
        """接口清空购物车（前置数据准备）"""
        with step("接口清空购物车（前置数据准备）"):
            count = self.api.clear_cart()
            attach_json("清空购物车", {"deleted": count})
        return count

    def api_total(self, items: Optional[list] = None) -> int:
        return self.api.total_price(items if items is not None else self.api.view_cart())
