# -*- coding: utf-8 -*-
"""
异常 / 安全 / 接口型业务动作
把"接口直接调用 + 异常场景构造"从 CartFlow 中拆出来，保持主流程代码干净
"""
import time
import uuid
from typing import Optional

from common.allure_helper import attach_json, attach_table, step
from common.api_client import ApiClient
from common.logger import get_logger
from config.settings import settings
from flows.cart_flow import CartFlow

log = get_logger("edge_flow")
T = settings.texts


class EdgeFlow:
    """边界、异常、安全类场景（接口层构造 + UI 层验证）"""

    def __init__(self, flow: CartFlow, api: Optional[ApiClient] = None):
        self.flow = flow
        self.api = api or flow.api
        self.page = flow.page
        # API 层结果统一暂存，供后续断言 action 使用
        self.last_response = None
        self.last_body = None

    # ==================================================================
    # 非法 / 越权加购
    # ==================================================================
    def add_invalid_product(self, prod_id=9999) -> dict:
        """接口加购不存在的商品，返回响应信息"""
        with step(f"接口加购非法商品 prod_id={prod_id}"):
            resp = self.api.add_to_cart(prod_id)
            body = self.api._json_or_text(resp)
            self.last_response, self.last_body = resp, body
            result = {"status": resp.status_code, "body": body, "prod_id": str(prod_id)}
            attach_json("非法商品加购响应", result)
        return result

    def add_with_fake_token(self, cookie: str = "garbage_token_123") -> dict:
        """伪造 Cookie 调用加购接口"""
        with step(f"使用伪造 Cookie 加购：{cookie or '空串'}"):
            resp = self.api.add_to_cart(settings.product("macbook_air")["idp"],
                                        cookie=cookie, flag=True)
            body = self.api._json_or_text(resp)
            self.last_response, self.last_body = resp, body
            result = {"status": resp.status_code, "body": body, "cookie": cookie}
            attach_json("伪造 token 响应", result)
        return result

    # ==================================================================
    # 删除幂等 / 非法 id / 越权
    # ==================================================================
    def replay_delete(self) -> dict:
        """先删除一条记录，再用同一 id 重放删除请求"""
        with step("删除记录并重放同一请求（幂等性验证）"):
            items = self.api.view_cart()
            assert items, "购物车为空，无法执行删除幂等测试"
            target = items[0]["id"]
            first = self.api.delete_item(target)
            second = self.api.delete_item(target)
            result = {
                "item_id": target,
                "first": {"status": first.status_code, "body": self.api._json_or_text(first)},
                "replay": {"status": second.status_code, "body": self.api._json_or_text(second)},
            }
            self.last_response, self.last_body = second, result["replay"]["body"]
            attach_json("删除幂等结果", result)
        return result

    def delete_not_exist_id(self, times: int = 3) -> list:
        """用随机 UUID 反复调用删除接口"""
        responses = []
        with step(f"删除不存在的记录 id，共 {times} 次"):
            for i in range(int(times)):
                fake_id = str(uuid.uuid4())
                resp = self.api.delete_item(fake_id)
                body = self.api._json_or_text(resp)
                responses.append({"round": i + 1, "id": fake_id,
                                  "status": resp.status_code, "body": body})
            self.last_body = responses[-1]["body"]
            attach_table("非法 id 删除结果", ["#", "id", "status", "body"],
                         [[r["round"], r["id"], r["status"], r["body"]] for r in responses])
        return responses

    def cross_account_delete(self) -> dict:
        """
        越权删除：账号 B 产生购物车记录，用账号 A 的 token 删除 B 的条目
        返回 {item_id, b_items_before, delete_status, delete_body}
        """
        with step("构造跨账号删除场景（A 删 B 的记录）"):
            sec = settings.secondary_account
            b_api = ApiClient()
            r = b_api.ensure_account(sec["username"], sec["password"])
            assert r["ok"], f"副账号不可用：{r['body']}"
            b_api.clear_cart()
            b_api.add_to_cart(settings.product("macbook_air")["idp"])
            b_items = b_api.view_cart()
            assert b_items, "副账号加购失败，无法构造越权场景"
            target_id = b_items[0]["id"]

            # 用主账号 token 删除副账号条目
            a_token = self.api.token
            resp = self.api.delete_item_raw(target_id, a_token)
            body = self.api._json_or_text(resp)

            # 复查副本账号数据
            b_after = b_api.view_cart()
            result = {
                "target_item_id": target_id,
                "b_before": len(b_items),
                "delete_status": resp.status_code,
                "delete_body": body,
                "b_after": len(b_after),
            }
            self.last_body = body
            attach_json("越权删除结果", result)
            # 清理副账号，避免残留数据影响其他用例
            b_api.clear_cart()
        return result

    # ==================================================================
    # Cookie / 会话
    # ==================================================================
    def clear_auth_cookie(self) -> int:
        """
        清除登录 Cookie（tokenp_），模拟登录态失效
        关键补充：同时把游客标识 user 重置成新 UUID。
        原因：站点用 document.cookie 的 user 判定游客购物车归属，
              若沿用旧 user，会读到该访客历史遗留的购物车数据（公共环境会不断累积），
              导致"登录态失效后购物车应为空"的断言被无关数据干扰。
        返回值：被清理的鉴权 Cookie 数量
        """
        with step("清除登录 Cookie（模拟登录态失效）"):
            cookies = self.page.context.cookies()
            removed = [c for c in cookies if c["name"] in ("tokenp_", "user")]
            for c in removed:
                self.page.context.clear_cookies(name=c["name"])
            # 置入全新的游客标识，保证游客购物车从空开始
            fresh = str(uuid.uuid4())
            self.page.context.add_cookies([{
                "name": "user", "value": fresh,
                "domain": ".demoblaze.com", "path": "/",
            }])
            attach_json("Cookie 处理", {
                "removed": [c["name"] for c in removed],
                "guest_user_id": fresh,
            })
            self.page.wait_for_timeout(500)
        return len([c for c in removed if c["name"] == "tokenp_"])

    def get_auth_cookie(self) -> str:
        for c in self.page.context.cookies():
            if c["name"] == "tokenp_":
                return c["value"]
        return ""

    # ==================================================================
    # 网络异常 / 浏览器导航
    # ==================================================================
    def delete_with_offline(self) -> dict:
        """切离线后点击 Delete，再恢复网络，返回点击过程的状态"""
        with step("网络置为 Offline 后点击 Delete"):
            cart = self.flow.cart
            before_rows = cart.row_count()
            # 拦截所有请求模拟断网（比 CDP offline 更可控，便于恢复）
            self.page.route("**/*", lambda route: route.abort())
            try:
                link = cart.row_delete_links().first
                link.click(timeout=5000)
                self.page.wait_for_timeout(2000)
            except Exception as exc:  # noqa: BLE001 离线时点击超时属预期
                log.info("离线点击 Delete 异常（预期内）：%s", exc)
            finally:
                self.page.unroute("**/*")
            rows_after_click = cart.row_count()
            result = {"rows_before": before_rows, "rows_after_click": rows_after_click}
            attach_json("离线删除表现", result)
        return result

    def browser_back_forward(self) -> dict:
        """后退再前进，并等待购物车重新渲染"""
        with step("浏览器后退 → 前进，检查状态一致性"):
            self.page.go_back(wait_until="load")
            self.page.wait_for_timeout(1200)
            self.page.go_forward(wait_until="load")
            self.page.wait_for_timeout(1500)
            result = {"url": self.page.url, "rows": self.flow.cart.row_count()}
            attach_json("前进后退后状态", result)
        return result

    def wait_for_render(self, seconds: float = 1.5) -> None:
        time.sleep(seconds)
