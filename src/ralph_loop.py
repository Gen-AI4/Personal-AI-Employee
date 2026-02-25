"""
Ralph Wiggum Loop - Autonomous task persistence for Claude Code.

The Ralph Wiggum pattern keeps Claude iterating on a task until it reaches
a defined completion state, using either:
  1. Promise-based: Claude outputs <promise>TASK_COMPLETE</promise>
  2. File-movement-based (Gold tier): Task moves to /Done folder

This module manages the loop state, tracks iterations, and provides
the Stop hook integration point. It implements both strategies and
exposes them as the `ralph-loop` Agent Skill.

Reference: https://github.com/anthropics/claude-code/tree/main/.claude/plugins/ralph-wiggum

Gold tier requirement: Ralph Wiggum loop for autonomous multi-step task completion.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

from log_utils import log_file_lock as _log_lock

logger = logging.getLogger(__name__)

# Default max iterations to prevent infinite loops
DEFAULT_MAX_ITERATIONS = 10

# State file location (written to vault/Logs/ or a temp directory)
STATE_DIR = os.getenv("VAULT_PATH", "./vault")


class RalphLoopState:
    """Tracks the state of a running Ralph Wiggum loop.

    Persists to a JSON file so the loop survives Claude Code restarts.
    """

    def __init__(
        self,
        task_id: str,
        prompt: str,
        completion_promise: str = "TASK_COMPLETE",
        completion_file: str = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        vault_path: str = STATE_DIR,
    ):
        """
        Args:
            task_id: Unique identifier for this loop instance.
            prompt: The task prompt to inject on each iteration.
            completion_promise: Text Claude must output to signal completion (strategy 1).
            completion_file: Path (relative to vault) to watch for (strategy 2).
            max_iterations: Maximum iterations before forcing exit.
            vault_path: Path to the vault (for state file and Done folder).
        """
        self.task_id = task_id
        self.prompt = prompt
        self.completion_promise = completion_promise
        self.completion_file = completion_file
        self.max_iterations = max_iterations
        self.vault_path = Path(vault_path)
        self.current_iteration = 0
        self.completed = False
        self.created = datetime.now(timezone.utc).isoformat()

    @property
    def _state_file(self) -> Path:
        state_dir = self.vault_path / "Logs"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"ralph_{self.task_id}.json"

    def save(self) -> None:
        """Persist state to disk."""
        data = {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "completion_promise": self.completion_promise,
            "completion_file": self.completion_file,
            "max_iterations": self.max_iterations,
            "current_iteration": self.current_iteration,
            "completed": self.completed,
            "created": self.created,
        }
        self._state_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, task_id: str, vault_path: str = STATE_DIR) -> "RalphLoopState | None":
        """Load state from disk. Returns None if not found."""
        state_dir = Path(vault_path) / "Logs"
        state_file = state_dir / f"ralph_{task_id}.json"
        if not state_file.exists():
            return None
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            state = cls(
                task_id=data["task_id"],
                prompt=data["prompt"],
                completion_promise=data.get("completion_promise", "TASK_COMPLETE"),
                completion_file=data.get("completion_file"),
                max_iterations=data.get("max_iterations", DEFAULT_MAX_ITERATIONS),
                vault_path=vault_path,
            )
            state.current_iteration = data.get("current_iteration", 0)
            state.completed = data.get("completed", False)
            state.created = data.get("created", "")
            return state
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Failed to load Ralph loop state {task_id}: {e}")
            return None

    def delete(self) -> None:
        """Remove state file after loop completes."""
        try:
            self._state_file.unlink(missing_ok=True)
        except OSError:
            pass


class RalphLoop:
    """Manages the Ralph Wiggum loop lifecycle.

    Coordinates between the Stop hook (which intercepts Claude's exit)
    and the task state, re-injecting the prompt until completion.
    """

    def __init__(self, vault_path: str = STATE_DIR):
        self.vault_path = Path(vault_path)
        self.logs_dir = self.vault_path / "Logs"
        self.done_dir = self.vault_path / "Done"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def start(
        self,
        prompt: str,
        completion_promise: str = "TASK_COMPLETE",
        completion_file: str = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ) -> RalphLoopState:
        """Start a new Ralph Wiggum loop.

        Creates state file and prints instructions for Claude.

        Args:
            prompt: The task prompt to iterate on.
            completion_promise: Text Claude must output to signal completion.
            completion_file: Vault-relative path to watch for (file-movement strategy).
            max_iterations: Maximum iterations before forced exit.

        Returns:
            The initialized RalphLoopState.
        """
        task_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        state = RalphLoopState(
            task_id=task_id,
            prompt=prompt,
            completion_promise=completion_promise,
            completion_file=completion_file,
            max_iterations=max_iterations,
            vault_path=str(self.vault_path),
        )
        state.save()

        self._log("ralph_loop_started", {
            "task_id": task_id,
            "max_iterations": max_iterations,
            "strategy": "file_movement" if completion_file else "promise",
        })

        logger.info(f"Ralph loop started: {task_id}")
        return state

    def check_completion_promise(
        self, output: str, state: RalphLoopState
    ) -> bool:
        """Check if Claude's output contains the completion promise.

        Args:
            output: The text Claude output before trying to exit.
            state: The current loop state.

        Returns:
            True if the promise was found (task complete).
        """
        return f"<promise>{state.completion_promise}</promise>" in output

    def check_completion_file(self, state: RalphLoopState) -> bool:
        """Check if the completion file has moved to /Done (file-movement strategy).

        Args:
            state: The current loop state with completion_file set.

        Returns:
            True if the file exists in /Done.
        """
        if not state.completion_file:
            return False

        # Check if the file (or any file matching the stem) is in /Done
        completion_path = Path(state.completion_file)
        stem = completion_path.stem

        if not self.done_dir.exists():
            return False

        for f in self.done_dir.iterdir():
            if stem in f.name:
                return True

        return False

    def should_continue(self, state: RalphLoopState, last_output: str = "") -> bool:
        """Determine whether the loop should continue.

        Checks both strategies and iteration limit.

        Args:
            state: Current loop state.
            last_output: Claude's last output text.

        Returns:
            True if the loop should re-inject the prompt (keep going).
        """
        # Check iteration limit
        if state.current_iteration >= state.max_iterations:
            logger.warning(
                f"Ralph loop {state.task_id} hit max iterations "
                f"({state.max_iterations}), exiting"
            )
            return False

        # Check promise-based completion
        if last_output and self.check_completion_promise(last_output, state):
            logger.info(f"Ralph loop {state.task_id}: promise found in output")
            return False

        # Check file-movement completion
        if state.completion_file and self.check_completion_file(state):
            logger.info(f"Ralph loop {state.task_id}: completion file found in Done")
            return False

        return True

    def advance(self, state: RalphLoopState) -> None:
        """Increment the iteration counter and save state."""
        state.current_iteration += 1
        state.save()
        self._log("ralph_loop_iteration", {
            "task_id": state.task_id,
            "iteration": state.current_iteration,
            "max_iterations": state.max_iterations,
        })

    def complete(self, state: RalphLoopState) -> None:
        """Mark the loop as complete and clean up state."""
        state.completed = True
        state.save()
        self._log("ralph_loop_completed", {
            "task_id": state.task_id,
            "total_iterations": state.current_iteration,
        })
        state.delete()
        logger.info(
            f"Ralph loop {state.task_id} completed after "
            f"{state.current_iteration} iterations"
        )

    def get_active_loops(self) -> list[RalphLoopState]:
        """Return all currently active loop state files."""
        loops = []
        for f in self.logs_dir.glob("ralph_*.json"):
            task_id = f.stem[len("ralph_"):]
            state = RalphLoopState.load(task_id, str(self.vault_path))
            if state and not state.completed:
                loops.append(state)
        return loops

    def _log(self, action_type: str, details: dict) -> None:
        """Write a structured log entry. Thread-safe."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"{today}.json"

        entry = {
            "timestamp": now.isoformat(),
            "action_type": action_type,
            "actor": "ralph_loop",
            **details,
        }

        with _log_lock:
            entries = []
            if log_file.exists():
                try:
                    entries = json.loads(log_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    entries = []
            entries.append(entry)
            log_file.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
            )


def run_stop_hook(output: str, vault_path: str = STATE_DIR) -> int:
    """Entry point for the Ralph Wiggum Stop hook.

    Called by Claude Code's stop hook when Claude is about to exit.
    Checks all active loops and re-injects the prompt if not done.

    Args:
        output: Claude's final output text before exit attempt.
        vault_path: Path to the vault directory.

    Returns:
        Exit code: 0 = allow exit, 1 = block exit (re-inject prompt)
    """
    loop = RalphLoop(vault_path=vault_path)
    active_loops = loop.get_active_loops()

    if not active_loops:
        return 0  # No loops active, allow Claude to exit

    for state in active_loops:
        if loop.should_continue(state, last_output=output):
            loop.advance(state)
            # Print the prompt for Claude to re-process
            print(f"\n[Ralph Wiggum Loop - Iteration {state.current_iteration}/{state.max_iterations}]")
            print(f"{state.prompt}")
            return 1  # Block exit
        else:
            loop.complete(state)

    return 0  # All loops done, allow exit


if __name__ == "__main__":
    # Called as the stop hook: python ralph_loop.py <vault_path>
    vault = sys.argv[1] if len(sys.argv) > 1 else STATE_DIR
    # Read Claude's output from stdin
    output = sys.stdin.read() if not sys.stdin.isatty() else ""
    exit_code = run_stop_hook(output, vault_path=vault)
    sys.exit(exit_code)
