# -*- coding: utf-8 -*-
"""
config 包：统一加载 config.yaml，提供全局只读配置对象
用法：
    from config.settings import settings
    settings.base_url
    settings.timeout["alert"]
    settings.product("macbook_air")
"""
import os
from pathlib import Path
from copy import deepcopy

import yaml

# 项目根目录（config 的上一级）
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT_DIR / "config" / "config.yaml"


class Settings:
    """配置单例，全局共享，避免各处重复读取 yaml"""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self, config_path: Path = CONFIG_FILE):
        if self._loaded:
            return
        self.root_dir = ROOT_DIR
        with open(config_path, "r", encoding="utf-8") as f:
            self._raw = yaml.safe_load(f)

        # 环境变量覆盖激活环境，便于 CI 切换
        self.env = os.getenv("TEST_ENV", self._raw.get("env", "demo"))
        self._loaded = True

    # ---------------- 基础属性 ----------------
    @property
    def raw(self) -> dict:
        return deepcopy(self._raw)

    @property
    def env_config(self) -> dict:
        envs = self._raw["environments"]
        if self.env not in envs:
            raise KeyError(f"config.yaml 中不存在环境 `{self.env}`，可选：{list(envs)}")
        return envs[self.env]

    @property
    def base_url(self) -> str:
        return os.getenv("BASE_URL", self.env_config["base_url"]).rstrip("/")

    @property
    def api_base_url(self) -> str:
        return os.getenv("API_BASE_URL", self.env_config["api_base_url"]).rstrip("/")

    @property
    def browser(self) -> dict:
        return self._raw["browser"]

    @property
    def timeout(self) -> dict:
        return self._raw["timeout"]

    @property
    def accounts(self) -> dict:
        return self._raw["accounts"]

    @property
    def account(self) -> dict:
        """主测试账号"""
        acc = dict(self.accounts["primary"])
        acc["username"] = os.getenv("TEST_USER", acc["username"])
        acc["password"] = os.getenv("TEST_PWD", acc["password"])
        return acc

    @property
    def secondary_account(self) -> dict:
        return dict(self._raw["accounts"]["secondary"])

    @property
    def business(self) -> dict:
        return self._raw["business"]

    @property
    def texts(self) -> dict:
        return self._raw["business"]["texts"]

    @property
    def api_paths(self) -> dict:
        return self._raw["business"]["api_paths"]

    @property
    def report(self) -> dict:
        return self._raw["report"]

    @property
    def data(self) -> dict:
        return self._raw["data"]

    @property
    def case_file(self) -> Path:
        return self.root_dir / self._raw["data"]["case_file"]

    # ---------------- 业务快捷方法 ----------------
    @property
    def products(self) -> dict:
        return self._raw["business"]["products"]

    def product(self, key: str) -> dict:
        """按 key 取商品信息，key 也可直接传 idp_ 数字"""
        products = self.products
        if key in products:
            return products[key]
        for p in products.values():
            if str(p["idp"]) == str(key):
                return p
        raise KeyError(f"未知商品 `{key}`，可选：{list(products)}")

    def url(self, path: str = "/") -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def product_url(self, idp) -> str:
        return self.url(f"prod.html?idp_={idp}")

    def api_url(self, key: str) -> str:
        return f"{self.api_base_url}{self.api_paths[key]}"


settings = Settings()

if __name__ == "__main__":
    print("env:", settings.env)
    print("base_url:", settings.base_url)
    print("api:", settings.api_url("login"))
    print("product:", settings.product("macbook_air"))
    print("alert timeout:", settings.timeout["alert"])
