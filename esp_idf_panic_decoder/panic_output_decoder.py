# SPDX-FileCopyrightText: 2023 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
import sys
import tempfile
from .output_helpers import red_print


class PanicOutputDecoder:
    """Wrapper class for gdb_panic_server"""

    def __init__(self, toolchain_prefix: str, elf_file: str, target: str) -> None:
        self.toolchain_prefix = toolchain_prefix
        self.elf_file = elf_file
        self.target = target

    def process_panic_output(self, panic_output: bytes) -> bytes:
        """Run gdb_panic_server as subprocess and decode the panic output"""
        panic_output_file = None
        try:
            # On Windows, the temporary file can't be read unless it is closed.
            # Set delete=False and delete the file manually later.
            with tempfile.NamedTemporaryFile(mode='wb', delete=False) as panic_output_file:
                panic_output_file.write(panic_output)
                panic_output_file.flush()
            cmd = [
                self.toolchain_prefix + 'gdb', '--batch', '-n', self.elf_file, '-ex',
                f'target remote | "{sys.executable}" -m esp_idf_panic_decoder '
                f'--target {self.target} "{panic_output_file.name}"',
                '-ex', 'bt'
            ]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return output
        finally:
            if panic_output_file is not None:
                try:
                    os.unlink(panic_output_file.name)
                except OSError as err:
                    red_print(f"Couldn't remove temporary panic output file ({err})")
