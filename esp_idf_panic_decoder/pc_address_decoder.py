# SPDX-FileCopyrightText: 2023 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from typing import Optional
import re
import subprocess

from .pc_address_matcher import PcAddressMatcher
from .output_helpers import red_print

# regex matches an potential address
ADDRESS_RE = re.compile(r'0x[0-9a-f]{8}', re.IGNORECASE)


class PcAddressDecoder:
    """
    Class for decoding possible addresses
    """

    def __init__(self, toolchain_prefix: str, elf_file: str, rom_elf_file: Optional[str] = None) -> None:
        self.toolchain_prefix = toolchain_prefix
        self.elf_file = elf_file
        self.rom_elf_file = rom_elf_file
        self.pc_address_buffer = b''
        self.pc_address_matcher = PcAddressMatcher(elf_file)
        if rom_elf_file is not None:
            self.rom_pc_address_matcher = PcAddressMatcher(rom_elf_file)

    def decode_address(self, line: bytes) -> str:
        """Decoded possible addresses in line"""
        line = self.pc_address_buffer + line
        self.pc_address_buffer = b''
        out = ''
        for match in re.finditer(ADDRESS_RE, line.decode(errors='ignore')):
            num = match.group()
            address_int = int(num, 16)
            translation = None

            # Try looking for the address in the app ELF file
            if self.pc_address_matcher.is_executable_address(address_int):
                translation = self.lookup_pc_address(num)
            # Not found in app ELF file, check ROM ELF file (if it is available)
            if translation is None and self.rom_elf_file is not None and \
            self.rom_pc_address_matcher.is_executable_address(address_int):
                translation = self.lookup_pc_address(num, is_rom=True)

            # Translation found either in the app or ROM ELF file
            if translation is not None:
                out += translation
        return out

    def lookup_pc_address(self, pc_addr: str, is_rom: bool = False) -> Optional[str]:
        """Decode address using addr2line tool"""
        elf_file: str = self.rom_elf_file if is_rom else self.elf_file  # type: ignore
        cmd = [f'{self.toolchain_prefix}addr2line', '-pfiaC', '-e', elf_file, pc_addr]

        try:
            translation = subprocess.check_output(cmd, cwd='.')
            if b'?? ??:0' not in translation:
                decoded = translation.decode()
                return decoded if not is_rom else decoded.replace('at ??:?', 'in ROM')
        except OSError as err:
            red_print(f'{" ".join(cmd)}: {err}')
        return None
