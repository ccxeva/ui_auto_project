# -*- coding: utf-8 -*-
"""
Chromium 合成点击坐标会被视觉视口裁剪：当元素在滚动区域外时
Playwright 的 click 可能点空或报 "Element is outside of the viewport"。
这里显式滚动到元素中心，避免 demo 站点长列表 / 多行购物车的点击不稳定。
"""
import time
from playwright.sync_api import Page, Locator


def scroll_into_view(locator: Locator, block: str = "center") -> None:
    locator.first.evaluate("(el, block) => el.scrollIntoView({block, inline: 'center'})", block)
    time.sleep(0.1)


def click_center(page: Page, locator: Locator, force: bool = False) -> None:
    """滚动到元素后再点击，规避视口裁剪"""
    scroll_into_view(locator)
    locator.first.click(force=force)


def hover_center(locator: Locator) -> None:
    scroll_into_view(locator)
    locator.first.hover()
