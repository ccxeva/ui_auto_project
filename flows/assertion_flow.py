# -*- coding: utf-8 -*-
"""
断言业务层：把"可量化预期"封装为可复用断言动作
设计原则：一条断言 = 一个明确的失败信息，失败时报告里能直接看出期望值 vs 实际值
"""
from typing import Iterable, Optional

from common.allure_helper import attach_json, attach_table, step
from common.logger import get_logger
from config.settings import settings
from flows.cart_flow import CartFlow

log = get_logger("assert_flow")
T = settings.texts


class AssertionFlow:
    """页面层 / 接口层 / 数据层三层断言"""

    def __init__(self, flow: CartFlow):
        self.flow = flow
        self.home = flow.home
        self.cart = flow.cart
        self.product = flow.product

    # ------------------------------------------------------------------
    # 登录态
    # ------------------------------------------------------------------
    def assert_logged_in(self) -> None:
        """
        断言登录态
        主判据取 Welcome 文案（#nameofuser 文本），辅以 LOG IN 入口消失；
        不以 #logout2 可见性为主判据——该元素显隐由 jQuery ready 异步控制，存在瞬时不同步
        """
        with step("断言：已处于登录态"):
            self.home.wait_logged_in()
            state = self.home.login_state()
            attach_json("登录态", state)
            assert state["welcome"], f"登录后 Welcome 文案为空：{state}"
            assert T["login_success_prefix"] in state["welcome"], \
                f"Welcome 文案异常，实际：{state['welcome']}"
            assert not state["login_visible"], f"登录后仍显示 LOG IN：{state}"

    def assert_guest(self) -> None:
        with step("断言：处于未登录游客态"):
            assert not self.home.is_logged_in(), "当前仍为登录态，未正确退出"
            assert self.home.is_visible(self.home.nav_login, timeout=3000), "游客态未显示 LOG IN"

    def assert_login_failed(self, alert: str, expect_text: str) -> None:
        with step(f"断言：登录失败提示「{expect_text}」"):
            assert alert, "登录失败场景未出现 alert 提示"
            assert expect_text in alert, f"提示文案不符，期望含「{expect_text}」，实际「{alert}」"

    # ------------------------------------------------------------------
    # 分类 / 详情
    # ------------------------------------------------------------------
    def assert_category_count(self, expected: int) -> None:
        with step(f"断言：商品数量 = {expected}"):
            actual = self.home.product_count()
            assert actual == expected, f"商品数量不符，期望 {expected}，实际 {actual}"

    def assert_category_titles(self, expected_titles: Iterable[str]) -> None:
        with step("断言：商品标题与数据源一致"):
            actual = self.home.product_titles_list()
            expect = list(expected_titles)
            attach_table("标题比对", ["#", "期望", "实际"],
                         [[i + 1, e, a] for i, (e, a) in enumerate(zip(expect, actual))])
            assert actual == expect, f"商品列表不符\n期望：{expect}\n实际：{actual}"

    def assert_product_detail(self, product: dict) -> None:
        with step(f"断言：详情页与配置一致（{product['title']}）"):
            assert product["title"] == self.product.title_text(), \
                f"标题不符：期望「{product['title']}」，实际「{self.product.title_text()}」"
            assert self.product.price_value() == product["price"], \
                f"价格不符：期望 {product['price']}，实际 {self.product.price_value()}"
            assert "*includes tax" in self.product.price_text(), \
                f"价格缺少 *includes tax 文案，实际：{self.product.price_text()}"

    def assert_url_contains(self, part: str) -> None:
        with step(f"断言：URL 包含「{part}」"):
            assert part in self.product.url, f"URL 不含「{part}」，实际：{self.product.url}"

    # ------------------------------------------------------------------
    # 加购
    # ------------------------------------------------------------------
    def assert_add_success(self, alert: str, guest: bool = False) -> None:
        key = "add_to_cart_success_guest" if guest else "add_to_cart_success"
        expect = T[key]
        with step(f"断言：加购提示含「{expect}」"):
            assert alert, "加购后未出现 alert 提示"
            assert expect in alert, f"提示不符，期望含「{expect}」，实际「{alert}」"

    def assert_cart_count(self, expected: int) -> None:
        with step(f"断言：购物车行数 = {expected}"):
            actual = self.cart.row_count()
            assert actual == expected, f"购物车行数不符，期望 {expected}，实际 {actual}"

    def assert_cart_titles(self, expected: Iterable[str], ordered: bool = False) -> None:
        """
        断言购物车商品标题
        :param ordered: True 严格校验顺序；False（默认）只校验内容多重集
        说明：站点新加购的商品插在列表最前（倒序展示），
              多数用例只关心"有哪些商品"，顺序由专门用例覆盖，故默认有序无关
        """
        expect = list(expected)
        title = "断言：购物车商品标题" + ("与顺序正确" if ordered else "集合正确")
        with step(title):
            actual = self.cart.titles()
            if ordered:
                assert actual == expect, f"购物车商品或顺序不符\n期望：{expect}\n实际：{actual}"
            else:
                from collections import Counter
                assert Counter(actual) == Counter(expect), (
                    f"购物车商品不符\n期望：{expect}\n实际：{actual}"
                )
            attach_json("购物车标题断言", {"expected": expect, "actual": actual,
                                          "ordered": ordered})

    def assert_cart_total(self, expected: int) -> None:
        with step(f"断言：购物车 Total = {expected}"):
            actual = self.cart.total_value()
            assert actual == expected, f"Total 不符，期望 {expected}，实际 {actual}（原文「{self.cart.total_text()}」）"

    def assert_cart_prices(self, expected: Iterable[int], ordered: bool = False) -> None:
        """
        断言购物车明细价格
        :param ordered: True 严格校验顺序；False（默认）只校验金额多重集
        说明：与标题断言保持一致口径——站点按加购时间倒序展示
        """
        expect = [int(x) for x in expected]
        title = "断言：购物车明细价格" + ("与顺序正确" if ordered else "集合正确")
        with step(title):
            actual = self.cart.price_values()
            if ordered:
                assert actual == expect, f"购物车价格或顺序不符\n期望：{expect}\n实际：{actual}"
            else:
                from collections import Counter
                assert Counter(actual) == Counter(expect), (
                    f"购物车价格不符\n期望：{expect}\n实际：{actual}"
                )
            attach_json("购物车价格断言", {"expected": expect, "actual": actual,
                                          "ordered": ordered})

    def assert_dialog_count(self, expected: int) -> None:
        with step(f"断言：alert 弹窗次数 = {expected}"):
            actual = self.product.dialog_count
            assert actual == expected, f"弹窗次数不符，期望 {expected}，实际 {actual}"

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------
    def assert_cart_empty(self) -> None:
        with step("断言：购物车为空"):
            # 给 /viewcart 一个收敛窗口，避免刚进页面就读到尚未渲染完成的中间态
            try:
                self.cart.wait_empty(timeout=3000)
            except AssertionError:
                pass  # 确实有数据时由下方断言给出更完整的现场信息
            count = self.cart.row_count()
            total = self.cart.total_value()
            attach_json("空购物车状态", {"rows": count, "total": total,
                                        "titles": self.cart.titles()})
            assert count == 0, f"购物车应为空，实际 {count} 行：{self.cart.titles()}"
            assert total == 0, f"购物车为空但 Total 不为 0：{total}"

    def assert_row_deleted(self, title: str) -> None:
        with step(f"断言：{title} 已从购物车移除"):
            titles = self.cart.titles()
            assert title not in titles, f"期望 {title} 被删除，实际仍在：{titles}"

    def assert_row_kept(self, title: str) -> None:
        with step(f"断言：{title} 仍保留在购物车"):
            titles = self.cart.titles()
            assert title in titles, f"期望 {title} 保留，实际列表：{titles}"

    def assert_delete_persisted(self, expected_rows: int) -> None:
        """删除后刷新页面，验证服务端已删除（防"假删除"）"""
        with step("断言：刷新后删除结果仍生效（服务端已删除）"):
            snap = self.flow.refresh_cart()
            assert snap["row_count"] == expected_rows, \
                f"刷新后行数不符，期望 {expected_rows}，实际 {snap['row_count']}"

    # ------------------------------------------------------------------
    # 接口层断言
    # ------------------------------------------------------------------
    def assert_api_cart_count(self, expected: int) -> None:
        with step(f"断言：接口侧购物车条数 = {expected}"):
            items = self.flow.api_cart_items()
            assert len(items) == expected, f"接口条数不符，期望 {expected}，实际 {len(items)}"

    def assert_api_total(self, expected: int) -> None:
        with step(f"断言：接口侧金额合计 = {expected}"):
            items = self.flow.api_cart_items()
            total = self.flow.api_total(items)
            assert total == expected, f"接口金额不符，期望 {expected}，实际 {total}"

    def assert_api_contains_product(self, key_or_idp) -> None:
        p = settings.product(key_or_idp)
        with step(f"断言：接口侧存在商品 {p['title']}（prod_id={p['idp']}）"):
            items = self.flow.api_cart_items()
            prod_ids = [str(it.get("prod_id")) for it in items]
            assert str(p["idp"]) in prod_ids, f"接口侧未找到 prod_id={p['idp']}，实际 {prod_ids}"

    def assert_rows_equal_api(self) -> None:
        """UI 行数与接口条数一致（双重校验，防前端渲染偏差）"""
        with step("断言：UI 行数与接口条数一致"):
            ui = self.cart.row_count()
            items = self.flow.api_cart_items()
            assert ui == len(items), f"UI {ui} 行 ≠ 接口 {len(items)} 条"
