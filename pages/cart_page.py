# -*- coding: utf-8 -*-
"""
购物车页面对象
页面结构（实测）：
    #tbodyid tr.success  >>>  4 个 td：图片 | 标题 | 价格 | Delete 链接(onclick=deleteItem('<uuid>'))
    #totalp               >>>  Total 金额（空购物车时为 "")
"""
import re
from typing import List, Optional

from playwright.sync_api import Locator, TimeoutError as PWTimeoutError

from common.logger import get_logger
from pages.base_page import BasePage

log = get_logger("cart_page")

_UUID_IN_ONCLICK = re.compile(r"deleteItem\('([^']+)'\)")


class CartPage(BasePage):
    """https://www.demoblaze.com/cart.html"""

    URL_PATH = "/cart.html"

    # ---------------- 定位器 ----------------
    @property
    def rows(self) -> Locator:
        return self.page.locator("#tbodyid tr")

    @property
    def total(self) -> Locator:
        return self.page.locator("#totalp")

    @property
    def place_order_button(self) -> Locator:
        return self.page.locator("button:has-text('Place Order')")

    def row_titles(self) -> Locator:
        return self.page.locator("#tbodyid tr td:nth-child(2)")

    def row_prices(self) -> Locator:
        return self.page.locator("#tbodyid tr td:nth-child(3)")

    def row_delete_links(self) -> Locator:
        return self.page.locator("#tbodyid tr td:nth-child(4) a")

    def row_by_index(self, index: int) -> Locator:
        return self.rows.nth(index)

    def row_by_title(self, title: str) -> Locator:
        """按商品标题定位整行"""
        return self.page.locator("#tbodyid tr", has_text=title)

    # 购物车列表渲染完成信号：
    # 站点在 /viewcart 回调里逐条 append <tr>，全部处理完后才会给 #totalp 赋值。
    # 空车时永远没有 tr，因此不能用「有行」判定，统一用 JS 轮询：
    #   - 有行：行数达到期望
    #   - 无行：等待一个稳定的短窗口，确认确实没有数据
    _JS_ROW_COUNT = "() => document.querySelectorAll('#tbodyid tr').length"

    def open_cart(self, expect_rows: Optional[int] = None) -> "CartPage":
        """
        打开购物车页并等待列表渲染
        :param expect_rows: 期望行数；None 表示不校验
        cart.html 的 #totalp 是静态骨架节点，不能作为"渲染完成"判据；
        真正的信号是 #tbodyid 里出现 tr。
        期望 0 行时给 3s 稳定窗口：/viewcart 若返回空数组，tbody 会一直为空；
        若实际有残留数据则会被渲染出来，从而让后续断言能真实反映服务端状态。
        """
        origin = self.page.evaluate("location.origin")
        self.goto(f"{origin}/cart.html", wait="domcontentloaded")

        if expect_rows is None:
            self.page.wait_for_timeout(1200)
            return self

        timeout = self.timeout["cart_list"] if expect_rows else 3000
        try:
            # 单次 wait_for_function 内部轮询，比 Python 侧循环 evaluate 快一个量级
            self.page.wait_for_function(
                "n => document.querySelectorAll('#tbodyid tr').length === n",
                arg=expect_rows,
                timeout=timeout,
                polling=150,
            )
        except PWTimeoutError:
            if expect_rows:
                raise AssertionError(
                    f"购物车行数未达期望 {expect_rows}（当前 {self.row_count()}），"
                    f"标题={self.titles()}"
                ) from None
            # 空车期望未达：不抛错，交给后续 assert_cart_empty 给出更明确的断言信息
            log.warning("期望空车但检测到 %d 行，交由断言环节判定", self.row_count())
        return self

    def wait_rows(self, expected: Optional[int] = None,
                  timeout: Optional[int] = None) -> "CartPage":
        """等待购物车行数达到期望值（expected=None 时仅等待首行出现）"""
        limit = timeout or self.timeout["cart_list"]
        if expected is None:
            self.rows.first.wait_for(state="visible", timeout=limit)
        else:
            self.wait_count(self.rows, expected, timeout=limit)
        return self

    def wait_empty(self, timeout: Optional[int] = None) -> "CartPage":
        """
        等待购物车为 0 行
        空车场景无需长超时（/viewcart 返回空数组时 tbody 立即保持为空），
        默认只给 3s 稳定窗口，避免空车判定白等 cart_list 全时长
        """
        limit = (timeout or 3000) / 1000
        waited, stable = 0.0, 0
        while waited < limit:
            n = self.page.evaluate(self._JS_ROW_COUNT)
            if n == 0:
                stable += 1
                if stable >= 2:
                    return self
            else:
                stable = 0
            self.page.wait_for_timeout(200)
            waited += 0.2
        raise AssertionError(
            f"等待购物车为空超时，当前 {self.rows.count()} 行，Total='{self.total_text()}'"
        )

    # ---------------- 读取 ----------------
    def row_count(self) -> int:
        return self.rows.count()

    def titles(self) -> List[str]:
        return self.texts_of(self.row_titles())

    def prices(self) -> List[str]:
        return self.texts_of(self.row_prices())

    def price_values(self) -> List[int]:
        result = []
        for p in self.prices():
            digits = "".join(ch for ch in p if ch.isdigit())
            result.append(int(digits) if digits else 0)
        return result

    def total_text(self) -> str:
        return self.text_of(self.total)

    def total_value(self) -> int:
        """Total 解析为整数；空购物车返回 0"""
        raw = self.total_text()
        digits = "".join(ch for ch in raw if ch.isdigit())
        return int(digits) if digits else 0

    def row_ids(self) -> List[str]:
        """从 Delete 链接的 onclick 中解析购物车条目 UUID（删除接口需要此 ID）"""
        html = self.page.eval_on_selector_all(
            "#tbodyid tr td:nth-child(4) a", "els => els.map(e => e.getAttribute('onclick') || '')"
        )
        ids = []
        for snippet in html:
            m = _UUID_IN_ONCLICK.search(snippet)
            ids.append(m.group(1) if m else "")
        return ids

    def first_row_id(self) -> str:
        ids = self.row_ids()
        return ids[0] if ids else ""

    def snapshot(self) -> dict:
        """购物车快照，用于报告附件与断言（Total 只读一次，避免重复等待）"""
        total = self.total_text()
        digits = "".join(ch for ch in total if ch.isdigit())
        return {
            "row_count": self.row_count(),
            "titles": self.titles(),
            "prices": self.prices(),
            "total_text": total,
            "total_value": int(digits) if digits else 0,
            "row_ids": self.row_ids(),
        }

    # ---------------- 删除 ----------------
    def delete_by_index(self, index: int = 0) -> "CartPage":
        """删除第 index 行（默认首行），等待列表刷新"""
        before = self.row_count()
        target = self.page.locator("#tbodyid tr td:nth-child(4) a").nth(index)
        self.click(target, f"第 {index + 1} 行 Delete")
        if before > 0:
            self.wait_count(self.rows, before - 1, timeout=self.timeout["cart_list"])
        else:
            self.page.wait_for_timeout(800)
        log.info("删除第 %d 行后剩余 %d 行", index + 1, self.row_count())
        return self

    def delete_by_title(self, title: str) -> "CartPage":
        """按商品标题删除对应行（多商品删除中间行场景）"""
        before = self.row_count()
        link = self.row_by_title(title).locator("td:nth-child(4) a").first
        self.click(link, f"删除 {title}")
        self.wait_count(self.rows, before - 1, timeout=self.timeout["cart_list"])
        return self

    def delete_all(self) -> "CartPage":
        """循环删除直至购物车为空"""
        guard = 0
        while self.row_count() > 0 and guard < 20:
            self.delete_by_index(0)
            guard += 1
        self.wait_empty()
        return self

    def refresh_and_wait(self) -> "CartPage":
        """刷新并等待数据重新拉取（验证删除/加购是否真正落库）"""
        self.page.reload(wait_until="load", timeout=self.timeout["navigation"])
        self.page.wait_for_timeout(1500)
        return self

    # ---------------- 其他 ----------------
    def is_empty(self) -> bool:
        return self.row_count() == 0

    def delete_link_visible(self, index: int = 0) -> bool:
        try:
            return self.row_delete_links().nth(index).is_visible()
        except PWTimeoutError:
            return False

    def delete_link_cursor(self, index: int = 0) -> str:
        return self.row_delete_links().nth(index).evaluate(
            "el => getComputedStyle(el).cursor"
        )
