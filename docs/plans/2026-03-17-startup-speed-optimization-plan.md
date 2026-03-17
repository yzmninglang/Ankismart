# Ankismart Startup Speed Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不改变现有功能与页面结构的前提下，显著降低 Ankismart 冷启动到首窗口可见的时间，并建立可持续追踪的启动性能基线。

**Architecture:** 优化按“先测量、后削峰、再回归验证”的顺序推进。先在启动入口建立可读、可比的阶段性耗时数据，再优先移除首页不需要的重型顶层导入，最后把配置解密与更新检查等非关键路径进一步延后，确保收益可以被单独归因。

**Tech Stack:** Python 3.11, PyQt6, QFluentWidgets, pytest, Ruff, importtime, time.perf_counter.

---

## Scope

- 不新增启动页、Splash、托盘常驻逻辑。
- 不移除任何现有页面、导航项、导出方式、推送方式或 OCR/生成能力。
- 只优化“启动时何时加载什么”，不改变用户入口与功能语义。
- 每一轮优化都必须有独立测量结果，禁止多处同时改动导致无法归因。

## Current Evidence

- `import ankismart.ui.main_window` 采样约 `706ms`，重头在：
  - `src/ankismart/core/config.py`
  - `src/ankismart/ui/import_page.py`
  - `src/ankismart/ui/workers.py`
- 真正运行期 `load_config() + _apply_theme() + MainWindow(config)` 采样约 `109ms`，说明主要瓶颈在冷启动导入阶段而不是窗口构造本身。
- 当前首页链路把不属于首页首帧的能力一并提前导入了：
  - `workers.py` 顶层导入 `ApkgExporter`
  - `workers.py` 顶层导入 `AnkiConnectClient`
  - `workers.py` 顶层导入 `AnkiGateway`
  - `config.py` 顶层导入 `cryptography`
  - `app.py` 顶层导入 `httpx`

## Implementation Order

1. 先补启动测量，锁定真实瓶颈。
2. 先做 `workers/gateway/export` 链路的延迟导入。
3. 再做 `config/crypto` 链路的按需导入。
4. 再收口 `app.py` 顶层依赖与首帧后任务。
5. 每一轮都回归启动指标与关键功能测试。

### Task 1: Build A Repeatable Startup Baseline

**Files:**
- Modify: `src/ankismart/ui/app.py`
- Modify: `src/ankismart/core/logging.py`
- Test: `tests/test_window.py`
- Test: `tests/test_theme.py`

**Step 1: Add stage-based startup timing helpers**

```python
_STARTUP_TS: dict[str, float] = {}


def _mark_startup(stage: str) -> None:
    _STARTUP_TS[stage] = time.perf_counter()


def _startup_cost_ms(start: str, end: str) -> float:
    return round((_STARTUP_TS[end] - _STARTUP_TS[start]) * 1000, 2)
```

**Step 2: Mark the critical startup stages in `main()`**

```python
_mark_startup("main.enter")
app = QApplication(sys.argv)
_mark_startup("qapp.created")
config = load_config()
_mark_startup("config.loaded")
_apply_theme(config.theme)
_mark_startup("theme.applied")
window = MainWindow(config)
_mark_startup("window.created")
window.show()
_mark_startup("window.shown")
```

**Step 3: Emit a compact startup summary log once the window is shown**

```python
logger.info(
    "startup timing",
    extra={
        "event": "app.startup.timing",
        "qapp_ms": _startup_cost_ms("main.enter", "qapp.created"),
        "config_ms": _startup_cost_ms("qapp.created", "config.loaded"),
        "theme_ms": _startup_cost_ms("config.loaded", "theme.applied"),
        "window_ms": _startup_cost_ms("theme.applied", "window.created"),
        "show_ms": _startup_cost_ms("window.created", "window.shown"),
    },
)
```

**Step 4: Add/adjust a non-brittle test that startup timing hooks do not break main window creation**

```python
def test_main_window_can_still_be_created_with_startup_timing():
    window = MainWindow(config=AppConfig(language="zh", theme="light"))
    assert window.import_page is not None
```

**Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_window.py tests/test_theme.py -q
```

Expected: PASS, with no behavior regression in window/theme initialization.

**Step 6: Commit**

```bash
git add src/ankismart/ui/app.py src/ankismart/core/logging.py tests/test_window.py tests/test_theme.py
git commit -m "test: add startup timing baseline"
```

### Task 2: Remove Heavy Export And Gateway Imports From Homepage Startup Path

**Files:**
- Modify: `src/ankismart/ui/workers.py`
- Modify: `src/ankismart/ui/import_page.py`
- Modify: `src/ankismart/ui/result_page.py`
- Test: `tests/test_ui/test_workers.py`
- Test: `tests/test_ui/test_import_page_start_convert.py`
- Test: `tests/test_ui/test_result_page.py`

**Step 1: Replace top-level gateway/export imports with local loader helpers**

```python
def _load_apkg_exporter_class():
    from ankismart.anki_gateway.apkg_exporter import ApkgExporter
    return ApkgExporter


def _load_gateway_types():
    from ankismart.anki_gateway.client import AnkiConnectClient
    from ankismart.anki_gateway.gateway import AnkiGateway, UpdateMode
    return AnkiConnectClient, AnkiGateway, UpdateMode
```

**Step 2: Update workers to call these loaders only in code paths that actually export/push**

```python
ApkgExporterClass = _load_apkg_exporter_class()
exporter = ApkgExporterClass(...)
```

```python
AnkiConnectClientClass, AnkiGatewayClass, UpdateModeEnum = _load_gateway_types()
```

**Step 3: Ensure import-page startup path only depends on convert-related workers**

```python
from ankismart.ui.workers import BatchConvertWorker
```

If that import still drags in push/export code, split the module into smaller worker files and keep import-page bound only to convert workers.

**Step 4: Add tests proving delayed loaders are only invoked when the related action starts**

```python
def test_import_page_init_does_not_load_gateway(monkeypatch):
    calls = {"count": 0}

    monkeypatch.setattr(
        "ankismart.ui.workers._load_gateway_types",
        lambda: calls.__setitem__("count", calls["count"] + 1),
    )

    page = ImportPage(_make_main_window())

    assert calls["count"] == 0
```

**Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_ui/test_workers.py tests/test_ui/test_import_page_start_convert.py tests/test_ui/test_result_page.py -q
```

Expected: PASS, and import page / result page behavior remains unchanged.

**Step 6: Re-measure cold import**

Run:

```bash
uv run python -X importtime -c "import ankismart.ui.main_window" 2>&1
```

Expected: `ankismart.ui.workers` and `ankismart.ui.import_page` cumulative import time drops materially from the current baseline.

**Step 7: Commit**

```bash
git add src/ankismart/ui/workers.py src/ankismart/ui/import_page.py src/ankismart/ui/result_page.py tests/test_ui/test_workers.py tests/test_ui/test_import_page_start_convert.py tests/test_ui/test_result_page.py
git commit -m "refactor(ui): lazy load export and gateway dependencies"
```

### Task 3: Defer Crypto Dependency Until Encrypted Fields Are Actually Used

**Files:**
- Modify: `src/ankismart/core/config.py`
- Modify: `src/ankismart/core/crypto.py`
- Test: `tests/test_core/test_config.py`
- Test: `tests/test_core/test_logging.py`

**Step 1: Replace top-level crypto imports in config with a lazy accessor**

```python
def _get_crypto_functions():
    from ankismart.core.crypto import decrypt, encrypt
    return decrypt, encrypt
```

**Step 2: Call the accessor only when loading/saving encrypted fields**

```python
decrypt, _ = _get_crypto_functions()
value = decrypt(ciphertext)
```

```python
_, encrypt = _get_crypto_functions()
payload[field] = encrypt(str(value))
```

**Step 3: Keep backward compatibility for existing config files**

```python
if not isinstance(value, str) or not value.startswith(_ENCRYPTED_PREFIX):
    return value
```

**Step 4: Add tests proving plain config load does not require crypto side effects**

```python
def test_load_plain_config_without_touching_crypto(monkeypatch, tmp_path):
    touched = {"count": 0}

    monkeypatch.setattr(
        "ankismart.core.config._get_crypto_functions",
        lambda: touched.__setitem__("count", touched["count"] + 1),
    )

    config = load_config()

    assert config is not None
    assert touched["count"] == 0
```

**Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_core/test_config.py tests/test_core/test_logging.py -q
```

Expected: PASS, existing encrypted-field compatibility preserved.

**Step 6: Re-measure config import cost**

Run:

```bash
uv run python -X importtime -c "import ankismart.core.config" 2>&1
```

Expected: `ankismart.core.config` cumulative import time drops materially from the current baseline.

**Step 7: Commit**

```bash
git add src/ankismart/core/config.py src/ankismart/core/crypto.py tests/test_core/test_config.py tests/test_core/test_logging.py
git commit -m "refactor(config): lazy load crypto on encrypted field access"
```

### Task 4: Shrink The App Entrypoint And Keep Non-Critical Work Off The Critical Path

**Files:**
- Modify: `src/ankismart/ui/app.py`
- Modify: `src/ankismart/ui/main_window.py`
- Test: `tests/test_window.py`
- Test: `tests/test_theme.py`

**Step 1: Move top-level `httpx` import into the update-check code path**

```python
def _fetch_latest_github_release(*, timeout: float, proxy_url: str = "") -> tuple[str, str]:
    import httpx
```

**Step 2: Audit top-level imports in `app.py` and keep only startup-critical ones**

```python
from ankismart.ui.main_window import MainWindow
```

If needed, move this import closer to where the window is created so import cost stays attributable to the right stage.

**Step 3: Ensure secondary page bootstrap and update check remain strictly post-show**

```python
window.show()
QTimer.singleShot(0, lambda: _start_post_show_tasks(window))
```

Add logging around `_start_post_show_tasks()` to verify it never runs before `window.show()`.

**Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_window.py tests/test_theme.py -q
```

Expected: PASS, no behavior change in theme switching or page bootstrap.

**Step 5: Re-measure full entrypoint import**

Run:

```bash
uv run python -X importtime -c "import ankismart.ui.app" 2>&1
```

Expected: `ankismart.ui.app` cumulative import time is lower than the current baseline.

**Step 6: Commit**

```bash
git add src/ankismart/ui/app.py src/ankismart/ui/main_window.py tests/test_window.py tests/test_theme.py
git commit -m "refactor(app): keep startup critical path minimal"
```

### Task 5: Verify End-To-End Startup Gains And Guard Against Regression

**Files:**
- Modify: `tests/test_window.py`
- Modify: `docs/contributing.md`
- Modify: `README.md`

**Step 1: Add a lightweight startup smoke measurement for local regression tracking**

```python
def test_main_window_startup_smoke_budget():
    started = time.perf_counter()
    window = MainWindow(config=AppConfig(language="zh", theme="light"))
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms < 250
```

Keep the threshold conservative to avoid flaky CI failures.

**Step 2: Document how to measure startup locally**

```bash
uv run python -X importtime -c "import ankismart.ui.app" 2>&1
uv run ankismart
```

Document where to read the startup timing log and how to compare before/after.

**Step 3: Run final verification suite**

Run:

```bash
uv run pytest tests/test_core/test_config.py tests/test_ui/test_workers.py tests/test_ui/test_import_page_start_convert.py tests/test_ui/test_result_page.py tests/test_window.py tests/test_theme.py -q
```

Run:

```bash
uv run ruff check src/ankismart/ui/app.py src/ankismart/ui/main_window.py src/ankismart/ui/workers.py src/ankismart/core/config.py src/ankismart/core/crypto.py tests/test_window.py tests/test_theme.py tests/test_ui/test_workers.py tests/test_ui/test_import_page_start_convert.py tests/test_ui/test_result_page.py tests/test_core/test_config.py
```

Expected: all pass, with measurable startup reduction relative to baseline logs.

**Step 4: Commit**

```bash
git add tests/test_window.py docs/contributing.md README.md
git commit -m "docs: record startup measurement workflow"
```

## Risks

- `workers.py` 拆分或延迟导入时，容易影响 monkeypatch 目标路径，需要同步修正测试替身。
- `config.py` 延迟导入 `crypto` 时，容易误伤现有加密字段兼容逻辑，必须用真实配置样本回归。
- 启动性能测试若阈值太激进，容易在 CI 或不同机器上产生波动，预算值必须保守。

## Success Criteria

- 冷启动导入阶段累计耗时明显下降，重点模块 `ankismart.ui.main_window`、`ankismart.ui.import_page`、`ankismart.core.config` 均低于当前基线。
- `window.show()` 之前不再提前加载首页首帧不需要的导出、推送、网络客户端相关依赖。
- 启动时序日志可以稳定输出并用于后续回归比较。
- 现有导入、转换、生成、导出、推送、设置功能行为不变。
