"""Tests for the Ralph Wiggum autonomous loop (Gold tier)."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ralph_loop import RalphLoopState, RalphLoop, run_stop_hook


@pytest.fixture
def vault(tmp_path):
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    (vault_path / "Logs").mkdir()
    (vault_path / "Done").mkdir()
    return vault_path


@pytest.fixture
def loop(vault):
    return RalphLoop(vault_path=str(vault))


# --- RalphLoopState ---


class TestRalphLoopState:
    """Tests for RalphLoopState creation and persistence."""

    def test_creates_state(self, vault):
        state = RalphLoopState(
            task_id="test_001",
            prompt="Process all items",
            vault_path=str(vault),
        )
        assert state.task_id == "test_001"
        assert state.prompt == "Process all items"
        assert state.current_iteration == 0
        assert state.completed is False

    def test_default_completion_promise(self, vault):
        state = RalphLoopState(
            task_id="test_002",
            prompt="Test",
            vault_path=str(vault),
        )
        assert state.completion_promise == "TASK_COMPLETE"

    def test_custom_max_iterations(self, vault):
        state = RalphLoopState(
            task_id="test_003",
            prompt="Test",
            max_iterations=5,
            vault_path=str(vault),
        )
        assert state.max_iterations == 5

    def test_save_creates_file(self, vault):
        state = RalphLoopState(
            task_id="save_test_001",
            prompt="Test",
            vault_path=str(vault),
        )
        state.save()
        assert (vault / "Logs" / "ralph_save_test_001.json").exists()

    def test_save_persists_state(self, vault):
        state = RalphLoopState(
            task_id="persist_test",
            prompt="Test prompt",
            max_iterations=7,
            vault_path=str(vault),
        )
        state.current_iteration = 3
        state.save()
        data = json.loads(
            (vault / "Logs" / "ralph_persist_test.json").read_text(encoding="utf-8")
        )
        assert data["task_id"] == "persist_test"
        assert data["prompt"] == "Test prompt"
        assert data["current_iteration"] == 3
        assert data["max_iterations"] == 7

    def test_load_restores_state(self, vault):
        state = RalphLoopState(
            task_id="load_test",
            prompt="Loaded prompt",
            max_iterations=5,
            vault_path=str(vault),
        )
        state.current_iteration = 2
        state.save()

        loaded = RalphLoopState.load("load_test", str(vault))
        assert loaded is not None
        assert loaded.task_id == "load_test"
        assert loaded.prompt == "Loaded prompt"
        assert loaded.current_iteration == 2
        assert loaded.max_iterations == 5

    def test_load_returns_none_when_not_found(self, vault):
        loaded = RalphLoopState.load("nonexistent_task", str(vault))
        assert loaded is None

    def test_delete_removes_file(self, vault):
        state = RalphLoopState(
            task_id="delete_test",
            prompt="Test",
            vault_path=str(vault),
        )
        state.save()
        state.delete()
        assert not (vault / "Logs" / "ralph_delete_test.json").exists()

    def test_delete_missing_file_no_error(self, vault):
        state = RalphLoopState(
            task_id="no_file_test",
            prompt="Test",
            vault_path=str(vault),
        )
        # Should not raise even if file doesn't exist
        state.delete()

    def test_completion_file_optional(self, vault):
        state = RalphLoopState(
            task_id="no_completion_file",
            prompt="Test",
            completion_file=None,
            vault_path=str(vault),
        )
        assert state.completion_file is None


# --- RalphLoop ---


class TestRalphLoop:
    """Tests for RalphLoop lifecycle management."""

    def test_start_creates_state(self, loop, vault):
        state = loop.start(
            prompt="Process all items in /Needs_Action",
            max_iterations=5,
        )
        assert state is not None
        assert state.prompt == "Process all items in /Needs_Action"
        assert state.max_iterations == 5

    def test_start_saves_state_file(self, loop, vault):
        state = loop.start(prompt="Test")
        state_file = vault / "Logs" / f"ralph_{state.task_id}.json"
        assert state_file.exists()

    def test_start_logs_action(self, loop, vault):
        loop.start(prompt="Test task")
        log_files = list((vault / "Logs").glob("*.json"))
        # Should have at least the state file and a log file
        assert len(log_files) >= 1

    def test_check_completion_promise_found(self, loop, vault):
        state = RalphLoopState(
            task_id="promise_test",
            prompt="Test",
            completion_promise="TASK_COMPLETE",
            vault_path=str(vault),
        )
        output = "I have processed all items.\n<promise>TASK_COMPLETE</promise>"
        assert loop.check_completion_promise(output, state) is True

    def test_check_completion_promise_not_found(self, loop, vault):
        state = RalphLoopState(
            task_id="no_promise_test",
            prompt="Test",
            completion_promise="TASK_COMPLETE",
            vault_path=str(vault),
        )
        output = "I processed some items but not all."
        assert loop.check_completion_promise(output, state) is False

    def test_check_completion_promise_partial_match(self, loop, vault):
        state = RalphLoopState(
            task_id="partial_promise",
            prompt="Test",
            completion_promise="TASK_COMPLETE",
            vault_path=str(vault),
        )
        # Must be exact wrapped in promise tags
        output = "TASK_COMPLETE"
        assert loop.check_completion_promise(output, state) is False

    def test_check_completion_file_found_in_done(self, loop, vault):
        state = RalphLoopState(
            task_id="file_test",
            prompt="Test",
            completion_file="TASK_inbox_sweep.md",
            vault_path=str(vault),
        )
        # Create the file in Done
        (vault / "Done" / "20260224_080000_TASK_inbox_sweep.md").write_text(
            "done", encoding="utf-8"
        )
        assert loop.check_completion_file(state) is True

    def test_check_completion_file_not_found(self, loop, vault):
        state = RalphLoopState(
            task_id="file_not_found",
            prompt="Test",
            completion_file="TASK_missing.md",
            vault_path=str(vault),
        )
        assert loop.check_completion_file(state) is False

    def test_check_completion_file_none(self, loop, vault):
        state = RalphLoopState(
            task_id="no_file",
            prompt="Test",
            completion_file=None,
            vault_path=str(vault),
        )
        assert loop.check_completion_file(state) is False

    def test_should_continue_within_limit(self, loop, vault):
        state = RalphLoopState(
            task_id="continue_test",
            prompt="Test",
            max_iterations=5,
            vault_path=str(vault),
        )
        state.current_iteration = 2
        assert loop.should_continue(state, "") is True

    def test_should_not_continue_at_max(self, loop, vault):
        state = RalphLoopState(
            task_id="max_iter_test",
            prompt="Test",
            max_iterations=5,
            vault_path=str(vault),
        )
        state.current_iteration = 5
        assert loop.should_continue(state, "") is False

    def test_should_not_continue_if_promise_found(self, loop, vault):
        state = RalphLoopState(
            task_id="promise_done",
            prompt="Test",
            completion_promise="TASK_COMPLETE",
            max_iterations=10,
            vault_path=str(vault),
        )
        state.current_iteration = 2
        output = "<promise>TASK_COMPLETE</promise>"
        assert loop.should_continue(state, output) is False

    def test_should_not_continue_if_file_in_done(self, loop, vault):
        state = RalphLoopState(
            task_id="file_done",
            prompt="Test",
            completion_file="TASK_briefing.md",
            max_iterations=10,
            vault_path=str(vault),
        )
        state.current_iteration = 2
        (vault / "Done" / "20260224_TASK_briefing.md").write_text("done", encoding="utf-8")
        assert loop.should_continue(state, "") is False

    def test_advance_increments_iteration(self, loop, vault):
        state = RalphLoopState(
            task_id="advance_test",
            prompt="Test",
            vault_path=str(vault),
        )
        state.save()
        loop.advance(state)
        assert state.current_iteration == 1

    def test_advance_saves_state(self, loop, vault):
        state = RalphLoopState(
            task_id="advance_save",
            prompt="Test",
            vault_path=str(vault),
        )
        state.save()
        loop.advance(state)
        loaded = RalphLoopState.load("advance_save", str(vault))
        assert loaded.current_iteration == 1

    def test_complete_marks_completed(self, loop, vault):
        state = RalphLoopState(
            task_id="complete_test",
            prompt="Test",
            vault_path=str(vault),
        )
        state.save()
        loop.complete(state)
        assert state.completed is True

    def test_complete_deletes_state_file(self, loop, vault):
        state = RalphLoopState(
            task_id="cleanup_test",
            prompt="Test",
            vault_path=str(vault),
        )
        state.save()
        assert (vault / "Logs" / "ralph_cleanup_test.json").exists()
        loop.complete(state)
        assert not (vault / "Logs" / "ralph_cleanup_test.json").exists()

    def test_get_active_loops_empty(self, loop, vault):
        active = loop.get_active_loops()
        assert active == []

    def test_get_active_loops_finds_running(self, loop, vault):
        state = loop.start(prompt="Active task")
        active = loop.get_active_loops()
        assert len(active) > 0
        assert any(s.task_id == state.task_id for s in active)

    def test_get_active_loops_excludes_completed(self, loop, vault):
        state = loop.start(prompt="Completed task")
        loop.complete(state)
        active = loop.get_active_loops()
        assert not any(s.task_id == state.task_id for s in active)


# --- run_stop_hook ---


class TestRunStopHook:
    """Tests for the stop hook entry point."""

    def test_exits_when_no_active_loops(self, vault):
        exit_code = run_stop_hook("Some output", vault_path=str(vault))
        assert exit_code == 0  # Allow exit

    def test_blocks_exit_when_loop_running(self, loop, vault, capsys):
        state = loop.start(prompt="Process inbox", max_iterations=5)
        # No completion promise in output
        exit_code = run_stop_hook("I processed one item.", vault_path=str(vault))
        assert exit_code == 1  # Block exit

    def test_allows_exit_when_promise_in_output(self, loop, vault):
        state = loop.start(
            prompt="Process inbox",
            completion_promise="TASK_COMPLETE",
            max_iterations=5,
        )
        exit_code = run_stop_hook(
            "All done! <promise>TASK_COMPLETE</promise>",
            vault_path=str(vault),
        )
        assert exit_code == 0  # Allow exit

    def test_allows_exit_at_max_iterations(self, loop, vault):
        state = loop.start(prompt="Test", max_iterations=2)
        # Simulate hitting max iterations
        state.current_iteration = 2
        state.save()
        exit_code = run_stop_hook("Not done yet.", vault_path=str(vault))
        assert exit_code == 0  # Allow exit (max iterations reached)
