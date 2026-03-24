from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from ankismart.core.task_models import TaskStage, TaskStatus, build_default_task_run
from ankismart.ui.task_center import TaskCenterPanel

_APP = QApplication.instance() or QApplication(sys.argv)


def test_task_center_renders_stage_statuses() -> None:
    panel = TaskCenterPanel()
    task = build_default_task_run(flow="full_pipeline", task_id="task-1")
    task.stages = [TaskStage(name="convert", status=TaskStatus.COMPLETED, progress=100)]

    panel.render_task(task)

    assert len(panel._task_widgets) == 1
    assert "task-1" in panel._task_widgets


def test_task_center_running_status_uses_theme_accent(monkeypatch) -> None:
    monkeypatch.setattr("ankismart.ui.task_center.get_theme_accent_text_hex", lambda **_: "#123456")

    assert "#123456" in TaskCenterPanel._status_style(TaskStatus.RUNNING)


def test_task_center_update_theme_repaints_running_badge(monkeypatch) -> None:
    monkeypatch.setattr("ankismart.ui.task_center.get_theme_accent_text_hex", lambda **_: "#123456")
    panel = TaskCenterPanel()
    task = build_default_task_run(flow="full_pipeline", task_id="task-1")
    task.status = TaskStatus.RUNNING

    panel.render_task(task)
    widget = panel._task_widgets["task-1"]
    status_badge = widget.findChildren(type(panel._summary_label))[1]
    assert "#123456" in status_badge.styleSheet()

    monkeypatch.setattr("ankismart.ui.task_center.get_theme_accent_text_hex", lambda **_: "#654321")
    panel.update_theme()

    widget = panel._task_widgets["task-1"]
    status_badge = widget.findChildren(type(panel._summary_label))[1]
    assert "#654321" in status_badge.styleSheet()
