# -*- coding: utf-8 -*-
"""
登录弹窗页面对象（#logInModal）
说明：DemoBlaze 登录是模态框而非独立页面，但仍单独抽为 Page Object，
      便于登录流程复用（POM 中的"组件对象"模式）
"""
from playwright.sync_api import Locator, TimeoutError as PWTimeoutError

from common.logger import get_logger
from config.settings import settings
from pages.base_page import BasePage

log = get_logger("login_modal")


class LoginModal(BasePage):
    """登录弹窗"""

    @property
    def modal(self) -> Locator:
        return self.page.locator("#logInModal")

    @property
    def username_input(self) -> Locator:
        return self.page.locator("#loginusername")

    @property
    def password_input(self) -> Locator:
        return self.page.locator("#loginpassword")

    @property
    def submit_button(self) -> Locator:
        return self.page.locator("#logInModal button[onclick='logIn()']")

    @property
    def close_button(self) -> Locator:
        return self.page.locator("#logInModal button:has-text('Close')")

    # ---------------- 动作 ----------------
    def wait_visible(self) -> "LoginModal":
        self.modal.wait_for(state="visible", timeout=self.timeout["implicit"])
        return self

    def fill_credentials(self, username: str, password: str) -> "LoginModal":
        self.fill(self.username_input, username, "Username")
        self.fill(self.password_input, password, "Password")
        return self

    def submit(self) -> "LoginModal":
        self.click(self.submit_button, "Log in 按钮")
        return self

    def close(self) -> "LoginModal":
        self.click(self.close_button, "Close 按钮")
        return self

    def dismiss_by_x(self) -> "LoginModal":
        self.click(self.page.locator("#logInModal .close"), "弹窗右上角 X")
        return self

    def login(self, username: str = None, password: str = None) -> str:
        """
        完整登录动作：填表 -> 提交 -> 等待结果
        返回 alert 文案（成功时为空串）

        站点行为：logIn() 成功后 location.reload()，失败则仅弹 alert 不导航。
        等待策略（三段式，规避 reload 与元素等待的竞争）：
          1) 短窗口 800ms 捕获失败 alert（alert 同步弹出，通常 <300ms 到达）
          2) 无 alert 则等 reload 完成（wait_for_load_state）
             注意：不能直接用 wait_for_function/wait_for 等元素，
             页面导航会销毁执行上下文，等待器会直接抛错而非继续重试
          3) reload 完成后再等导航栏 Welcome 文案出现
        """
        acc = settings.account
        username = username or acc["username"]
        password = password or acc["password"]
        before = self.dialog_count
        self.fill_credentials(username, password)
        self.click(self.submit_button, "Log in 按钮")

        # ---- 阶段一：失败分支的 alert 通常在点击后立刻弹出 ----
        waited = 0.0
        while waited < 0.8:
            if self.dialog_count > before:
                msg = self.last_dialog or ""
                log.info("登录失败 alert：%s", msg)
                return msg
            self.page.wait_for_timeout(80)
            waited += 0.08

        # ---- 阶段二：等 reload 完成 ----
        try:
            self.page.wait_for_load_state("domcontentloaded",
                                          timeout=self.timeout["navigation"])
        except PWTimeoutError:
            log.debug("等待 reload 超时，继续按成功分支探测")

        # ---- 阶段三：确认 Welcome 文案 ----
        try:
            self.page.wait_for_function(
                "() => { const e = document.querySelector('#nameofuser');"
                " return !!e && (e.textContent || '').trim().length > 0; }",
                timeout=self.timeout["implicit"],
                polling=150,
            )
        except Exception:  # noqa: BLE001
            if self.dialog_count > before:
                msg = self.last_dialog or ""
                log.info("登录失败 alert：%s", msg)
                return msg
            # 兜底：文案未取到但鉴权 Cookie 已写入，也视为成功
            if self._has_auth_cookie():
                log.warning("Welcome 文案未渲染，但已写入鉴权 Cookie，按登录成功处理")
                return ""
            raise
        log.info("登录成功：%s", username)
        return ""

    def _has_auth_cookie(self) -> bool:
        """检查站点鉴权 Cookie（tokenp_）是否存在，作为登录成功的辅助判据"""
        try:
            return any(c.get("name") == "tokenp_" for c in self.page.context.cookies())
        except Exception:  # noqa: BLE001
            return False

    # ---------------- 状态 ----------------
    def is_visible(self, locator: Locator = None, timeout: int = 2000) -> bool:
        if locator is None:
            locator = self.modal
        return super().is_visible(locator, timeout)

    def visible_fields(self) -> dict:
        return {
            "modal": self.is_visible(self.modal),
            "username": self.is_visible(self.username_input),
            "password": self.is_visible(self.password_input),
            "submit": self.is_visible(self.submit_button),
            "close": self.is_visible(self.close_button),
        }

    def password_input_type(self) -> str:
        return self.password_input.get_attribute("type") or ""
