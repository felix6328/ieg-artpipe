"""Run trusted Blender scripts in interruptible, isolated job directories."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import which
from time import monotonic
import json
import os
import signal
import subprocess

from .storage import confined

SCRIPT = Path(__file__).with_name("blender_script.py")


class BlenderError(RuntimeError):
    """Blender could not complete the requested operation."""

    def __init__(self, message, *, parse_failed=False):
        super().__init__(message)
        self.parse_failed = parse_failed


class JobCanceled(RuntimeError):
    """The worker was asked to cancel the active job."""


@dataclass(frozen=True)
class Job:
    directory: Path

    @property
    def input(self):
        return self.directory / "input"

    @property
    def output(self):
        return self.directory / "output"

    def prepare(self):
        for folder in (self.input, self.output, self.directory / "logs", self.directory / "runtime"):
            folder.mkdir(parents=True, exist_ok=True)


def detect_blender():
    """Resolve the configured executable or common local installations."""
    configured = os.environ.get("ASSETGATE_BLENDER")
    candidates = [configured] if configured else [
        which("blender"), "/Applications/Blender.app/Contents/MacOS/Blender",
    ]
    for candidate in filter(None, candidates):
        found = which(candidate)
        if found:
            return Path(found).resolve()
    return None


class BlenderAdapter:
    """Exchange JSON with Blender. Each command owns a process group and logs."""

    mode = "BLENDER"

    def __init__(self, binary, config):
        self.binary = Path(binary) if binary else None
        self.config = config["blender"]
        self.worker_lock_fd = None

    def get_blender_version(self):
        if self.binary is None:
            raise BlenderError("未找到 Blender，请设置 ASSETGATE_BLENDER")
        result = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True,
                                errors="replace", check=False, timeout=self.config["probe_seconds"])
        if result.returncode:
            raise BlenderError(f"无法读取 Blender 版本，退出码 {result.returncode}")
        return result.stdout.splitlines()[0] if result.stdout else "Blender"

    def probe(self, job, canceled=lambda: False):
        return self._execute(job, "probe", canceled, timeout=self.config["probe_seconds"])

    def import_model(self, job, source, canceled, *, stage="import"):
        return self._execute(job, stage, canceled, action="inspect", source=self._input(job, source))

    def inspect_model(self, job, source, canceled, *, stage="inspect", preview=None, area_epsilon=1e-12):
        path = self._output(job, preview) if preview else None
        return self._execute(job, stage, canceled, action="inspect", source=self._input(job, source),
                             preview=path, area_epsilon=area_epsilon)

    def process_model(self, job, source, target, operation, settings, canceled):
        return self._execute(job, operation, canceled, action="process", source=self._input(job, source),
                             target=self._output(job, target), operation=operation, settings=settings)

    def export_model(self, job, source, target, canceled, *, stage="convert"):
        return self._execute(job, stage, canceled, action="export", source=self._input(job, source),
                             target=self._output(job, target))

    @staticmethod
    def _input(job, source):
        source = Path(source).resolve()
        if not source.is_relative_to(job.directory.resolve()) or not source.is_file():
            raise BlenderError("输入模型必须位于任务目录内")
        return str(source)

    @staticmethod
    def _output(job, target):
        return str(confined(job.output, str(target)))

    def _execute(self, job, stage, canceled, *, action=None, timeout=None, **params):
        if canceled():
            raise JobCanceled()
        if self.binary is None:
            raise BlenderError("未找到 Blender，请设置 ASSETGATE_BLENDER")
        job.prepare()
        log_dir = job.directory / "logs"
        request = log_dir / f"{stage}.request.json"
        result = log_dir / f"{stage}.result.json"
        result.unlink(missing_ok=True)
        request.write_text(json.dumps({"action": action or stage, "result": str(result),
                                       "root": str(job.directory), **params}), encoding="utf-8")
        runtime = job.directory / "runtime"
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL")
               if key in os.environ}
        env.update({"BLENDER_USER_RESOURCES": str(runtime), "HOME": str(runtime), "TMPDIR": str(runtime)})
        argv = [str(self.binary), "--background", "--factory-startup", "--disable-autoexec",
                "--python-exit-code", "7", "--python", str(SCRIPT), "--", str(request)]
        deadline = monotonic() + (timeout or self.config["timeout_seconds"])
        try:
            with ((log_dir / f"{stage}.stdout.log").open("wb") as stdout,
                  (log_dir / f"{stage}.stderr.log").open("wb") as stderr):
                process = subprocess.Popen(argv, cwd=job.directory, env=env, stdout=stdout,
                                           stderr=stderr, start_new_session=True,
                                           pass_fds=() if self.worker_lock_fd is None else (self.worker_lock_fd,))
                try:
                    while True:
                        if canceled():
                            raise JobCanceled()
                        remaining = deadline - monotonic()
                        if remaining <= 0:
                            raise BlenderError(f"Blender 操作超时（{stage}）")
                        try:
                            code = process.wait(timeout=min(remaining, 0.2))
                            break
                        except subprocess.TimeoutExpired:
                            continue
                finally:
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
        except OSError as exc:
            raise BlenderError(f"无法启动或控制 Blender：{exc}") from exc
        if canceled():
            raise JobCanceled()
        try:
            value = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        if code:
            info = tail(log_dir / f"{stage}.stderr.log") or tail(log_dir / f"{stage}.stdout.log")
            raise BlenderError(f"Blender {stage} 退出码 {code}\n{value.get('error') or info}",
                               parse_failed=value.get("parse_failed", False))
        if not value.get("ok"):
            raise BlenderError(value.get("error", f"Blender {stage} 缺少有效输出"),
                               parse_failed=value.get("parse_failed", False))
        return value


def tail(path, limit=3500):
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - limit))
        return stream.read(limit).decode("utf-8", "replace").strip()
