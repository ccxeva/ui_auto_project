# -*- coding: utf-8 -*-
"""
商品详情页页面对象
覆盖：商品名 / 价格（含 *includes tax）/ 描述 / Add to cart 按钮
"""
from typing import Optional

from playwright.sync_api import Locator

from common.logger import get_logger
from pages.base_page import BasePage

log = get_logger("product_page")


class ProductPage(BasePage):
    """https://www.demoblaze.com/prod.html?idp_={id}"""

    URL_PATH = "/prod.html"

    @property
    def name(self) -> Locator:
        return self.page.locator("h2.name")

    @property
    def price(self) -> Locator:
        return self.page.locator("h3.price-container")

    @property
    def description(self) -> Locator:
        return self.page.locator("#more-information p")

    @property
    def product_image(self) -> Locator:
        return self.page.locator(".item-img, .product-image, #tbodyid img").first

    @property
    def add_to_cart_button(self) -> Locator:
        return self.page.locator("a:has-text('Add to cart')")

    # ---------------- 打开 ----------------
    def open_by_id(self, idp) -> "ProductPage":
        """按商品 ID 直接打开详情页（URL 直达，避免依赖列表顺序）"""
        origin = self.page.evaluate("location.origin")
        self.goto(f"{origin}/prod.html?idp_={idp}")
        return self.wait_loaded()

    def wait_loaded(self, timeout: Optional[int] = None) -> "ProductPage":
        """等待 h2.name 出现即视为详情页渲染完成"""
        self.name.wait_for(state="visible", timeout=timeout or self.timeout["implicit"])
        return self

    # ---------------- 读取 ----------------
    def title_text(self) -> str:
        return self.text_of(self.name)

    def price_text(self) -> str:
        return self.text_of(self.price)

    def price_value(self) -> int:
        """把 "$700 *includes tax" 解析为数字 700"""
        raw = self.price_text()
        digits = "".join(ch for ch in raw.split("*")[0] if ch.isdigit())
        return int(digits) if digits else 0

    def description_text(self) -> str:
        return self.text_of(self.description)

    def is_loaded(self) -> bool:
        return self.is_visible(self.name, timeout=5000)

    # ---------------- 加购 ----------------
    def add_to_cart(self) -> str:
        """
        点击 Add to cart 并返回 alert 文案
        站点行为：已登录 -> "Product added."；游客 -> "Product added"（无句号）
        """
        before = self.dialog_count
        self.click(self.add_to_cart_button, "Add to cart 按钮")
        return self.wait_dialog(since=before)

    def click_add_to_cart_no_wait(self) -> None:
        """只点击不等待（用于并发/重复点击场景）"""
        self.click(self.add_to_cart_button, "Add to cart 按钮（不等待弹窗）")

    def add_to_cart_times(self, times: int) -> list:
        """连续加购 N 次，返回每次的 alert 文案列表"""
        messages = []
        for i in range(times):
            before = self.dialog_count
            self.click(self.add_to_cart_button, f"第 {i + 1} 次点击 Add to cart")
            messages.append(self.wait_dialog(since=before))
        return messages

