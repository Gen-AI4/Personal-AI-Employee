"""Shared logging utilities for thread-safe log file writes.

All modules that write to vault/Logs/*.json must use this shared lock
to prevent concurrent read-modify-write corruption.
"""

import threading

# Single shared lock for ALL log file writes across all modules
log_file_lock = threading.Lock()
