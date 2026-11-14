#!/usr/bin/env python3
"""Bounded terminal process-tree tests inside the CI terminal container."""
import asyncio
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest

import main as terminal


class TerminalRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-terminal-unit-")
        self.old_root = terminal.ARTIFACT_ROOT
        terminal.ARTIFACT_ROOT = Path(self.tmp.name)

    def tearDown(self):
        terminal.ARTIFACT_ROOT = self.old_root
        self.tmp.cleanup()

    def req(self, name="run.py", code="print('ok')\n", command=None, timeout=5):
        return terminal.ExecuteRequest(
            filename=name, content=code, command=command, timeout_sec=timeout
        )

    @staticmethod
    def running(pid):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            return stat.split(") ", 1)[1].split()[0] not in ("Z", "X")
        except FileNotFoundError:
            return False

    async def test_filename_is_not_interpreted_by_shell(self):
        out = await terminal.execute(self.req(
            "name $(touch bad).py", "print('safe-file')\n"
        ))
        self.assertEqual(out.exit_code, 0)
        self.assertIn("safe-file", out.stdout)
        self.assertFalse((terminal.ARTIFACT_ROOT / "bad").exists())

    async def test_large_stdout_and_stderr_are_bounded(self):
        out = await terminal.execute(self.req(
            "output.py", "import sys;print('z'*2000000);print('q'*2000000,file=sys.stderr)\n"
        ))
        self.assertEqual(out.exit_code, 0)
        self.assertLessEqual(len(out.stdout), 8000)
        self.assertLessEqual(len(out.stderr), 4000)

    async def test_large_source_is_rejected_before_write(self):
        with self.assertRaises(terminal.HTTPException) as ctx:
            await terminal.execute(self.req("big.py", "x" * (terminal.MAX_SOURCE_BYTES + 1)))
        self.assertEqual(ctx.exception.status_code, 413)
        self.assertFalse((terminal.ARTIFACT_ROOT / "big.py").exists())

    def child_command(self, pidfile):
        code = (
            "import subprocess,sys,time,pathlib;"
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
            f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid));"
            "time.sleep(30)"
        )
        return "python -c " + shlex.quote(code)

    async def assert_child_terminated(self, pidfile):
        self.assertTrue(pidfile.exists())
        pid = int(pidfile.read_text())
        for _ in range(30):
            if not self.running(pid):
                break
            await asyncio.sleep(0.1)
        self.assertFalse(self.running(pid), f"child survived cleanup: {pid}")

    async def test_timeout_kills_child_process_group(self):
        pidfile = terminal.ARTIFACT_ROOT / "child.pid"
        out = await terminal.execute(self.req(
            "timeout.py", "pass\n", self.child_command(pidfile), timeout=1
        ))
        self.assertEqual(out.exit_code, 124)
        self.assertIn("TIMEOUT", out.stderr)
        await self.assert_child_terminated(pidfile)

    async def test_cancel_kills_child_process_group(self):
        pidfile = terminal.ARTIFACT_ROOT / "cancel.pid"
        task = asyncio.create_task(terminal.execute(self.req(
            "cancel.py", "pass\n", self.child_command(pidfile), timeout=20
        )))
        try:
            for _ in range(40):
                if pidfile.exists():
                    break
                await asyncio.sleep(0.05)
            self.assertTrue(pidfile.exists())
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        await self.assert_child_terminated(pidfile)

    async def test_nonzero_exit_and_stderr_retained(self):
        out = await terminal.execute(self.req(
            "failure.py", "import sys;sys.stderr.write('intentional');sys.exit(7)\n"
        ))
        self.assertEqual(out.exit_code, 7)
        self.assertIn("intentional", out.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
