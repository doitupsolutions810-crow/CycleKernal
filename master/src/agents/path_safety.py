"""Fail-closed, Linux dirfd-based artifact path and atomic-write helpers."""
from __future__ import annotations

import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}\Z")


def validate_name(value: str) -> str:
    """Accept a single portable artifact identifier, not a path."""
    if (not isinstance(value, str) or not _NAME.fullmatch(value)
            or value in (".", "..") or ".." in value):
        raise ValueError("invalid artifact identifier")
    return value


def validate_relative_path(path: str) -> tuple[str, ...]:
    if (not isinstance(path, str) or not path or len(path) > 512
            or path.startswith("/") or "\\" in path or "\x00" in path):
        raise ValueError("invalid relative artifact path")
    parts = tuple(path.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("invalid relative artifact path")
    return parts


@contextmanager
def artifact_directory(root: Path, run_id: str, name: str) -> Iterator[tuple[Path, int]]:
    """Create a unique run directory without following intermediate symlinks."""
    validate_name(run_id)
    validate_name(name)
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(root), _DIR_FLAGS)
    try:
        for component in (run_id, name):
            try:
                os.mkdir(component, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            next_fd = os.open(component, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield root / run_id / name, fd
    finally:
        os.close(fd)


def write_artifact(dir_fd: int, relative: str, content: str) -> int:
    """Install text atomically beneath an open artifact directory descriptor."""
    parts = validate_relative_path(relative)
    if not isinstance(content, str):
        raise ValueError("artifact content must be text")
    current = os.dup(dir_fd)
    temp = None
    try:
        for component in parts[:-1]:
            try:
                os.mkdir(component, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            child = os.open(component, _DIR_FLAGS, dir_fd=current)
            os.close(current)
            current = child
        try:
            previous = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
            if not stat.S_ISREG(previous.st_mode):
                raise ValueError("artifact destination must be a regular file")
        except FileNotFoundError:
            pass
        data = content.encode("utf-8")
        temp = ".ck-write-" + uuid.uuid4().hex
        output_fd = os.open(
            temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=current,
        )
        with os.fdopen(output_fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, parts[-1], src_dir_fd=current, dst_dir_fd=current)
        temp = None
        return len(data)
    finally:
        if temp:
            try:
                os.unlink(temp, dir_fd=current)
            except FileNotFoundError:
                pass
        os.close(current)
