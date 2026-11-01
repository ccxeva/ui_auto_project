# -*- coding: utf-8 -*-
"""
pages 包：页面对象层（POM）
只负责"页面元素 + 原子操作"，不包含业务流程与断言
"""
from pages.base_page import BasePage
from pages.home_page import HomePage
from pages.login_modal import LoginModal
from pages.product_page import ProductPage
from pages.cart_page import CartPage

__all__ = ["BasePage", "HomePage", "LoginModal", "ProductPage", "CartPage"]
