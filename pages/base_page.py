# -*- coding: utf-8 -*-
"""
POM 基类：所有 Page Object 的父类
封装：
- 页面导航 / 加载完成判定
- 元素定位与安全点击（滚动到视口再点，规避 demo 站点长列表点击失效）
- 原生 alert 的监听与断言（本站点大量使用 alert）
- 等待工具（networkidle / 元素数量 / URL）
- 失败时自动截图与页面快照
"""
from typing import List, Optional

from playwright.sync_api import Page, Locator, TimeoutError as PWTimeoutError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from common.allure_helper import attach_screenshot, attach_text, attach_json
from common.logger import get_logger
from config.settings import settings
from playwright.sync_api import expect

log = get_logger("base_page")


class BasePage:
    """页面对象基类，不做任何业务断言，只提供稳定的原子操作"""

    # 子类重写：页面特征元素（用于判定加载完成）
    URL_PATH: str = "/"

    def __init__(self, page: Page):
        self.page = page
        self.timeout = settings.timeout
        self._dialogs: List[str] = []
        self._dialog_types: List[str] = []
        # 监听原生弹窗：站点的登录失败/加购成功/鉴权失败均用 alert 反馈
        # 注意：同一 page 会被多个 Page Object 共享，监听器只注册一次，
        #       否则一个 alert 会被重复 accept（第二个必抛 already handled）
        if not getattr(page, "_demoblaze_dialog_bound", False):
            page.on("dialog", self._on_dialog)
            page._demoblaze_dialog_bound = True
            page._demoblaze_dialogs = self._dialogs
            page._demoblaze_dialog_types = self._dialog_types
        else:
            # 复用首个 Page Object 创建的共享列表，保证跨页面对象看到同一份 alert 记录
            self._dialogs = page._demoblaze_dialogs
            self._dialog_types = page._demoblaze_dialog_types

    # ------------------------------------------------------------------
    # Dialog
    # ------------------------------------------------------------------
    def _on_dialog(self, dialog) -> None:
        try:
            self._dialogs.append(dialog.message)
            self._dialog_types.append(dialog.type)
            log.info("捕获 %s：%s", dialog.type, dialog.message)
            dialog.accept()
        except Exception as exc:  # noqa: BLE001
            log.debug("dialog 处理异常（页面可能已关闭）：%s", exc)

    def clear_dialogs(self) -> None:
        self._dialogs.clear()
        self._dialog_types.clear()

    @property
    def dialog_count(self) -> int:
        return len(self._dialogs)

    @property
    def last_dialog(self) -> Optional[str]:
        return self._dialogs[-1] if self._dialogs else None

    def dialogs(self) -> List[str]:
        return list(self._dialogs)

    def wait_dialog(self, timeout: Optional[int] = None, since: int = 0) -> str:
        """等待新增 alert 出现并返回其文案（since 传入弹窗前已有的数量）"""
        limit = (timeout or self.timeout["alert"]) / 1000
        waited = 0.0
        step = 0.1
        while waited < limit:
            if self.dialog_count > since:
                msg = self.last_dialog or ""
                attach_text("Alert 文案", msg)
                return msg
            self.page.wait_for_timeout(int(step * 1000))
            waited += step
        raise AssertionError(
            f"等待 alert 超时（{timeout or self.timeout['alert']}ms），"
            f"已捕获：{self.dialogs() or '无'}"
        )

    def expect_dialog_contains(self, expected: str, timeout: Optional[int] = None,
                               since: int = 0) -> str:
        msg = self.wait_dialog(timeout=timeout, since=since)
        assert expected in msg, f"alert 文案不符，期望包含「{expected}」，实际「{msg}」"
        return msg

    # ------------------------------------------------------------------
    # 导航
    # ------------------------------------------------------------------
    def goto(self, url: str, wait: str = "domcontentloaded", retries: int = 2) -> "BasePage":
        """
        打开页面（带导航重试）
        :param retries: 导航超时后的重试次数。公共演示站实测约 20% 概率整站卡死 50s+，
                        无重试会让偶发服务端抖动被误判为功能失败

        wait 默认 domcontentloaded：本站点包含大量 CDN 图片/字体，等 load 会额外耗时 5~20s，
        而真正需要的 DOM 在 domcontentloaded 时已就绪，特征元素由各页面对象自行等待
        """
        log.info("打开页面：%s", url)
        last_exc: Optional[Exception] = None
        for attempt in range(1, retries + 2):
            try:
                self.page.goto(url, wait_until=wait, timeout=self.timeout["navigation"])
                self.wait_for_load()
                return self
            except PWTimeoutError as exc:
                last_exc = exc
                if attempt > retries:
                    break
                log.warning("导航超时（第 %d/%d 次），%s 后重试：%s",
                            attempt, retries + 1, "1.5s", url)
                self.page.wait_for_timeout(1500)
        assert last_exc is not None
        raise last_exc

    def open(self, path: str = "") -> "BasePage":
        return self.goto(settings.url(path))

    def reload(self, retries: int = 2) -> "BasePage":
        log.info("刷新页面")
        last_exc: Optional[Exception] = None
        for attempt in range(1, retries + 2):
            try:
                self.page.reload(wait_until="domcontentloaded",
                                 timeout=self.timeout["navigation"])
                self.wait_for_load()
                return self
            except PWTimeoutError as exc:
                last_exc = exc
                if attempt > retries:
                    break
                log.warning("刷新超时（第 %d/%d 次），准备重试", attempt, retries + 1)
                self.page.wait_for_timeout(1500)
        assert last_exc is not None
        raise last_exc

    def wait_for_load(self) -> "BasePage":
        """
        等待页面可用：DOM 就绪 + 关键元素可见
        注意：本站点存在持续轮询/XHR，networkidle 经常等到超时（实测 30s），
              因此不用 networkidle，改为等待 DOM 就绪后由各页面对象等待自己的特征元素
        """
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=self.timeout["navigation"])
        except PWTimeoutError:
            log.debug("domcontentloaded 等待超时，继续执行")
        return self

    def wait_network_quiet(self, timeout: int = 3000) -> "BasePage":
        """可选：短超时等待网络安静，仅用于对时序敏感的断言场景"""
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout)
        except PWTimeoutError:
            log.debug("networkidle 未在 %sms 内安静，忽略", timeout)
        return self

    @property
    def url(self) -> str:
        return self.page.url

    # def wait_url_contains(self, part: str, timeout: Optional[int] = None) -> None:
    #     self.page.wait_for_url(f"**{part}**", timeout=timeout or self.timeout["navigation"])
    def wait_url_contains(self, part: str,
                          timeout: Optional[int] = None,
                          wait_until: str = "domcontentloaded") -> None:
        """等待当前 URL 包含指定字符串。"""
        timeout_ms = timeout or self.timeout["navigation"]
        try:
            self.page.wait_for_url(
                lambda url: part in url,  # 纯包含判断，彻底绕开 glob 通配符陷阱
                timeout=timeout_ms,
                wait_until=wait_until,  # 不用 load，避免被慢资源拖垮
            )
        except PlaywrightTimeoutError as e:
            # 把当前真实 URL 打出来，一眼看出是没跳还是跳错了地方
            raise AssertionError(
                f"等待 URL 包含 '{part}' 超时（>{timeout_ms}ms），当前 URL 为：{self.page.url}"
            ) from e

    # ------------------------------------------------------------------
    # 定位与操作
    # ------------------------------------------------------------------
    @staticmethod
    def by_text(scope: Locator, text: str) -> Locator:
        """按文本在指定作用域内定位元素"""
        return scope.get_by_text(text, exact=True)

    def click(self, locator: Locator, label: str = "", force: bool = False) -> "BasePage":
        """
        安全点击：先滚动到视口中央再点
        原因：demo 站点商品卡片/购物车行较长，Chromium 合成点击坐标会被视口裁剪
        """
        target = locator.first
        target.wait_for(state="visible", timeout=self.timeout["implicit"])
        try:
            target.scroll_into_view_if_needed(timeout=3000)
        except Exception:  # noqa: BLE001
            pass
        log.info("点击：%s", label or "元素")
        target.click(force=force)
        return self

    def fill(self, locator: Locator, value: str, label: str = "") -> "BasePage":
        target = locator.first
        target.wait_for(state="visible", timeout=self.timeout["implicit"])
        log.info("输入 %s = %s", label or "字段", "*" * len(value) if "password" in (label or "").lower() else value)
        target.fill(value)
        return self

    def text_of(self, locator: Locator, default: str = "", timeout: int = 5000) -> str:
        """
        读取元素文本（只读动作，不做长超时等待）
        关键点：只等 attached 并读 textContent——
          · 空文本是合法结果（如空购物车的 #totalp），不该当成失败等满 30s
          · 只读操作不需要等 visible，避免隐藏元素拖慢整个用例
        """
        try:
            locator.first.wait_for(state="attached", timeout=timeout)
            return (locator.first.text_content() or "").strip()
        except PWTimeoutError:
            return default

    def texts_of(self, locator: Locator, timeout: int = 5000) -> List[str]:
        try:
            locator.first.wait_for(state="attached", timeout=timeout)
        except PWTimeoutError:
            return []
        return [(t or "").strip() for t in locator.all_text_contents()]

    def count(self, locator: Locator) -> int:
        return locator.count()

    def is_visible(self, locator: Locator, timeout: int = 3000) -> bool:
        try:
            locator.first.wait_for(state="visible", timeout=timeout)
            return True
        except PWTimeoutError:
            return False

    # ------------------------------------------------------------------
    # 等待
    # ------------------------------------------------------------------
    def wait_count(self, locator: Locator, expected: int,
                   timeout: Optional[int] = None) -> None:
        """轮询等待元素数量精确等于期望值"""
        limit = (timeout or self.timeout["assertion"]) / 1000
        waited = 0.0
        while waited < limit:
            if locator.count() == expected:
                return
            self.page.wait_for_timeout(200)
            waited += 0.2
        raise AssertionError(f"等待元素数量={expected} 超时，当前={locator.count()}")
    # def wait_count(self, locator: Locator, expected: int, timeout: Optional[int] = None) -> None:
    #     expect(locator).to_have_count(
    #         expected, timeout=timeout or self.timeout["assertion"]
    #     )

    def wait_text_contains(self, locator: Locator, expected: str,
                           timeout: Optional[int] = None) -> None:
        limit = (timeout or self.timeout["assertion"]) / 1000
        waited = 0.0
        while waited < limit:
            try:
                if expected in (locator.first.inner_text() or ""):
                    return
            except Exception:  # noqa: BLE001
                pass
            self.page.wait_for_timeout(200)
            waited += 0.2
        raise AssertionError(f"等待文本包含「{expected}」超时")

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------
    def capture(self, name: str = "页面截图") -> None:
        attach_screenshot(self.page, name)

    def attach_page_info(self) -> None:
        try:
            attach_json("页面信息", {"url": self.page.url, "title": self.page.title()})
        except Exception:  # noqa: BLE001
            pass
