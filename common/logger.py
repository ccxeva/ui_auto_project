# -*- coding: utf-8 -*-
"""
统一日志模块
- 控制台彩色输出 + 文件按天滚动
- 每条日志带线程名/模块名，便于定位并发与来源
"""
import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "reports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_LEVEL_COLOR = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35m",
}
_RESET = "\033[0m"
_initialized = False


class ColorFormatter(logging.Formatter):
    def format(self, record):
        color = _LEVEL_COLOR.get(record.levelname, "")
        record.levelname_c = f"{color}{record.levelname:<7}{_RESET}"
        return super().format(record)


def _init_root():
    global _initialized
    if _initialized:
        return
    root = logging.getLogger("demoblaze")
    root.setLevel(logging.DEBUG)
    root.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(ColorFormatter(
        fmt="%(asctime)s %(levelname_c)s [%(threadName)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    log_file = LOG_DIR / f"run_{datetime.now():%Y%m%d}.log"
    fh = TimedRotatingFileHandler(log_file, when="midnight", backupCount=7, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s(%(filename)s:%(lineno)d): %(message)s"
    ))
    root.addHandler(fh)
    _initialized = True


def get_logger(name: str = "demoblaze") -> logging.Logger:
    _init_root()
    if not name.startswith("demoblaze"):
        name = f"demoblaze.{name}"
    return logging.getLogger(name)


log = get_logger("core")

if __name__ == "__main__":
    lg = get_logger("demo")
    lg.info("日志初始化成功")
    lg.warning("示例警告")
