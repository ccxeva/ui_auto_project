# -*- coding: utf-8 -*-
"""
flows 包：业务层
把 Page Object 的原子操作编排为"业务动作"，是 YAML 步骤与页面对象之间的桥梁
三层分离体现：
    数据层 data/*.yaml  ->  业务层 flows/*  ->  页面层 pages/*
"""
from flows.cart_flow import CartFlow

__all__ = ["CartFlow"]
