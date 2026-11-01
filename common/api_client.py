# -*- coding: utf-8 -*-
"""
接口客户端（requests 实现）
用途：
1. 测试数据准备：清空购物车、直接加购、注册测试账号——比 UI 操作快 10 倍且稳定
2. 接口层断言：验证 UI 操作后服务端数据是否真正落库（防"假删除""假加购"）
3. 与 UI 层形成交叉验证，报告中同时呈现 UI 断言与接口断言
"""
import base64
import time
import uuid
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from common.logger import get_logger
from config.settings import settings

log = get_logger("api_client")


class ApiClient:
    """DemoBlaze 接口封装（api.demoblaze.com）"""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 20):
        self.base_url = (base_url or settings.api_base_url).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Origin": settings.base_url,
            "Referer": settings.base_url + "/",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"),
        })
        # api.demoblaze.com 会主动关闭空闲的 keep-alive 连接，
        # 复用到已关闭的连接就会抛 RemoteDisconnected；挂载带重试的适配器从连接池层面兜住
        retry = Retry(
            total=3, connect=3, read=3, backoff_factor=0.6,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(["POST", "GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=10)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.token: Optional[str] = None
        self.username: Optional[str] = None

    # ---------------- 内部 ----------------
    @staticmethod
    def b64(password: str) -> str:
        """前端 b64EncodeUnicode 等价实现：UTF-8 -> Base64"""
        return base64.b64encode(password.encode("utf-8")).decode("ascii")

    def _post(self, path: str, payload: dict, retries: int = 3) -> requests.Response:
        """
        统一 POST
        公共演示环境偶发 RemoteDisconnected / 5xx 抖动，做有限重试（默认 3 次，指数退避）
        注意：仅对连接类错误与 5xx 重试，4xx 属于业务响应，不重试
        """
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                log.debug("POST %s %s（第 %d 次）", url, payload, attempt)
                resp = self.session.post(url, json=payload, timeout=self.timeout)
                log.debug("← %s %s", resp.status_code, resp.text[:300])
                if resp.status_code < 500:
                    return resp
                log.warning("接口 %s 返回 %s，准备重试", path, resp.status_code)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                log.warning("接口 %s 连接异常（第 %d/%d 次）：%s", path, attempt, retries, exc)
            if attempt < retries:
                time.sleep(0.6 * attempt)
        if last_exc is not None:
            raise last_exc
        return resp  # 全部返回 5xx 时把最后一次响应交回调用方

    @staticmethod
    def _json_or_text(resp: requests.Response) -> Any:
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # ---------------- 账号 ----------------
    def signup(self, username: str, password: str) -> dict:
        resp = self._post(settings.api_paths["signup"],
                          {"username": username, "password": self.b64(password)})
        body = self._json_or_text(resp)
        ok = not (isinstance(body, dict) and body.get("errorMessage"))
        log.info("注册 %s -> %s", username, "成功/已存在" if ok else body)
        return {"ok": ok, "body": body, "status": resp.status_code}

    def login(self, username: str, password: str) -> dict:
        """登录并保存 token（去掉 Auth_token: 前缀）"""
        resp = self._post(settings.api_paths["login"],
                          {"username": username, "password": self.b64(password)})
        body = self._json_or_text(resp)
        if isinstance(body, str) and body.startswith("Auth_token:"):
            self.token = body.replace("Auth_token:", "").strip()
            self.username = username
            log.info("登录成功：%s，token=%s", username, self.token)
            return {"ok": True, "token": self.token, "body": body, "status": resp.status_code}
        log.warning("登录失败：%s -> %s", username, body)
        return {"ok": False, "token": None, "body": body, "status": resp.status_code}

    def ensure_account(self, username: str, password: str) -> dict:
        """账号不存在时自动注册，保证用例可执行（公共演示环境常见）"""
        result = self.login(username, password)
        if result["ok"]:
            return result
        body = result["body"]
        if isinstance(body, dict) and body.get("errorMessage") == settings.texts["user_not_exist"]:
            log.info("账号 %s 不存在，自动注册", username)
            self.signup(username, password)
            result = self.login(username, password)
        return result

    # ---------------- 商品 ----------------
    def bycat(self, cat: str) -> list:
        resp = self._post(settings.api_paths["bycat"], {"cat": cat})
        body = self._json_or_text(resp)
        return body.get("Items", []) if isinstance(body, dict) else []

    def product_detail(self, idp) -> dict:
        resp = self._post(settings.api_paths["view"], {"idp": str(idp)})
        body = self._json_or_text(resp)
        return body if isinstance(body, dict) else {}

    # ---------------- 购物车 ----------------
    def add_to_cart(self, prod_id, token: Optional[str] = None, flag: bool = True,
                    cookie: Optional[str] = None) -> requests.Response:
        """加购；token 为空时使用当前登录态，cookie 可显式指定（游客态/异常场景）"""
        payload = {
            "id": str(uuid.uuid4()),
            "cookie": cookie if cookie is not None else (token or self.token or ""),
            "prod_id": str(prod_id),
            "flag": flag,
        }
        return self._post(settings.api_paths["add_to_cart"], payload)

    def view_cart(self, token: Optional[str] = None, flag: bool = True,
                  cookie: Optional[str] = None) -> list:
        payload = {
            "cookie": cookie if cookie is not None else (token or self.token or ""),
            "flag": flag,
        }
        body = self._json_or_text(self._post(settings.api_paths["view_cart"], payload))
        if isinstance(body, dict):
            return body.get("Items") or []
        return []

    def delete_item(self, item_id: str, token: Optional[str] = None) -> requests.Response:
        payload = {"id": item_id, "cookie": token or self.token or ""}
        return self._post(settings.api_paths["delete_item"], payload)

    def delete_item_raw(self, item_id: str, cookie: str) -> requests.Response:
        """显式指定 cookie，用于越权/非法 id 场景"""
        return self._post(settings.api_paths["delete_item"], {"id": item_id, "cookie": cookie})

    # ---------------- 组合操作（数据准备） ----------------
    def clear_cart(self, token: Optional[str] = None) -> int:
        """清空购物车，返回删除条数"""
        items = self.view_cart(token=token)
        for it in items:
            self.delete_item(it["id"], token=token)
        log.info("清空购物车，删除 %d 条", len(items))
        return len(items)

    def prepare_cart(self, products: list, token: Optional[str] = None) -> list:
        """按商品列表预置购物车，返回接口侧记录"""
        for p in products:
            self.add_to_cart(p["idp"], token=token)
        return self.view_cart(token=token)

    def total_price(self, items: list) -> int:
        """按 prod_id 反查商品价格求和（接口返回不含价格，需本地换算）"""
        mapping = {str(p["idp"]): p["price"] for p in settings.products.values()}
        return sum(mapping.get(str(it.get("prod_id")), 0) for it in items)


if __name__ == "__main__":
    api = ApiClient()
    acc = settings.account
    r = api.ensure_account(acc["username"], acc["password"])
    print("login:", r["ok"])
    if r["ok"]:
        print("cart:", len(api.view_cart()))
        api.add_to_cart(settings.product("macbook_air")["idp"])
        print("after add:", len(api.view_cart()), "total:", api.total_price(api.view_cart()))
        print("cleared:", api.clear_cart())
