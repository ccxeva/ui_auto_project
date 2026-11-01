#!/usr/bin/env bash
# ==============================================================================
# DemoBlaze 购物车 UI 自动化 - 一键执行脚本
#
# 用法：
#   ./scripts/run.sh                    # 全量执行 + 生成报告
#   ./scripts/run.sh -m P0              # 仅 P0 冒烟
#   ./scripts/run.sh --module 加入购物车  # 按模块
#   ./scripts/run.sh --ui-headed        # 有头调试
#   ./scripts/run.sh -k 0001 --no-report # 单条调试，跳过报告生成
# ==============================================================================
set -euo pipefail

# 定位项目根目录（脚本所在目录的上级）
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

RESULTS_DIR="reports/allure-results"
REPORT_DIR="reports/allure-report"

GEN_REPORT=1
PYTEST_ARGS=()

# 分离自定义开关与 pytest 参数
for arg in "$@"; do
  case "${arg}" in
    --no-report) GEN_REPORT=0 ;;
    *) PYTEST_ARGS+=("${arg}") ;;
  esac
done

echo "=============================================================="
echo " DemoBlaze UI 自动化"
echo " 项目目录 : ${ROOT_DIR}"
echo " 结果目录 : ${RESULTS_DIR}"
echo " 用例文件 : data/cart_cases.yaml"
echo "=============================================================="

# ---------- 0. 环境准备 ----------
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
mkdir -p "${RESULTS_DIR}" reports/logs
# 每次执行前清理上一轮结果，避免历史 attachment 干扰报告
rm -rf "${RESULTS_DIR}"/*.json "${RESULTS_DIR}"/*.txt "${RESULTS_DIR}"/*.html 2>/dev/null || true

if ! python3 -c "import pytest, playwright, allure, yaml, requests" 2>/dev/null; then
  echo "[i] 依赖缺失，正在安装 ..."
  pip3 install -q -r requirements.txt
  python3 -m playwright install chromium
fi

# ---------- 1. 执行用例 ----------
set +e
python3 -m pytest "${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"}"
EXIT_CODE=$?
set -e

echo "--------------------------------------------------------------"
if [ ${EXIT_CODE} -eq 0 ]; then
  echo "[✓] 用例全部通过"
else
  echo "[✗] 存在失败用例，exit=${EXIT_CODE}（若为缺陷复现类用例，属预期）"
fi

# ---------- 2. 生成 Allure HTML 报告 ----------
if [ ${GEN_REPORT} -eq 1 ]; then
  if command -v allure >/dev/null 2>&1; then
    echo "[i] 生成 Allure 报告 ..."
    allure generate "${RESULTS_DIR}" -o "${REPORT_DIR}" --clean
    echo "[✓] 报告已生成：${REPORT_DIR}/index.html"
    echo "    直接打开：allure open ${REPORT_DIR}"
  else
    echo "[!] 未检测到 allure 命令，跳过 HTML 报告生成"
    echo "    安装方式见 requirements.txt 注释；"
    echo "    已有结果目录可直接用：allure serve ${RESULTS_DIR}"
  fi
fi

exit ${EXIT_CODE}
