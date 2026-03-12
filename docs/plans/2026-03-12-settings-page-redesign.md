# Settings Page Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 重写设置页为“顶部概览 + 分区锚点 + 单页卡片流”的官方风格，同时保留当前所有设置、连接测试、自动保存和维护功能。

**Architecture:** 保留 `SettingsPage` 的业务逻辑、配置保存和 worker 生命周期，只重构 UI 组装层。通过拆分 `settings_page.py` 中的大型 `_init_layout()`，引入 header、anchor bar 和 section builder，尽量复用现有对象名与行为，减少测试与调用面破坏。

**Tech Stack:** PyQt6, QFluentWidgets, pytest, Ruff

---

### Task 1: 为新布局建立失败测试

**Files:**
- Modify: `tests/test_ui/test_settings_page_provider_ui.py`
- Modify: `tests/test_ui/test_settings_page_config.py`
- Modify: `tests/test_ui/test_settings_page_connectivity.py`

**Step 1: Write the failing test**

补充以下断言：
- 设置页存在顶部概览容器和锚点导航容器
- 分区顺序为 `LLM -> Anki -> OCR -> Network/Language -> Cache/Experimental -> Maintenance`
- 原有功能控件对象仍可访问，例如 `_provider_table`、`_ocr_mode_combo`、`_proxy_mode_combo`

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui/test_settings_page_provider_ui.py tests/test_ui/test_settings_page_config.py tests/test_ui/test_settings_page_connectivity.py -q --maxfail=1`

Expected: FAIL，提示新 header/anchor 或 section 结构不存在。

**Step 3: Write minimal implementation**

仅添加最小结构骨架：
- header 容器
- anchor bar 容器
- 统一的 section 顺序骨架

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui/test_settings_page_provider_ui.py tests/test_ui/test_settings_page_config.py tests/test_ui/test_settings_page_connectivity.py -q --maxfail=1`

Expected: PASS 或仅剩后续布局断言失败。

**Step 5: Commit**

```bash
git add tests/test_ui/test_settings_page_provider_ui.py tests/test_ui/test_settings_page_config.py tests/test_ui/test_settings_page_connectivity.py src/ankismart/ui/settings_page.py
git commit -m "test(ui): cover settings page redesign structure"
```

### Task 2: 重构页面骨架与 section 组织

**Files:**
- Modify: `src/ankismart/ui/settings_page.py`

**Step 1: Write the failing test**

补充测试覆盖：
- 旧的 `Other` 混合区被拆分后，操作卡片移动到底部维护区
- 语言/代理/日志级别不再与更新/备份/重置混组

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui/test_settings_page_provider_ui.py::test_other_group_stays_at_bottom -q`

Expected: FAIL，旧分组命名或顺序与新设计不匹配。

**Step 3: Write minimal implementation**

在 `settings_page.py` 中：
- 拆分 `_init_layout()` 为 header、anchor、LLM、Anki、OCR、network/language、cache/experimental、maintenance section builders
- 保留原控件对象名
- 让 section 添加顺序固定

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui/test_settings_page_provider_ui.py -q --maxfail=1`

Expected: PASS

**Step 5: Commit**

```bash
git add src/ankismart/ui/settings_page.py tests/test_ui/test_settings_page_provider_ui.py
git commit -m "refactor(ui): reorganize settings page sections"
```

### Task 3: 实现顶部概览区

**Files:**
- Modify: `src/ankismart/ui/settings_page.py`
- Test: `tests/test_ui/test_settings_page_config.py`

**Step 1: Write the failing test**

补充测试：
- 页面存在概览标题、副标题
- 概览区可显示当前 provider / Anki URL / OCR mode / 版本摘要

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui/test_settings_page_config.py -q --maxfail=1`

Expected: FAIL，概览区字段不存在。

**Step 3: Write minimal implementation**

在 `SettingsPage` 中新增：
- `_build_page_overview()`
- `_refresh_page_overview()`

并在 `_load_config()`、`retranslate_ui()`、`update_theme()` 后刷新概览。

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui/test_settings_page_config.py -q --maxfail=1`

Expected: PASS

**Step 5: Commit**

```bash
git add src/ankismart/ui/settings_page.py tests/test_ui/test_settings_page_config.py
git commit -m "feat(ui): add settings page overview header"
```

### Task 4: 实现锚点导航与滚动联动

**Files:**
- Modify: `src/ankismart/ui/settings_page.py`
- Test: `tests/test_ui/test_settings_page_provider_ui.py`

**Step 1: Write the failing test**

补充测试：
- 锚点按钮存在
- 点击锚点会触发滚动到目标 section

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui/test_settings_page_provider_ui.py -q --maxfail=1`

Expected: FAIL，锚点区未创建或未绑定滚动。

**Step 3: Write minimal implementation**

新增：
- `_build_anchor_bar()`
- `_scroll_to_section(section_key)`

通过 `ensureWidgetVisible()` 或滚动条目标值完成导航，不引入复杂动画。

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui/test_settings_page_provider_ui.py -q --maxfail=1`

Expected: PASS

**Step 5: Commit**

```bash
git add src/ankismart/ui/settings_page.py tests/test_ui/test_settings_page_provider_ui.py
git commit -m "feat(ui): add settings page anchor navigation"
```

### Task 5: 收口 OCR / Network / Maintenance 视觉与交互细节

**Files:**
- Modify: `src/ankismart/ui/settings_page.py`
- Modify: `tests/test_ui/test_settings_page_config.py`
- Modify: `tests/test_ui/test_settings_page_connectivity.py`

**Step 1: Write the failing test**

补充测试：
- OCR 本地/云折叠行为在新 section 下仍正确
- 代理输入与模式切换布局仍满足现有要求
- 更新、备份、恢复、导出日志仍位于维护 section 且可触发原逻辑

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui/test_settings_page_config.py tests/test_ui/test_settings_page_connectivity.py -q --maxfail=1`

Expected: FAIL，新的布局或 section 组织尚未兼容旧行为断言。

**Step 3: Write minimal implementation**

修正：
- OCR section 的动态折叠和高度控制
- proxy 行的左右布局
- maintenance section 中操作卡片的顺序和命名

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui/test_settings_page_config.py tests/test_ui/test_settings_page_connectivity.py -q --maxfail=1`

Expected: PASS

**Step 5: Commit**

```bash
git add src/ankismart/ui/settings_page.py tests/test_ui/test_settings_page_config.py tests/test_ui/test_settings_page_connectivity.py
git commit -m "fix(ui): preserve settings workflows in redesigned layout"
```

### Task 6: 全量验证与清理

**Files:**
- Modify: `src/ankismart/ui/settings_page.py`
- Modify: `tests/test_ui/test_settings_page_provider_ui.py`
- Modify: `tests/test_ui/test_settings_page_config.py`
- Modify: `tests/test_ui/test_settings_page_connectivity.py`

**Step 1: Run focused test suite**

Run: `uv run pytest tests/test_ui/test_settings_page_provider_ui.py tests/test_ui/test_settings_page_config.py tests/test_ui/test_settings_page_connectivity.py -q --maxfail=1`

Expected: PASS

**Step 2: Run non-E2E regression**

Run: `uv run pytest tests --ignore=tests/e2e -q --maxfail=1`

Expected: PASS

**Step 3: Run lint**

Run: `uv run ruff check src tests`

Expected: All checks passed

**Step 4: Final cleanup**

如有必要，仅做命名、样式和重复代码清理，不改行为。

**Step 5: Commit**

```bash
git add src/ankismart/ui/settings_page.py tests/test_ui/test_settings_page_provider_ui.py tests/test_ui/test_settings_page_config.py tests/test_ui/test_settings_page_connectivity.py
git commit -m "feat(ui): redesign settings page with overview and anchors"
```
