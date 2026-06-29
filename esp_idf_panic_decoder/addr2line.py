# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0
"""Persistent addr2line subprocess pool.

addr2line is slow to start (loads and indexes the ELF) but fast once running, so
we keep one subprocess alive per ELF file and feed it addresses on stdin. To
insulate the build from our open file handle — Windows can block the linker from
rewriting an open ELF, and Unix would otherwise let addr2line keep reading the
stale ELF after a rebuild — each subprocess actually opens a temp copy. On every
lookup we stat the original (mtime, size) and respawn against a fresh copy if it
has changed, so a rebuild during a monitor session is picked up automatically.
"""
import atexit
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from esp_pylib.logger import log
from rich.markup import escape

# Sentinel written after each request so we know where the response ends.
# 0xfefefefe is a classic uninit-memory marker, well outside any ESP code region,
# so it will not pass PcAddressMatcher.is_executable_address and cannot collide
# with a real lookup. The regex matches the full 3-line sentinel response
# atomically (echoed address + ?? + ??:0), tolerating leading zero padding when
# addr2line widens to the ELF pointer width (e.g. `0x00000000fefefefe` on a
# 64-bit target).
_SENTINEL_INPUT = '0xfefefefe'
_SENTINEL_RE = re.compile(r'0x0*fefefefe\r?\n\?\?\r?\n\?\?:0\r?\n')

# Matches `<path>:<line>` in addr2line output, ignoring `(discriminator N)` suffixes.
_FILE_LINE_RE = re.compile(r'(?P<file>.*):(?P<line>\d+|\?)(?: \(discriminator \d+\))?$')

# (func, path, line) — raw frame as parsed from addr2line, no presentation transforms.
Frame = Tuple[str, str, str]


@dataclass
class _Process:
    proc: subprocess.Popen
    temp_path: str
    mtime: float
    size: int


class Addr2LineRunner:
    """Pool of persistent `addr2line` subprocesses, keyed by ELF path.

    Each lookup writes one address plus a sentinel to the matching subprocess's
    stdin and reads frames back until the sentinel echo terminates the response.
    Returns raw `(func, path, line)` tuples; callers apply any presentation
    transforms (e.g. rewriting `??` to `'ROM'` for ROM ELFs).
    """

    def __init__(self, toolchain_prefix: str) -> None:
        self._toolchain_prefix = toolchain_prefix
        self._processes: Dict[str, _Process] = {}
        self._temp_dir: Optional[str] = None
        atexit.register(self.close)

    def lookup(self, address: str, elf_file: str) -> Optional[List[Frame]]:
        """Translate one address using a persistent addr2line for `elf_file`.

        :return: List of `(func, path, line)` frames (multiple entries indicate
                 inlined functions), or `None` if addr2line could not resolve
                 the address (every entry was `??/??`).
        """
        proc = self._get_process(elf_file)
        if proc is not None and proc.stdin is not None and proc.stdout is not None:
            try:
                proc.stdin.write(f'{address}\n{_SENTINEL_INPUT}\n')
                proc.stdin.flush()
                buf = ''
                while True:
                    line = proc.stdout.readline()
                    if line == '':
                        raise BrokenPipeError('addr2line closed stdout unexpectedly')
                    buf += line
                    match = _SENTINEL_RE.search(buf)
                    if match:
                        return _parse_frames(buf[:match.start()])
            except (BrokenPipeError, OSError, RuntimeError) as err:
                log.err(f'{escape(self._toolchain_prefix)}addr2line ({escape(elf_file)}): {escape(str(err))}')
                entry = self._processes.pop(elf_file, None)
                if entry is not None:
                    _terminate(entry)

        # One-shot fallback (also the path when spawning failed).
        cmd = [f'{self._toolchain_prefix}addr2line', '-fiaC', '-e', elf_file, address]
        try:
            output = subprocess.check_output(cmd, cwd='.')
        except OSError as err:
            log.err(f"{escape(' '.join(cmd))}: {escape(str(err))}")
            return None
        except subprocess.CalledProcessError as err:
            log.err(f"{escape(' '.join(cmd))}: {escape(str(err))}")
            log.err('ELF file is missing or has changed, the build folder was probably modified.')
            return None
        return _parse_frames(output.decode(errors='ignore'))

    def close(self) -> None:
        """Terminate all cached subprocesses and remove the temp directory."""
        for entry in list(self._processes.values()):
            _terminate(entry)
        self._processes.clear()
        if self._temp_dir is not None:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    def __enter__(self) -> 'Addr2LineRunner':
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _get_process(self, elf_file: str) -> Optional[subprocess.Popen]:
        entry = self._processes.get(elf_file)
        if entry is not None:
            stat = _stat_or_none(elf_file)
            stale = stat is not None and (stat[0] != entry.mtime or stat[1] != entry.size)
            died = entry.proc.poll() is not None
            if stale or died:
                _terminate(entry)
                self._processes.pop(elf_file, None)
                entry = None
        if entry is None:
            entry = self._spawn(elf_file)
            if entry is not None:
                self._processes[elf_file] = entry
        return entry.proc if entry is not None else None

    def _spawn(self, elf_file: str) -> Optional[_Process]:
        stat = _stat_or_none(elf_file)
        if stat is None:
            log.err(f'{escape(elf_file)}: file not found')
            return None

        try:
            if self._temp_dir is None:
                self._temp_dir = tempfile.mkdtemp(prefix='esp-idf-panic-decoder-')
            base = os.path.basename(elf_file) or 'elf'
            fd, temp_path = tempfile.mkstemp(prefix=f'{base}.', dir=self._temp_dir)
            os.close(fd)
            shutil.copy2(elf_file, temp_path)
        except OSError as err:
            log.err(f'{escape(elf_file)}: failed to copy for addr2line: {escape(str(err))}')
            return None

        cmd = [f'{self._toolchain_prefix}addr2line', '-fiaC', '-e', temp_path]
        try:
            # Deliberately not a context manager: the process outlives this call
            # and is closed by _terminate()/close().
            proc = subprocess.Popen(  # pylint: disable=consider-using-with
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                text=True,
                cwd='.',
            )
        except OSError as err:
            log.err(f"{escape(' '.join(cmd))}: {escape(str(err))}")
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            return None

        return _Process(proc=proc, temp_path=temp_path, mtime=stat[0], size=stat[1])


def _stat_or_none(elf_file: str) -> Optional[Tuple[float, int]]:
    try:
        st = os.stat(elf_file)
    except OSError:
        return None
    return (st.st_mtime, st.st_size)


def _terminate(entry: _Process) -> None:
    proc = entry.proc
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    except (OSError, ValueError):
        # Broken pipe on the final flush, or the stream was closed underneath us.
        pass
    try:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
    except OSError:
        # Already reaped, or we lost the right to signal it.
        pass
    try:
        os.unlink(entry.temp_path)
    except OSError:
        pass


def _parse_frames(output: str) -> Optional[List[Frame]]:
    """Parse the addr2line response for a single address.

    The first line is the echoed address (discarded — caller knows what it sent).
    The remaining lines are `(func, file:line)` pairs, one per stack frame
    (1 + inlines). Returns None when every entry is `??/??`.
    """
    lines = [ln for ln in output.split('\n') if ln != '']
    if len(lines) < 3:
        return None

    frames: List[Frame] = []
    valid = False
    for func, path_line in zip(map(str.strip, lines[1::2]), map(str.strip, lines[2::2])):
        match = _FILE_LINE_RE.match(path_line)
        path = match.group('file') if match else path_line
        line = match.group('line') if match else ''
        valid = valid or func != '??' or path != '??'
        frames.append((func, path, line))

    return frames if valid and frames else None
