"""
File System Watcher - Monitors a drop folder for new files.

When files are dropped into the watched folder (vault/Inbox), this watcher:
1. Detects the new file via watchdog events
2. Copies the file to /Needs_Action with a prefixed name
3. Creates a metadata .md file describing the dropped file
4. Logs the action

This is the Bronze tier watcher implementation (one working watcher).
"""

import re
import shutil
import logging
import queue
from pathlib import Path
from datetime import datetime, timezone
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from .base_watcher import BaseWatcher

logger = logging.getLogger(__name__)


# Priority keywords used to classify incoming files
PRIORITY_KEYWORDS = {
    "high": ["urgent", "asap", "critical", "important", "priority"],
    "medium": ["invoice", "payment", "review", "request"],
    "low": [],
}

# Regex to strip path-traversal and unsafe characters from filenames
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize_filename(name: str) -> str:
    """Sanitize a filename to prevent path traversal and unsafe characters.

    Strips '..' sequences, leading dots, path separators, and other
    characters that could escape the target directory or break YAML.
    """
    # Remove path separators and traversal
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    # Remove other unsafe characters
    name = _UNSAFE_CHARS.sub("", name)
    # Strip leading dots (hidden files)
    name = name.lstrip(".")
    # Replace spaces with underscores
    name = name.replace(" ", "_")
    return name or "unnamed"


def _escape_yaml_string(value: str) -> str:
    """Escape a string for safe inclusion in YAML double-quoted values."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def classify_priority(filename: str) -> str:
    """Classify file priority based on filename keywords."""
    name_lower = filename.lower()
    for level in ("high", "medium"):
        if any(kw in name_lower for kw in PRIORITY_KEYWORDS[level]):
            return level
    return "low"


class DropFolderHandler(FileSystemEventHandler):
    """Watchdog event handler that processes new files dropped into Inbox.

    On file creation, queues the file path for processing by the watcher.
    Uses a thread-safe queue to communicate with the watcher thread.
    """

    def __init__(self, watcher: "FileSystemWatcher"):
        super().__init__()
        self.watcher = watcher

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return

        source = Path(event.src_path)

        # Skip hidden files and .gitkeep
        if source.name.startswith("."):
            return

        self.watcher.logger.info(f"New file detected: {source.name}")

        try:
            self.watcher.pending_queue.put_nowait(source)
        except Exception as e:
            self.watcher.logger.error(f"Error queuing file {source.name}: {e}")


class FileSystemWatcher(BaseWatcher):
    """Watches a local folder for new file drops and creates action items.

    Uses the watchdog library for real-time filesystem event detection,
    with a polling fallback via the BaseWatcher check loop.
    """

    def __init__(self, vault_path: str, watch_folder: str = None, check_interval: int = 10):
        super().__init__(vault_path, check_interval)
        self.watch_folder = Path(watch_folder) if watch_folder else self.vault_path / "Inbox"
        self.watch_folder.mkdir(parents=True, exist_ok=True)
        # Thread-safe queue replaces plain list for cross-thread communication
        self.pending_queue: queue.Queue[Path] = queue.Queue()
        # Keep pending_items as a property alias for backwards compatibility in tests
        self._processed_files: set[str] = set()
        self._observer = None

    @property
    def pending_items(self) -> "_PendingItemsProxy":
        """Backwards-compatible proxy that delegates to the thread-safe queue."""
        return _PendingItemsProxy(self.pending_queue)

    def _start_observer(self) -> None:
        """Start the watchdog observer for real-time file detection."""
        handler = DropFolderHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_folder), recursive=False)
        self._observer.daemon = True
        self._observer.start()
        self.logger.info(f"Watchdog observer started on: {self.watch_folder}")

    def check_for_updates(self) -> list:
        """Return list of new files detected since last check.

        Combines watchdog event-driven items with a filesystem scan
        to catch any files that may have been missed.
        """
        new_items = []
        seen_names = set()

        # Drain the thread-safe queue
        while True:
            try:
                item = self.pending_queue.get_nowait()
            except queue.Empty:
                break
            if item.name not in self._processed_files and item.exists():
                new_items.append(item)
                seen_names.add(item.name)

        # Fallback scan: check for any unprocessed files in the watch folder
        if self.watch_folder.exists():
            for f in self.watch_folder.iterdir():
                if (
                    f.is_file()
                    and not f.name.startswith(".")
                    and f.name not in self._processed_files
                    and f.name not in seen_names
                ):
                    new_items.append(f)
                    seen_names.add(f.name)

        return new_items

    def create_action_file(self, item: Path) -> Path:
        """Copy the dropped file to /Needs_Action and create a metadata sidecar.

        Args:
            item: Path to the file in the Inbox/watch folder.

        Returns:
            Path to the created metadata .md file.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_name = _sanitize_filename(item.stem)
        safe_suffix = _sanitize_filename(item.suffix.lstrip("."))
        if safe_suffix:
            safe_suffix = "." + safe_suffix

        dest_name = f"FILE_{timestamp}_{safe_name}{safe_suffix}"
        dest_path = self.needs_action / dest_name

        # Verify destination stays within needs_action directory
        if not dest_path.resolve().is_relative_to(self.needs_action.resolve()):
            self.logger.error(f"Path traversal blocked for: {item.name}")
            raise ValueError(f"Unsafe filename rejected: {item.name}")

        # Copy the original file
        shutil.copy2(str(item), str(dest_path))

        # Determine priority
        priority = classify_priority(item.name)

        # Determine file size
        try:
            file_size = item.stat().st_size
        except OSError:
            file_size = 0

        # Escape filename for safe YAML embedding
        escaped_name = _escape_yaml_string(item.name)

        # Create metadata sidecar .md
        meta_path = self.needs_action / f"FILE_{timestamp}_{safe_name}.md"
        meta_content = f"""---
type: file_drop
original_name: "{escaped_name}"
size: {file_size}
received: {datetime.now(timezone.utc).isoformat()}
priority: {priority}
status: pending
source: inbox
---

## File Drop: {escaped_name}

A new file was dropped into the Inbox for processing.

- **Original name**: {escaped_name}
- **Size**: {file_size} bytes
- **Priority**: {priority}
- **Copied to**: {dest_name}

## Suggested Actions
- [ ] Review file contents
- [ ] Categorize and process
- [ ] Move to /Done when complete
"""
        meta_path.write_text(meta_content, encoding="utf-8")

        # Mark as processed
        self._processed_files.add(item.name)

        self.log_action(
            "file_drop_processed",
            {
                "original_file": item.name,
                "action_file": str(meta_path.name),
                "priority": priority,
                "size": file_size,
                "result": "success",
            },
        )

        return meta_path

    def run(self) -> None:
        """Start the filesystem watcher with both watchdog and polling."""
        self.logger.info(f"Starting FileSystemWatcher on: {self.watch_folder}")
        self._start_observer()
        super().run()

    def stop(self) -> None:
        """Stop the watcher and its watchdog observer."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
        super().stop()


class _PendingItemsProxy:
    """Proxy that provides list-like append() over a thread-safe Queue.

    This allows existing code that calls watcher.pending_items.append(x)
    to keep working while the underlying storage is thread-safe.
    """

    def __init__(self, q: queue.Queue):
        self._queue = q

    def append(self, item: Path) -> None:
        self._queue.put_nowait(item)

    def __len__(self) -> int:
        return self._queue.qsize()

    def __bool__(self) -> bool:
        return not self._queue.empty()
