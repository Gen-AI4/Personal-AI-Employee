"""Tests for the Scheduler module."""

import json
import time
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from scheduler import Scheduler, ScheduledTask, generate_cron_entries, generate_windows_task_xml


@pytest.fixture
def vault(tmp_path):
    """Create a temporary vault with Logs directory."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    (vault_path / "Logs").mkdir()
    return vault_path


@pytest.fixture
def scheduler(vault):
    """Create a Scheduler with a temporary vault."""
    return Scheduler(vault_path=str(vault))


# --- ScheduledTask Tests ---


class TestScheduledTask:
    """Test the ScheduledTask class."""

    def test_create_periodic_task(self):
        cb = MagicMock()
        task = ScheduledTask(name="test", callback=cb, interval_seconds=60)
        assert task.name == "test"
        assert task.interval_seconds == 60
        assert task.run_count == 0
        assert task.last_run is None

    def test_create_daily_task(self):
        cb = MagicMock()
        task = ScheduledTask(
            name="daily", callback=cb,
            run_at_hour=8, run_at_minute=30,
        )
        assert task.run_at_hour == 8
        assert task.run_at_minute == 30

    def test_should_run_periodic_first_time(self):
        cb = MagicMock()
        task = ScheduledTask(name="t", callback=cb, interval_seconds=60)
        assert task.should_run(datetime.now(timezone.utc)) is True

    def test_should_not_run_periodic_too_soon(self):
        cb = MagicMock()
        task = ScheduledTask(name="t", callback=cb, interval_seconds=60)
        task.last_run = datetime.now(timezone.utc)
        assert task.should_run(datetime.now(timezone.utc)) is False

    def test_should_run_periodic_after_interval(self):
        cb = MagicMock()
        task = ScheduledTask(name="t", callback=cb, interval_seconds=5)
        task.last_run = datetime.now(timezone.utc) - timedelta(seconds=10)
        assert task.should_run(datetime.now(timezone.utc)) is True

    def test_should_run_daily_at_correct_time(self):
        cb = MagicMock()
        now = datetime.now(timezone.utc)
        task = ScheduledTask(
            name="t", callback=cb,
            run_at_hour=now.hour, run_at_minute=0,
        )
        assert task.should_run(now) is True

    def test_should_not_run_daily_wrong_hour(self):
        cb = MagicMock()
        now = datetime.now(timezone.utc)
        other_hour = (now.hour + 6) % 24
        task = ScheduledTask(
            name="t", callback=cb,
            run_at_hour=other_hour, run_at_minute=0,
        )
        assert task.should_run(now) is False

    def test_should_not_run_daily_already_ran_today(self):
        cb = MagicMock()
        now = datetime.now(timezone.utc)
        task = ScheduledTask(
            name="t", callback=cb,
            run_at_hour=now.hour, run_at_minute=0,
        )
        task.last_run = now - timedelta(minutes=30)
        assert task.should_run(now) is False

    def test_should_not_run_no_schedule(self):
        cb = MagicMock()
        task = ScheduledTask(name="t", callback=cb)
        assert task.should_run(datetime.now(timezone.utc)) is False

    def test_execute_success(self):
        cb = MagicMock()
        task = ScheduledTask(name="t", callback=cb, interval_seconds=60)
        result = task.execute()
        assert result is True
        assert task.run_count == 1
        assert task.last_run is not None
        cb.assert_called_once()

    def test_execute_failure(self):
        cb = MagicMock(side_effect=RuntimeError("boom"))
        task = ScheduledTask(name="t", callback=cb, interval_seconds=60)
        result = task.execute()
        assert result is False
        assert task.error_count == 1
        assert task.run_count == 0

    def test_description_attribute(self):
        cb = MagicMock()
        task = ScheduledTask(
            name="t", callback=cb,
            interval_seconds=60, description="Test task",
        )
        assert task.description == "Test task"


# --- Scheduler Tests ---


class TestSchedulerInit:
    """Test Scheduler initialization."""

    def test_creates_logs_directory(self, vault):
        sched = Scheduler(vault_path=str(vault))
        assert (vault / "Logs").exists()

    def test_starts_with_no_tasks(self, scheduler):
        assert len(scheduler.get_tasks()) == 0

    def test_not_running_initially(self, scheduler):
        assert scheduler._running is False


class TestSchedulerAddRemoveTask:
    """Test adding and removing tasks."""

    def test_add_task(self, scheduler):
        task = ScheduledTask(
            name="test", callback=MagicMock(), interval_seconds=60,
        )
        scheduler.add_task(task)
        assert "test" in scheduler.get_tasks()

    def test_add_multiple_tasks(self, scheduler):
        for i in range(3):
            scheduler.add_task(ScheduledTask(
                name=f"task_{i}", callback=MagicMock(), interval_seconds=60,
            ))
        assert len(scheduler.get_tasks()) == 3

    def test_remove_task(self, scheduler):
        scheduler.add_task(ScheduledTask(
            name="removable", callback=MagicMock(), interval_seconds=60,
        ))
        scheduler.remove_task("removable")
        assert "removable" not in scheduler.get_tasks()

    def test_remove_nonexistent_task(self, scheduler):
        # Should not raise
        scheduler.remove_task("does_not_exist")


class TestSchedulerCheckAndRun:
    """Test the check_and_run method."""

    def test_runs_due_tasks(self, scheduler):
        cb = MagicMock()
        # interval_seconds must be > 0 (truthy); last_run=None triggers first run
        task = ScheduledTask(name="due", callback=cb, interval_seconds=1)
        scheduler.add_task(task)
        executed = scheduler.check_and_run()
        assert "due" in executed
        cb.assert_called_once()

    def test_skips_not_due_tasks(self, scheduler):
        cb = MagicMock()
        task = ScheduledTask(name="not_due", callback=cb, interval_seconds=9999)
        task.last_run = datetime.now(timezone.utc)
        scheduler.add_task(task)
        executed = scheduler.check_and_run()
        assert executed == []
        cb.assert_not_called()

    def test_returns_executed_names(self, scheduler):
        cb1 = MagicMock()
        cb2 = MagicMock()
        scheduler.add_task(ScheduledTask(
            name="a", callback=cb1, interval_seconds=1,
        ))
        scheduler.add_task(ScheduledTask(
            name="b", callback=cb2, interval_seconds=1,
        ))
        executed = scheduler.check_and_run()
        assert "a" in executed
        assert "b" in executed

    def test_logs_executed_tasks(self, scheduler, vault):
        scheduler.add_task(ScheduledTask(
            name="logged", callback=MagicMock(), interval_seconds=1,
        ))
        scheduler.check_and_run()
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) >= 1
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "scheduled_task_executed" for e in entries)

    def test_logs_failed_tasks(self, scheduler, vault):
        scheduler.add_task(ScheduledTask(
            name="failing",
            callback=MagicMock(side_effect=RuntimeError("fail")),
            interval_seconds=1,
        ))
        scheduler.check_and_run()
        log_files = list((vault / "Logs").glob("*.json"))
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "scheduled_task_failed" for e in entries)


class TestSchedulerRunLoop:
    """Test the scheduler's run loop."""

    def test_run_and_stop(self, scheduler):
        cb = MagicMock()
        scheduler.add_task(ScheduledTask(
            name="loop_test", callback=cb, interval_seconds=1,
        ))

        thread = threading.Thread(target=scheduler.run, kwargs={"check_interval": 1})
        thread.start()
        time.sleep(0.5)
        scheduler.stop()
        thread.join(timeout=3)
        assert not thread.is_alive()

    def test_stop_sets_flag(self, scheduler):
        scheduler._running = True
        scheduler.stop()
        assert scheduler._running is False


class TestSchedulerGetStatus:
    """Test scheduler status reporting."""

    def test_status_includes_running(self, scheduler):
        status = scheduler.get_status()
        assert "running" in status
        assert status["running"] is False

    def test_status_includes_task_count(self, scheduler):
        scheduler.add_task(ScheduledTask(
            name="t", callback=MagicMock(), interval_seconds=60,
        ))
        status = scheduler.get_status()
        assert status["task_count"] == 1

    def test_status_task_details(self, scheduler):
        cb = MagicMock()
        task = ScheduledTask(
            name="detail_test", callback=cb,
            interval_seconds=60, description="Test",
        )
        scheduler.add_task(task)
        task.execute()  # Run once

        status = scheduler.get_status()
        task_info = status["tasks"]["detail_test"]
        assert task_info["run_count"] == 1
        assert task_info["description"] == "Test"
        assert task_info["last_run"] is not None


# --- Config Generator Tests ---


class TestGenerateCronEntries:
    """Test crontab generation."""

    def test_returns_string(self):
        result = generate_cron_entries()
        assert isinstance(result, str)

    def test_contains_cron_expressions(self):
        result = generate_cron_entries()
        assert "*/5 * * * *" in result
        assert "0 8 * * *" in result
        assert "0 * * * *" in result

    def test_uses_custom_python_path(self):
        result = generate_cron_entries(python_path="/usr/bin/python3.13")
        assert "/usr/bin/python3.13" in result

    def test_uses_custom_script_dir(self):
        result = generate_cron_entries(script_dir="/opt/ai-employee")
        assert "/opt/ai-employee" in result


class TestGenerateWindowsTaskXml:
    """Test Windows Task Scheduler XML generation."""

    def test_returns_xml(self):
        result = generate_windows_task_xml()
        assert "<?xml" in result
        assert "</Task>" in result

    def test_5_minute_interval(self):
        result = generate_windows_task_xml()
        assert "PT5M" in result

    def test_custom_python_path(self):
        result = generate_windows_task_xml(python_path="C:\\Python313\\python.exe")
        assert "C:\\Python313\\python.exe" in result

    def test_custom_working_directory(self):
        result = generate_windows_task_xml(script_dir="C:\\Projects\\AIEmployee")
        assert "C:\\Projects\\AIEmployee" in result

    def test_boot_trigger(self):
        result = generate_windows_task_xml()
        assert "BootTrigger" in result
