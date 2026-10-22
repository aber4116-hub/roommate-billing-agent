# 阶段 2 报告：整数分摊引擎

- 状态：**已完成，等待用户验收后进入阶段 3**。
- 阶段 2 只实现领域层：金额解析、整数分摊、错误类型、单元/属性测试。
- 未实现数据库、API、前端、Agent；这些属于阶段 3–6。
- 用户已确认推荐方案：历史实收按个人已付贡献、账期修正采用重开 + 新修订、普通账单拒绝负数、入住天数为整数 0–31、确认工具不暴露给模型、保留旧版存档。

---

## 1. 本阶段目标

先在不依赖数据库、Web 框架或模型的前提下，把以下业务规则固化成可测试的纯 Python 代码：

1. 所有金额使用整数分；
2. 电费/水费按入住天数权重分摊；
3. 宽带/垃圾按户等权分摊；
4. 多出来的零头全部归规则指定的零头归属人（默认小周）；
5. 权重全为 0 时使用明确、可测试的均分备用规则；
6. 每笔账单分摊总额必须等于原始金额；
7. 不使用浮点数做金额运算；
8. 非法输入明确报错，不静默产生 NaN/丢钱。

---

## 2. 新增/修改文件

```text
pyproject.toml
uv.lock
.gitignore
src/roommate_billing/__init__.py
src/roommate_billing/domain/__init__.py
src/roommate_billing/domain/errors.py
src/roommate_billing/domain/money.py
src/roommate_billing/domain/allocation.py
tests/unit/test_money.py
tests/unit/test_allocation.py
tests/unit/test_allocation_properties.py
```

> `.venv/` 和缓存未提交；`uv.lock` 已生成，锁定开发依赖。

---

## 3. 实现说明

### 3.1 金额解析/格式化

- 内部金额一律 `int`，单位分。
- `parse_yuan_to_cents()`：
  - 接受 `0`、`12`、`12.3`、`12.34`；
  - 拒绝空值、指数、千分位、前导零、`.5`、`1.`、超过两位小数；
  - 普通金额默认拒绝负数；显式 `allow_negative=True` 才允许（冲正/引擎测试）；
  - 单笔上限 `100_000_000_000` 分（10 亿元）。
- `format_cents()` 输出 `¥1,234.56`/`-¥0.01`；`format_cents_plain()` 用于导出。
- `validate_cents()` 用于后续 API 边界，拒绝 `bool`/浮点/字符串/超范围。

### 3.2 分摊算法

```text
amount = abs(total_cents)
base_i = amount * weight_i // total_weight
leftover = amount - sum(base_i)
owner += leftover
```

- 只用 Python 整数除法和取余；
- 余数 `leftover < 人数`，全部加到 owner；
- 结果记录 `base_cents`、`remainder_cents`、`amount_cents`、`is_remainder_owner`、`fallback_used`；
- 每次计算后调用 `assert_conserved()`：
  - 每行 `amount == base + remainder`；
  - 所有行合计等于总额；
  - `base` 与 `remainder` 合计等于总额。
- 负数金额保留符号；普通账单 API 会拒绝负数，引擎仅用于冲正/测试。
- 零头归属人下标非法时**直接报错**，不静默回退到最后一人。
- 权重全 0 时使用均分 fallback；`fallback_used=True`，便于审计解释。
- `fallback` 只允许 `"equal"`；未知值报错。

### 3.3 错误类型

`DomainError` 下分层：

- `MoneyError` → `InvalidAmountError`/`AmountOutOfRangeError`
- `AllocationError` → `InvalidTotalError`/`EmptyWeightsError`/`InvalidWeightError`/`InvalidOwnerError`/`InvalidFallbackError`/`ConservationError`

错误带稳定 `code`，后续 API 可映射为错误响应，不依赖字符串匹配。

---

## 4. 固定样例结果

实测输出：

```text
电费 ['¥66.38', '¥110.63', '¥110.64']
水费 ['¥22.24', '¥37.07', '¥37.09']
宽带 ['¥29.66', '¥29.66', '¥29.68']
垃圾 ['¥6.66', '¥6.66', '¥6.68']
合计 ['¥124.94', '¥184.02', '¥184.09'] ¥493.05
```

对应整数分：

| 账单 | 小林 | 阿哲 | 小周 | 合计 |
|---|---:|---:|---:|---:|
| 电费 | 6638 | 11063 | 11064 | 28765 |
| 水费 | 2224 | 3707 | 3709 | 9640 |
| 宽带 | 2966 | 2966 | 2968 | 8900 |
| 垃圾 | 666 | 666 | 668 | 2000 |
| 个人合计 | 12494 | 18402 | 18409 | 49305 |

- 小周本账期分到的零头合计 7 分（电费 1 + 水费 2 + 宽带 2 + 垃圾 2）。
- 每笔账单逐项守恒。

---

## 5. 实际测试结果

环境：

- Python 3.12.14（DSH 内置解释器创建本地 `.venv`）
- uv 0.13.5
- pytest 9.1.1
- Hypothesis 6.170.5
- ruff 0.17.1

命令与结果：

```text
uv sync --frozen --extra dev
pytest -q
79 passed in 7.19s

ruff check .
All checks passed!

ruff format --check .
22 files already formatted

pip check
No broken requirements found.

python -m compileall -q src tests
compileall OK
```

### 5.1 测试覆盖范围

- 正常入住天数分摊；
- 按户平摊；
- 零头固定归 owner；
- 总额为 0；
- 权重全 0 的显式 fallback；
- 非法/负数/布尔/浮点权重；
- 非法 owner；
- 未知 fallback；
- 负数金额；
- 单人分摊；
- 1 分、2 分等极小余额；
- 多笔账单合计；
- 同一输入确定性；
- 单笔上限；
- 每笔守恒；
- Hypothesis 正数 5000 组、正负金额 1000 组随机输入；
- 金额解析/格式化的边界。

> 79 个测试用例，其中两个 Hypothesis 属性测试分别跑 5000/1000 个生成样例。测试用例数量不等于生成样例数量。

---

## 6. 已知限制

1. **没有数据库/API/UI/Agent**：本阶段只是领域层。
2. `split_cents` 接受任意非负整数权重；入住天数 `0–31` 的校验会在阶段 3/4 的 API 层做。
3. 引擎允许负数总额用于冲正/测试；普通账单 API 会拒绝负数。
4. 金额上限是单笔 10 亿元；多笔账单合计、账期总额上限在阶段 3 定义。
5. `format_cents` 当前只支持人民币符号 `¥`；多币种不在 v1。
6. 没有采集覆盖率；阶段 7 可加 `pytest-cov` 并纳入 CI。
7. 当前依赖通过 `uv.lock` 锁定；CI 尚未创建。
8. 许可证尚未选择；`LICENSE` 未创建。

---

## 7. 运行方式（Windows PowerShell）

本报告实际使用 DSH 内置 Python 3.12.14 的绝对路径创建 `.venv`，避免 Windows Store 的 `python` 别名。若 `python` 已安装并在 PATH 中，可用等价的 `python -m venv .venv`。

```powershell
# 本机实际执行的 venv 创建方式：使用已确认的 Python 3.12 解释器
& "<python-3.12-path>\python.exe" -m venv .venv

.\.venv\Scripts\python.exe -m pip install uv
.\.venv\Scripts\uv.exe sync --frozen --extra dev
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

注意：`uv sync --frozen` 默认不安装 `dev` extra；只跑测试时必须带 `--extra dev`，否则 pytest 会被移除。

Linux/macOS 将 `.venv\Scripts\` 换成 `.venv/bin/`。

---

## 8. 下一阶段开始条件

- 用户验收本报告和 79 个测试结果；
- 确认阶段 3 的范围：数据库模型、Alembic、账单/付款/结算服务与核心 API；
- 许可证仍待明确（不阻塞阶段 3 代码，但阻塞开源发布）。

阶段 3 **不会**直接开始，除非用户明确说继续。
