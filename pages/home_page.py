# -*- coding: utf-8 -*-
"""
首页页面对象
覆盖：导航栏（登录/退出/购物车入口）、左侧分类筛选、商品卡片列表
"""
from typing import List, Optional

from playwright.sync_api import Locator, TimeoutError as PWTimeoutError

from common.logger import get_logger
from pages.base_page import BasePage

log = get_logger("home_page")


class HomePage(BasePage):
    """https://www.demoblaze.com/index.html"""

    URL_PATH = "/index.html"

    # ---------------- 定位器（CSS/文本混合，均为站点原生 id/class） ----------------
    @property
    def nav_login(self) -> Locator:
        return self.page.locator("#login2")

    @property
    def nav_logout(self) -> Locator:
        return self.page.locator("#logout2")

    @property
    def nav_user(self) -> Locator:
        """登录后导航栏显示的 Welcome xxx 文案（未登录时元素隐藏）"""
        return self.page.locator("#nameofuser")

    @property
    def nav_cart(self) -> Locator:
        return self.page.locator("#cartur")

    @property
    def nav_home(self) -> Locator:
        return self.page.locator("#navbarExample >> text=Home")

    @property
    def category_links(self) -> Locator:
        return self.page.locator("a#itemc")

    def category(self, name: str) -> Locator:
        """按分类名取左侧链接，如 Laptops / Phones / Monitors"""
        return self.page.locator("a#itemc", has_text=name)

    @property
    def product_cards(self) -> Locator:
        return self.page.locator("#tbodyid .card")

    @property
    def product_titles(self) -> Locator:
        return self.page.locator("#tbodyid .card-title a")

    # ---------------- 页面动作 ----------------
    def open_home(self) -> "HomePage":
        self.open("index.html")
        self.wait_cards_loaded()
        return self

    def wait_cards_loaded(self, timeout: Optional[int] = None,
                          retry_reload: bool = True) -> "HomePage":
        """
        等待商品卡片渲染完成（数据走 /entries AJAX，必须显式等待）
        公共环境 /entries 偶发无响应，导致首屏一直空白：
        超时后自动 reload 重试一次，避免偶发接口抖动被误判为功能缺陷
        """
        limit = timeout or self.timeout["implicit"]
        try:
            self.product_cards.first.wait_for(state="visible", timeout=limit)
        except PWTimeoutError:
            if not retry_reload:
                raise
            log.warning("首页商品列表未渲染（/entries 可能无响应），刷新重试一次")
            self.page.reload(wait_until="domcontentloaded",
                             timeout=self.timeout["navigation"])
            self.product_cards.first.wait_for(state="visible",
                                              timeout=self.timeout["navigation"])
        return self

    # ---------------- 登录入口 ----------------
    def open_login_modal(self) -> "HomePage":
        self.clear_dialogs()
        self.click(self.nav_login, "导航栏 LOG IN")
        self.page.locator("#logInModal").wait_for(state="visible",
                                                  timeout=self.timeout["implicit"])
        return self

    def logout(self) -> "HomePage":
        self.clear_dialogs()
        self.click(self.nav_logout, "导航栏 Log out")
        self.wait_for_load()
        return self

    # ---------------- 登录态查询 ----------------
    def is_logged_in(self) -> bool:
        """以"退出按钮可见"为登录态判据（登录后 LOG IN 隐藏、Log out 显示）"""
        return self.is_visible(self.nav_logout, timeout=2000)

    def welcome_text(self) -> str:
        return self.text_of(self.nav_user)

    def wait_logged_in(self, timeout: Optional[int] = None) -> str:
        """
        等待登录完成
        判据：#nameofuser 文本出现 "Welcome xxx"（登录成功后由 showMenu 填充）
        说明：
          · 不用 wait_for(visible) 等 #logout2——reload 后该元素由 jQuery ready 异步控制显隐
          · 先等 reload 完成：页面导航会销毁执行上下文，直接 wait_for_function 会抛错
        """
        limit = timeout or self.timeout["implicit"]
        try:
            self.page.wait_for_load_state("domcontentloaded",
                                          timeout=self.timeout["navigation"])
        except PWTimeoutError:
            log.debug("等待页面就绪超时，继续探测登录态")
        self.page.wait_for_function(
            "() => { const e = document.querySelector('#nameofuser');"
            " return !!e && (e.textContent || '').trim().length > 0; }",
            timeout=limit, polling=150,
        )
        text = self.welcome_text()
        log.info("登录态文案：%s", text)
        return text

    def login_state(self) -> dict:
        return {
            "logged_in": self.is_logged_in(),
            "welcome": self.welcome_text(),
            "login_visible": self.is_visible(self.nav_login, timeout=1000),
            "logout_visible": self.is_visible(self.nav_logout, timeout=1000),
        }

    # ---------------- 分类筛选 ----------------
    def select_category(self, name: str, expect_count: Optional[int] = None) -> "HomePage":
        """
        点击左侧分类并等待列表刷新
        :param expect_count: 期望商品数量，传入后用 JS 轮询确认列表已切换（避免读到旧列表）
        """
        self.click(self.category(name), f"左侧分类 {name}")
        if expect_count is not None:
            self.page.wait_for_function(
                "n => document.querySelectorAll('#tbodyid .card').length === n",
                arg=expect_count, timeout=self.timeout["implicit"],
            )
        else:
            self.wait_for_load()
        log.info("分类 %s 切换完成，当前商品数=%d", name, self.product_cards.count())
        return self

    def product_count(self) -> int:
        return self.product_cards.count()

    def product_titles_list(self) -> List[str]:
        return self.texts_of(self.product_titles)

    def product_prices(self) -> List[str]:
        return self.texts_of(self.page.locator("#tbodyid .card h5"))

    # ---------------- 进入详情 ----------------
    def open_product(self, title: str) -> "HomePage":
        """在列表中点击指定商品标题进入详情（会触发页面跳转）"""
        card = self.product_titles.filter(has_text=title).first
        self.click(card, f"商品卡片 {title}")
        self.wait_url_contains("prod.html")
        self.page.locator("h2.name").wait_for(state="visible",
                                             timeout=self.timeout["implicit"])
        return self

    # ---------------- 购物车入口 ----------------
    def open_cart(self) -> "HomePage":
        self.click(self.nav_cart, "导航栏 CART")
        self.wait_url_contains("cart.html")
        return self
