#!/usr/bin/env bash
# ==============================================================================
# Allure 报告生成（单独使用）
# 用法：
#   ./scripts/allure_report.sh              # 生成静态报告到 reports/allure-report
#   ./scripts/allure_report.sh --open       # 生成后直接用浏览器打开
#   ./scripts/allure_report.sh --serve      # 起本地服务实时预览（临时目录）
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

RESULTS="reports/allure-results"
REPORT="reports/allure-report"

if ! command -v allure >/dev/null 2>&1; then
  echo "[!] 未找到 allure 命令"
  echo "    npm 安装（推荐，无需 Java）：npm install -g allure-commandline"
  echo "    或参考 requirements.txt 中的系统安装方式"
  exit 1
fi

if [ ! -d "${RESULTS}" ] || [ -z "$(ls -A "${RESULTS}" 2>/dev/null)" ]; then
  echo "[!] 结果目录为空：${RESULTS}"
  echo "    请先执行用例：./scripts/run.sh --no-report"
  exit 1
fi

case "${1:-}" in
  --serve)
    echo "[i] 临时服务预览（Ctrl+C 退出）..."
    allure serve "${RESULTS}"
    ;;
  --open)
    allure generate "${RESULTS}" -o "${REPORT}" --clean
    echo "[✓] 报告已生成：${REPORT}/index.html"
    allure open "${REPORT}"
    ;;
  *)
    allure generate "${RESULTS}" -o "${REPORT}" --clean
    echo "[✓] 报告已生成：${REPORT}/index.html"
    echo "    本地查看：allure open ${REPORT}"
    ;;
esac
