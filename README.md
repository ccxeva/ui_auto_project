# DemoBlaze 购物车 UI 自动化测试框架

基于 **Pytest + Playwright + YAML + Allure** 的 UI 自动化工程，采用 **POM 三层分离**架构，
通过 YAML 数据驱动批量执行用例，Allure 定制化渲染 HTML 报告。

被测站点：<https://www.demoblaze.com>

---

## 一、架构设计：POM 三层分离

```
ui-automation/
├── config/                  # ── 配置层：环境、账号、商品、文案、超时 ──
│   ├── config.yaml          #    唯一数据源，禁止在代码里硬编码 URL/账号/价格
│   ├── settings.py          #    单例配置对象，支持环境变量覆盖
│   └── __init__.py
│
├── common/                  # ── 公共能力层：与被测页面无关的通用工具 ──
│   ├── logger.py            #    彩色控制台 + 按天滚动文件日志
│   ├── yaml_loader.py       #    YAML 加载 + ${变量} 替换 + 字段校验
│   ├── api_client.py        #    requests 封装，数据准备与三层断言交叉验证
│   ├── allure_helper.py     #    Allure 定制化：step/severity/表格附件/报文附件
│   └── scroll.py            #    滚动与坐标点击辅助
│
├── pages/                   # ── 页面层（Page Object）：只管"元素在哪、怎么点" ──
│   ├── base_page.py         #    基类：导航、点击、填充、alert 捕获、等待策略
│   ├── home_page.py         #    首页：登录入口、分类选择、商品卡片、购物车入口
│   ├── login_modal.py       #    登录弹窗（组件对象）
│   ├── product_page.py      #    商品详情页：标题、价格、Add to cart
│   └── cart_page.py         #    购物车页：行数据、总价、删除
│
├── flows/                   # ── 业务层：跨页面编排，不含选择器 ──
│   ├── cart_flow.py         #    购物车主业务：登录、选品、加购、查看、删除
│   ├── assertion_flow.py    #    三层断言：页面 / 接口 / 数据一致性
│   ├── edge_flow.py         #    边界与安全：非法商品、伪造 token、重放删除
│   └── step_executor.py     #    步骤驱动引擎：action 注册表 + 参数化分发
│
├── data/                    # ── 数据层：用例全部以声明式 YAML 描述 ──
│   └── cart_cases.yaml      #    31 条用例，31 个 action 组合成不同场景
│
├── testcases/               # ── 用例入口：薄壳，只做参数化与 Allure 元信息 ──
│   └── test_cart.py         #    3 个测试函数对应 3 个功能模块
│
├── reports/                 # ── 产出：Allure 结果、HTML 报告、运行日志 ──
├── run.py                   # ── Python 一键入口：执行 + 报告（跨平台推荐）──
├── scripts/run.sh           # ── shell 一键脚本（CI/Linux 备用）──
├── conftest.py              # ── 夹具与钩子：浏览器生命周期、参数化、失败截图 ──
├── pytest.ini
└── requirements.txt
```

### 三层职责边界

| 层 | 目录 | 职责 | 禁止事项 |
|---|---|---|---|
| **数据层** | `data/*.yaml` + `config/` | 用例步骤、输入数据、期望值、账号、商品 | 不出现任何 CSS 选择器与 Python 逻辑 |
| **业务层** | `flows/*.py` | 编排页面动作、组装业务语义（如"登录后加购两次"） | 不直接写 `page.locator(...)` |
| **页面层** | `pages/*.py` | 元素定位、单页面原子操作、页面状态读取 | 不写断言业务预期、不做跨页面流程 |

> 断言单独收敛在 `flows/assertion_flow.py`，便于统一维护三层校验口径。

---

## 二、数据驱动：YAML 声明式用例

`data/cart_cases.yaml` 的结构：

```yaml
variables:                       # 全局变量，可在任意字段用 ${xxx} 引用
  p_macbook_air: macbook_air
  price_air: 700

defaults:                        # 所有用例的默认值，单条可覆盖
  marker: "@data"
  account: primary
  enabled: true
  layer: UI
  feature: "电商系统"

cases:
  - id: MALL-CART-FUNC-0001
    title: "已登录状态在详情页点击 Add to cart，验证加购成功提示"
    module: "电商系统 → 购物车模块 → 加入购物车"
    priority: P0
    tags: [smoke, cart]
    account: primary             # 可覆盖 defaults
    steps:                       # 声明式动作序列
      - action: open_site
      - action: ensure_login
      - action: assert_logged_in
      - action: api_clear_cart   # 接口清空，保证起点干净
      - action: open_product
        product: ${p_macbook_air}
      - action: add_to_cart
        product: ${p_macbook_air}
      - action: assert_add_success
      - action: assert_url_contains
        expected: prod.html
      - action: assert_api_cart_count
        expected: 1
```

**变量替换规则**（`common/yaml_loader.py`）：

- 整串变量 `"${price_air}"` → 保留原始类型（`700` 是 int，不是 `"700"`）
- 内嵌变量 `"商品-${p_macbook_air}-详情"` → 拼接为字符串
- 支持多级嵌套引用

**步骤执行引擎**（`flows/step_executor.py`）：

- 49 个 action 分两族注册：`actions`（动作）与 `assert_actions`（断言）
- 每步自动包裹 `allure.step`，并把入参以 JSON 附件落盘，报告里可逐步回溯
- `_call()` 用 `inspect.signature` 过滤多余参数，YAML 里加 `desc: xxx` 不会报错

**新增用例只需改 YAML，无需动 Python 代码。**

---

## 三、用例覆盖

| 功能模块 | 用例数 | 优先级分布 |
|---|---|---|
| 电商系统 → 购物车模块 → 加入购物车 | 13 | P0×7 / P1×4 / P2×2 |
| 电商系统 → 购物车模块 → 删除记录 | 12 | P0×5 / P1×5 / P2×2 |
| 电商系统 → 主流程 → 登录到购物车删除 | 6 | P0×3 / P1×2 / P2×1 |
| **合计** | **31** | **P0×15 / P1×11 / P2×5** |

覆盖的场景类型：

- **正向主流程**：登录 → 选 Laptops → 详情 → 加购 → 购物车 → 删除
- **游客态**：未登录加购（用 `document.cookie` 归属）、登录后合并购物车
- **金额计算**：单件、多件、跨商品总价、重复加购累加
- **数据持久化**：删除后刷新、重新登录、换 context 后仍不恢复
- **并发隔离**：两个账号购物车互不可见、跨账号删除被拒绝
- **异常与安全**：非法 prod_id、伪造 token、删除已删记录、离线点击、重放删除请求
- **接口交叉验证**：UI 操作后调 `/viewcart` 核对服务端数据，三层断言闭环

> 部分用例（`tags: [defect]`）为**缺陷复现**用例，失败即为预期结果。
> 在 YAML 中标记 `expect_fail: true`，`conftest.py` 会自动打 `pytest.mark.xfail(strict=False)`，
> 报告中显示为 **xfail（预期失败）**，与真实失败区分开，不污染通过率统计。
> 缺陷修复后该用例会自动转为 passed，届时可移除该标记。

当前已知缺陷（`expect_fail: true`）：

| 用例编号 | 缺陷描述 | 级别 |
|---|---|---|
| `MALL-CART-FUNC-0012` | 加购接口未校验 `prod_id` 有效性，`prod_id=9999` 仍能写入脏数据 | P1 |
| `MALL-CARTDEL-FUNC-0009` | 删除接口未校验条目归属，账号 A 可删除账号 B 的购物车记录 | P1（越权） |

---

## 四、Allure 定制化渲染

`common/allure_helper.py` 提供的定制能力：

| 能力 | 实现 | 报告呈现 |
|---|---|---|
| 用例元信息 | `case_meta()` → `dynamic.feature/story/title` | Behaviors 视图按「功能 → 场景」两层树展示 |
| 优先级映射 | `P0→BLOCKER`、`P1→CRITICAL`、`P2→NORMAL`、`P3→MINOR` | 用例前显示红色/橙色/黄色/绿色级别标识 |
| 步骤嵌套 | `with step("...")` 包裹每个 action | 报告里逐级展开的步骤树，每步带耗时 |
| 用例摘要表 | `attach_table()` 生成 HTML 表格 | 用例详情顶部显示编号/优先级/模块/前置条件 |
| YAML 原文 | `attach_yaml_case()` | 附件可直接查看该用例的原始声明 |
| 接口报文 | `attach_api_exchange()` | 请求/响应 JSON + 耗时，定位问题不用翻日志 |
| 失败截图 | `pytest_runtest_makereport` 钩子 | 失败自动附全页截图 + 页面信息 + console 日志 |
| 环境信息 | `pytest_sessionstart` 写 `environment.properties` | 报告 Environment 区块显示浏览器/环境/站点 |

生成报告：

```bash
allure generate reports/allure-results -o reports/allure-report --clean
allure open reports/allure-report
```

---

## 五、快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium

# allure 命令行（HTML 报告生成必需）
brew install allure                                   # macOS
# 或 Linux：
# wget https://github.com/allure-framework/allure2/releases/download/2.32.0/allure-2.32.0.tgz
# tar -zxvf allure-2.32.0.tgz -C /opt/ && ln -s /opt/allure-2.32.0/bin/allure /usr/bin/allure
```

### 2. 执行

```bash
# ── 推荐：Python 一键入口（跨平台，Windows 可用）──
python run.py                            # 全量执行 + 生成报告
python run.py -m P0                      # 仅 P0 冒烟（参数原样透传给 pytest）
python run.py -k 0001 --no-report        # 单条调试，跳过报告
python run.py report                     # 只生成报告（不执行用例）
python run.py serve                      # 起本地服务实时预览（Ctrl+C 退出）

# ── 备选：shell 脚本（CI/Linux）──
./scripts/run.sh                         # 与 python run.py 等价

# ── 直接用 pytest ──
PYTHONPATH=. pytest                          # 全量 31 条
PYTHONPATH=. pytest -m P0                    # 仅 P0 冒烟
PYTHONPATH=. pytest -m "cart and P1"         # 加购模块且 P1
PYTHONPATH=. pytest -k "MALL-CART-FUNC-0001" # 按编号精确定位
PYTHONPATH=. pytest --module 删除记录         # 按模块（可多次指定）
PYTHONPATH=. pytest --priority P0 --tags smoke
PYTHONPATH=. pytest --ui-headed --ui-slowmo 500   # 有头 + 放慢，本地调试
```

### 3. 查看报告

```bash
python run.py serve                      # 临时起服务直接预览
python run.py report && allure open reports/allure-report
# 或原生命令：
allure generate reports/allure-results -o reports/allure-report --clean
allure open reports/allure-report
```

---

## 六、关键设计说明

### 1. 每个用例独立 `context`

站点用 Cookie `tokenp_` 判定购物车归属，若复用 context 会造成**测试间数据污染**。
`conftest.py` 中 `context` 夹具为 `scope="function"`，每个用例全新 context，用例结束即销毁。

### 2. 接口做数据准备，而非 UI 做前置

用例前置若用 UI 造数据，单条耗时会翻倍且不稳定。框架统一用 `api_client`：

- `api_clear_cart`：`/viewcart` 查列表 → 逐条 `/deleteitem`，1~2 秒完成
- `ensure_account`：`/login` 探测，账号不存在则 `/signup` 自动注册
- 用例结束不做清理，由下条用例的前置归一化，避免 teardown 失败掩盖真实断言

### 3. 等待策略：只等特征元素，不等 `networkidle`

站点存在持续轮询请求，`networkidle` 必定超时（曾导致单条 82 秒）。
现有策略：

- `goto(wait="domcontentloaded")` —— 只等 DOM 就绪
- 各 Page Object 等自己的特征元素（`#tbodyid .card`、`h2.name`、`#tbodyid tr`）
- 需要网络落定时用可控的 `wait_network_quiet(timeout=3000)`，而非无限等待

### 4. 登录的 reload 竞争

DemoBlaze 登录成功后 `location.reload()`，此时若直接 `wait_for(state="visible")` 会与导航竞争超时。
`LoginModal.login()` 改为 `expect_navigation` 包裹点击，导航完成后再判断：有 alert → 失败分支，无 alert → 成功分支。单步从 19 秒降到 7 秒。

### 5. alert 只注册一次监听

一个用例会实例化 4~5 个 Page Object，若每个都 `page.on("dialog")`，同一个 alert 会被重复 `accept()` 并抛
`Cannot accept dialog which is already handled`。现由首个 Page Object 注册，其余复用同一份列表。

### 6. 参数化在收集阶段拆分

三个测试函数若各自参数化全部 31 条，会收集出 94 条再靠运行时 skip。
现 `pytest_generate_tests` 读取 `metafunc.function.case_module`，**收集阶段**只注入对应模块的用例，实际收集 32 条（31 业务 + 1 说明）。

### 7. 公共环境的抗抖动设计

本站点为公开演示环境，实测约 20% 概率出现整站卡死 50s+ 的服务端抖动（与功能无关）。框架做三层容错：

- **页面导航**：`goto()` / `reload()` 超时自动重试 2 次
- **首页列表**：`wait_cards_loaded()` 检测 `/entries` 未响应时自动 reload 重试
- **接口调用**：`HTTPAdapter + Retry`（连接/读/5xx 各 3 次，指数退避）+ 应用层手动重试

出现集中性超时时，先确认站点可访问，再用 `pytest --lf` 重跑失败用例，不要直接判定为缺陷。

---

## 七、扩展指南

| 场景 | 操作 |
|---|---|
| 新增用例 | 只在 `data/cart_cases.yaml` 追加 `cases` 项，复用已有 action |
| 新增动作 | 在 `flows/step_executor.py` 的 `actions` 注册表加一行映射到 flow 方法 |
| 新增页面 | 在 `pages/` 新建类继承 `BasePage`，只写定位器与原子操作 |
| 换测试环境 | 改 `config/config.yaml` 的 `environments`，或用 `--env` 环境变量切 |
| 换测试账号 | `TEST_USER` / `TEST_PWD` 环境变量覆盖，或改 `config.yaml` 的 `accounts` |
| 换商品数据 | 改 `config.yaml` 的 `business.products`，YAML 里用 `${p_xxx}` 引用 |
