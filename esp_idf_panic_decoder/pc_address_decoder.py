# SPDX-FileCopyrightText: 2023 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from .addr2line import Addr2LineRunner
from .pc_address_matcher import PcAddressMatcher

# regex matches an potential address
ADDRESS_RE = re.compile(r'0x[0-9a-f]{8}', re.IGNORECASE)


# Decoded PC address trace
@dataclass
class PcAddressLocation:
    func: str
    path: str
    line: str


class PcAddressDecoder:
    """
    Class for decoding possible addresses
    """

    def __init__(
        self, toolchain_prefix: str, elf_file: Union[List[str], str], rom_elf_file: Optional[str] = None
    ) -> None:
        self.toolchain_prefix = toolchain_prefix
        self.elf_files = elf_file if isinstance(elf_file, list) else [elf_file]
        self.rom_elf_file = rom_elf_file
        self.pc_address_matcher = [PcAddressMatcher(file) for file in self.elf_files]
        if self.rom_elf_file:
            self.pc_address_matcher.append(PcAddressMatcher(self.rom_elf_file))

        self._addr2line = Addr2LineRunner(toolchain_prefix)

    def close(self) -> None:
        """Terminate any cached addr2line subprocesses. Optional — atexit will handle it otherwise."""
        self._addr2line.close()

    def __enter__(self) -> 'PcAddressDecoder':
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def decode_address(self, line: bytes) -> str:
        """
        Find executable addresses in a line and translate them to source locations using addr2line.
        **Deprecated**: Method preserved for esp-idf-monitor < 1.7 compatibility - use `translate_addresses` instead.
        :return: A string containing human-readable addr2line output for the addresses found in the line.
        """

        # Translate any addresses found in the line to their source locations
        decoded = self.translate_addresses(line.decode(errors='ignore'))
        if not decoded:
            return ''

        # Synthesize the output of addr2line --pretty-print, while preserving improvements from translate_addresses
        # which relies on the non pretty-print output of addr2line.

        # `decoded` contains [(0x40376121, [(func, path, line), ...]), ...]
        # Which gets converted to:
        # 0x40376121: func at path:line

        def format_trace_entry(location: PcAddressLocation):
            if location.path == 'ROM':
                return f'{location.func} in ROM'

            return f'{location.func} at {location.path}' + (f':{location.line}' if location.line else '')

        out = ''
        # For each address and its corresponding trace
        for addr, trace in decoded:
            # Append address
            out += f'{addr}: '
            if not trace:
                out += '(unknown)\n'
                continue

            # Append first trace entry
            out += f'{format_trace_entry(trace[0])}\n'

            # Any subsequent entries indicate inlined functions
            for entry in trace[1:]:
                out += f' (inlined by) {format_trace_entry(entry)}\n'

        return out

    def translate_addresses(self, line: str) -> List[Tuple[str, List[PcAddressLocation]]]:
        """
        Find executable addresses in a line and translate them to source locations using addr2line.
        :param line: The line to decode, as a string.
        :return: List of addresses and their source locations (with multiple locations indicating an inlined function).
        """

        # === Example input line ===
        # Backtrace: 0x40376121:0x3fcb5590 0x40384ef9:0x3fcb55b0 0x4202c8c9:0x3fcb55d0
        # Each pair represents a program counter (PC) address and a stack pointer (SP) address.
        # We parse them and look them up in the first ELF that owns them.

        addresses = [a.lower() for a in re.findall(ADDRESS_RE, line)]
        if not addresses:
            return []

        out: List[Tuple[str, List[PcAddressLocation]]] = []
        for addr in addresses:
            for matcher in self.pc_address_matcher:
                if not matcher.is_executable_address(int(addr, 16)):
                    continue
                is_rom = matcher.elf_path == self.rom_elf_file
                trace = self.lookup_address(addr, matcher.elf_path, is_rom=is_rom)
                if trace is not None:
                    out.append((addr, trace))
                    # Stop at the first ELF that owns this address.
                    break
        return out

    def lookup_address(
        self,
        address: str,
        elf_file: str,
        is_rom: bool = False,
    ) -> Optional[List[PcAddressLocation]]:
        """
        Translate one executable address to a source location trace using a persistent addr2line.
        :param address: The address to translate (e.g. '0x40376121').
        :param elf_file: The ELF file to use for translating.
        :param is_rom: If True, replace '??' paths with 'ROM' as paths are not available from ROM ELF files.
        :return: List of source locations (with multiple indicating an inlined function), or None if
                 addr2line could not resolve the address (all entries are ??/??).
        """
        frames = self._addr2line.lookup(address, elf_file)
        if frames is None:
            return None
        return [
            PcAddressLocation(func, 'ROM' if is_rom and path == '??' else path, line)
            for func, path, line in frames
        ]

    def perform_addr2line(
        self,
        addresses: List[str],
        elf_file: str,
        is_rom: bool = False,
    ) -> Dict[str, List[PcAddressLocation]]:
        """
        Translate a list of executable addresses to source locations using addr2line.
        Thin batched wrapper over :py:meth:`lookup_address` — kept for backwards compatibility.
        :param addresses: List of addresses to translate.
        :param elf_file: The ELF file to use for translating.
        :param is_rom: If True, replace '??' paths with 'ROM' as paths are not available from ROM ELF files.
        :return: Map from each resolved address to its trace (unresolved addresses are omitted).
        """
        out: Dict[str, List[PcAddressLocation]] = {}
        for addr in addresses:
            trace = self.lookup_address(addr, elf_file, is_rom=is_rom)
            if trace is not None:
                out[addr] = trace
        return out
