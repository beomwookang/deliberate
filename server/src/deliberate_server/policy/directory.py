"""Approver directory — loads approvers.yaml and resolves IDs to concrete approvers.

See PRD §5.2 for the directory schema. Supports hot-reload on file change.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from deliberate.types import ApproverDirectoryConfig, ApproverEntry, ResolvedApprover

logger = logging.getLogger("deliberate_server.policy.directory")


class ApproverDirectoryError(Exception):
    """Raised when the approver directory has a problem."""


class ApproverNotFoundError(ApproverDirectoryError):
    """Raised when an approver or group ID is not found in the directory."""


class ApproverDirectory:
    """Loads and resolves approvers from a YAML directory file.

    Thread-safe: the internal state is swapped atomically behind a lock.
    Hot-reload: call reload() or use start_watching() for automatic file monitoring.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._approvers: dict[str, ApproverEntry] = {}
        self._groups: dict[str, list[str]] = {}
        self._file_path: Path | None = None
        self._file_hash: str = ""
        self._watcher_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def load(self, file_path: str | Path) -> None:
        """Load the approver directory from a YAML file.

        Raises ApproverDirectoryError on parse/validation failure.
        """
        path = Path(file_path)
        if not path.exists():
            msg = f"Approver directory file not found: {path}"
            raise ApproverDirectoryError(msg)

        content = path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(content.encode()).hexdigest()

        try:
            raw = yaml.safe_load(content)
        except yaml.YAMLError as e:
            msg = f"Invalid YAML in approver directory {path}: {e}"
            raise ApproverDirectoryError(msg) from e

        if not isinstance(raw, dict):
            msg = f"Approver directory must be a YAML mapping, got {type(raw).__name__}"
            raise ApproverDirectoryError(msg)

        try:
            config = ApproverDirectoryConfig(**raw)
        except ValidationError as e:
            msg = f"Invalid approver directory schema in {path}: {e}"
            raise ApproverDirectoryError(msg) from e

        # Build lookup dicts
        approvers: dict[str, ApproverEntry] = {}
        for entry in config.approvers:
            if entry.id in approvers:
                msg = f"Duplicate approver ID '{entry.id}' in {path}"
                raise ApproverDirectoryError(msg)
            approvers[entry.id] = entry

        groups: dict[str, list[str]] = {}
        for group in config.groups:
            if group.id in groups:
                msg = f"Duplicate group ID '{group.id}' in {path}"
                raise ApproverDirectoryError(msg)
            # Validate all members exist
            for member_id in group.members:
                if member_id not in approvers:
                    msg = (
                        f"Group '{group.id}' references unknown approver '{member_id}' in {path}"
                    )
                    raise ApproverDirectoryError(msg)
            groups[group.id] = group.members

        with self._lock:
            self._approvers = approvers
            self._groups = groups
            self._file_path = path
            self._file_hash = file_hash

        logger.info(
            "Loaded approver directory: %d approvers, %d groups from %s",
            len(approvers),
            len(groups),
            path,
        )

    def reload(self) -> bool:
        """Reload the directory file if it has changed.

        Returns True if the file was reloaded, False if unchanged.
        On parse error, logs a warning and keeps the current state.
        """
        if self._file_path is None:
            return False

        try:
            content = self._file_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Could not read approver directory %s: %s", self._file_path, e)
            return False

        file_hash = hashlib.sha256(content.encode()).hexdigest()
        if file_hash == self._file_hash:
            return False

        try:
            self.load(self._file_path)
            logger.info("Hot-reloaded approver directory from %s", self._file_path)
            return True
        except ApproverDirectoryError as e:
            logger.warning(
                "Failed to hot-reload approver directory (keeping current state): %s", e
            )
            return False

    def resolve(self, ref: str) -> list[ResolvedApprover]:
        """Resolve an approver or group ID to a list of concrete approvers.

        Args:
            ref: An individual approver ID or a group ID.

        Returns:
            List of ResolvedApprover with email and display_name populated.

        Raises:
            ApproverNotFoundError: If the ref doesn't match any approver or group.
        """
        with self._lock:
            # Try individual approver first
            if ref in self._approvers:
                entry = self._approvers[ref]
                return [
                    ResolvedApprover(
                        id=entry.id,
                        email=entry.email,
                        display_name=entry.display_name,
                    )
                ]

            # Try group
            if ref in self._groups:
                result = []
                for member_id in self._groups[ref]:
                    entry = self._approvers[member_id]
                    result.append(
                        ResolvedApprover(
                            id=entry.id,
                            email=entry.email,
                            display_name=entry.display_name,
                        )
                    )
                return result

            msg = f"Unknown approver or group ID: '{ref}'"
            raise ApproverNotFoundError(msg)

    def get_approver(self, approver_id: str) -> ApproverEntry | None:
        """Get a single approver entry by ID, or None if not found."""
        with self._lock:
            return self._approvers.get(approver_id)

    @property
    def approver_count(self) -> int:
        with self._lock:
            return len(self._approvers)

    @property
    def group_count(self) -> int:
        with self._lock:
            return len(self._groups)

    def start_watching(self, poll_interval: float = 5.0) -> None:
        """Start a background thread that polls for file changes.

        Uses simple polling instead of watchdog to avoid an extra dependency.
        The poll interval is configurable (default 5s).
        """
        if self._watcher_thread is not None:
            return

        self._stop_event.clear()

        def _watch() -> None:
            while not self._stop_event.wait(poll_interval):
                self.reload()

        self._watcher_thread = threading.Thread(target=_watch, daemon=True, name="approver-watch")
        self._watcher_thread.start()
        logger.info("Started approver directory watcher (poll interval: %.1fs)", poll_interval)

    def stop_watching(self) -> None:
        """Stop the background file watcher."""
        self._stop_event.set()
        if self._watcher_thread is not None:
            self._watcher_thread.join(timeout=10)
            self._watcher_thread = None
            logger.info("Stopped approver directory watcher")

    def to_dict(self) -> dict[str, Any]:
        """Return a summary dict for debugging/health checks."""
        with self._lock:
            return {
                "file_path": str(self._file_path) if self._file_path else None,
                "file_hash": self._file_hash[:16] + "..." if self._file_hash else None,
                "approver_count": len(self._approvers),
                "group_count": len(self._groups),
                "approver_ids": list(self._approvers.keys()),
                "group_ids": list(self._groups.keys()),
            }
