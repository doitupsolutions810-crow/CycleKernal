#!/usr/bin/env python3
"""Agent artifact path traversal, symlink and atomic-write regressions."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

import agents.artifact as artifact
from agents.path_safety import artifact_directory, write_artifact


STARTED = datetime.utcnow()


class FixedClock:
    @staticmethod
    def utcnow():
        return STARTED


class ArtifactPathTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-agent-artifact-")
        self.base = Path(self.tmp.name)
        self.root = self.base / "artifacts"
        self.root.mkdir()
        self.run_id = STARTED.strftime("%Y%m%dT%H%M%S")
        self.root_patch = patch.object(artifact, "ARTIFACT_ROOT", self.root)
        self.clock_patch = patch.object(artifact, "datetime", FixedClock)
        self.mood_patch = patch.object(artifact.ArtifactAgent, "current_mood",
                                       new=AsyncMock(return_value={"mood": "neutral"}))
        for patcher in (self.root_patch, self.clock_patch, self.mood_patch):
            patcher.start()

    def tearDown(self):
        for patcher in (self.mood_patch, self.clock_patch, self.root_patch):
            patcher.stop()
        self.tmp.cleanup()

    async def run_artifact(self, task):
        return await artifact.ArtifactAgent().run(task)

    async def test_nested_artifact_content_and_manifest_digest(self):
        result = await self.run_artifact({
            "name": "safe_pkg",
            "files": [{"path": "nested/good.py", "content": "print('ok')\n"}],
        })
        self.assertTrue(result.success)
        dest = self.root / self.run_id / "safe_pkg"
        self.assertEqual((dest / "nested/good.py").read_text(), "print('ok')\n")
        manifest = json.loads((dest / "manifest.json").read_text())
        self.assertEqual(manifest["files"][0]["sha256"],
                         hashlib.sha256(b"print('ok')\n").hexdigest())
        self.assertEqual(manifest["entry"], "nested/good.py")

    async def test_unsafe_artifact_identifiers_rejected(self):
        for name in ("../outside", "/tmp/outside", "foo/bar", ".", "..",
                     "bad\\path", "a" * 100, "foo..bar", "has space"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    await self.run_artifact({"name": name, "files": [
                        {"path": "good.txt", "content": "bad write"},
                    ]})
        self.assertFalse((self.base / "outside").exists())

    async def test_invalid_file_paths_are_never_silently_rewritten(self):
        for path in ("../outside", "/tmp/outside", "nested/../../outside",
                     "nested//file.txt", "nested/./file.txt", "bad\\path",
                     "nested/\x00bad"):
            with self.subTest(path=repr(path)):
                with self.assertRaises(ValueError):
                    await self.run_artifact({
                        "name": "unsafe_files",
                        "files": [{"path": path, "content": "must-not-write"}],
                    })
        self.assertFalse((self.base / "outside").exists())

    async def test_symlink_leaf_cannot_overwrite_external_file(self):
        outside = self.base / "outside.txt"
        outside.write_text("untouched")
        target = self.root / self.run_id / "leaf_case"
        target.mkdir(parents=True)
        (target / "evil.txt").symlink_to(outside)
        with self.assertRaises(ValueError):
            await self.run_artifact({
                "name": "leaf_case",
                "files": [{"path": "evil.txt", "content": "overwritten"}],
            })
        self.assertEqual(outside.read_text(), "untouched")

    async def test_symlink_parent_cannot_write_outside(self):
        outside_dir = self.base / "external-dir"
        outside_dir.mkdir()
        target = self.root / self.run_id / "parent_case"
        target.mkdir(parents=True)
        (target / "linked").symlink_to(outside_dir, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            await self.run_artifact({
                "name": "parent_case",
                "files": [{"path": "linked/file.txt", "content": "overwritten"}],
            })
        self.assertFalse((outside_dir / "file.txt").exists())

    async def test_symlink_artifact_directory_is_rejected(self):
        outside_dir = self.base / "external-root"
        outside_dir.mkdir()
        parent = self.root / self.run_id
        parent.mkdir(parents=True)
        (parent / "redirect_case").symlink_to(outside_dir, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            await self.run_artifact({
                "name": "redirect_case",
                "files": [{"path": "file.txt", "content": "overwritten"}],
            })
        self.assertFalse((outside_dir / "file.txt").exists())

    async def test_nontext_file_content_rejected(self):
        with self.assertRaises(ValueError):
            await self.run_artifact({
                "name": "nontext_case",
                "files": [{"path": "file.txt", "content": 99}],
            })

    async def test_parallel_atomic_writes_leave_no_partial_output(self):
        values = [f"revision-{i}:" + "x" * 40000 for i in range(12)]
        with artifact_directory(self.root, self.run_id, "atomic_case") as (dest, directory_fd):
            lengths = await asyncio.gather(*[
                asyncio.to_thread(write_artifact, directory_fd, "shared.txt", value)
                for value in values
            ])
            self.assertEqual(lengths, [len(x.encode()) for x in values])
            self.assertIn((dest / "shared.txt").read_text(), values)
            self.assertFalse(list(dest.glob(".ck-write-*")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
