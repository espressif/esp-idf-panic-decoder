# SPDX-FileCopyrightText: 2023 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0
from dataclasses import dataclass
from typing import List, Optional, Union, Dict, Tuple
import re
import subprocess

from .pc_address_matcher import PcAddressMatcher
from .output_helpers import red_print

# regex matches an potential address
ADDRESS_RE = re.compile(r'0x[0-9a-f]{8}', re.IGNORECASE)

# regex to split address sections in addr2line output (lookahead to preserve address when splitting)
ADDR2LINE_ADDRESS_LOOKAHEAD_RE = re.compile(r'(?=0x[0-9a-f]{8}\r?\n)')
# regex matches filename and line number in addr2line output (and ignores discriminators)
ADDR2LINE_FILE_LINE_RE = re.compile(r'(?P<file>.*):(?P<line>\d+|\?)(?: \(discriminator \d+\))?$')

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
        # We parse them all and filter out those that are not considered executable by one of the configured ELF files.

        # Find all hex addresses (0x40376121, 0x3fcb5590, etc.)
        addresses = re.findall(ADDRESS_RE, line)
        if not addresses:
            return []

        # Addresses left to find (initially a copy of addresses: 0x40376121, 0x3fcb5590, etc.)
        remaining = addresses.copy()

        # Mapped addresses (0x40376121 => [(func, path, line), ...])
        mapped: Dict[str, List[PcAddressLocation]] = {}

        # Iterate through available ELF files
        for matcher in self.pc_address_matcher:
            elf_path = matcher.elf_path
            is_rom = elf_path == self.rom_elf_file

            # Find any remaining addresses that are executable in this ELF file
            elf_addresses = [addr for addr in remaining if matcher.is_executable_address(int(addr, 16))]
            if not elf_addresses:
                continue

            # Translate addresses using addr2line
            elf_mapped = self.perform_addr2line(addresses=elf_addresses, elf_file=elf_path, is_rom=is_rom)

            # Update shared mapped addresses
            mapped.update(elf_mapped)

            # Stop searching for addresses that have been found (even if they may exist in other ELF files)
            remaining = [addr for addr in remaining if addr not in elf_mapped]

            # If there are no remaining addresses, we can stop looking through ELF files
            if not remaining:
                break

        # All discovered and translated addresses are now in `mapped`, but they are ordered based on the ELF files.
        # Recreate the original order of `addresses`, allowing also for multiple instances of the same address.
        # [(0x40376121, [(func, path, line), ...]), ...]
        return [(addr, mapped[addr]) for addr in addresses if addr in mapped]

    def perform_addr2line(
        self,
        addresses: List[str],
        elf_file: str,
        is_rom: bool = False,
    ) -> Dict[str, List[PcAddressLocation]]:
        """
        Translate a list of executable addresses to source locations using addr2line.
        :param addresses: List of addresses to translate.
        :param elf_file: The ELF file eto use for translating.
        :param is_rom: If True, replace '??' paths with 'ROM' as paths are not available from ROM ELF files.
        :return: Map from each address to a list of its source locations (with multiple indicating an inlined function).
        """
        cmd = [f'{self.toolchain_prefix}addr2line', '-fiaC', '-e', elf_file, *addresses]

        try:
            batch_output = subprocess.check_output(cmd, cwd='.')
        except OSError as err:
            red_print(f'{" ".join(cmd)}: {err}')
            return {}
        except subprocess.CalledProcessError as err:
            red_print(f'{" ".join(cmd)}: {err}')
            red_print('ELF file is missing or has changed, the build folder was probably modified.')
            return {}

        decoded_output = batch_output.decode(errors='ignore')

        return PcAddressDecoder.parse_addr2line_output(decoded_output, is_rom=is_rom)

    @staticmethod
    def parse_addr2line_output(
        output: str,
        is_rom: bool = False,
    ) -> Dict[str, List[PcAddressLocation]]:
        """
        Parse the output of addr2line.
        :param output: The output of addr2line as a string.
        :param is_rom: If True, replace '??' paths with 'ROM' as paths are not available from ROM ELF files.
        :return: Map from each address to a list of its source locations (with multiple indicating an inlined function).
        """

        # == addr2line output example ==
        # 0xabcd1234  # Aad # First input address
        # foo()       # A0f # Function
        # foo.c:123   # A0p # Source location
        # 0x1234abcd  # Bad # Second input address
        # inlined()   # B0f # Inlined function
        # bar.c:456   # B0p # Source location
        # bar()       # B1f # Function which inlined inlined()
        # bar.c:789   # B1p # Source location
        # ...         # ... # ... more entries

        # Step 1: Split into sections representing each address and its trace (A**, B**)
        sections = re.split(ADDR2LINE_ADDRESS_LOOKAHEAD_RE, output)

        result: Dict[str, List[PcAddressLocation]] = {}
        for section in sections:
            section = section.strip() # Remove trailing newline
            if not section:
                continue

            # Step 2: Split the section by newlines (Aad, A0f, A0p)
            lines = section.split('\n')

            # Step 3: First line is the address (Aad)
            address = lines[0].strip()

            # Step 4: Build trace by consuming lines in pairs (A0f + A0p)
            #         Multiple entries indicate inlined functions (B0f + B0p, B1f + B1p, etc.)
            trace: List[PcAddressLocation] = []
            valid = False
            for func, path_line in zip(map(str.strip, lines[1::2]), map(str.strip, lines[2::2])):
                path_match = ADDR2LINE_FILE_LINE_RE.match(path_line)
                path = path_match.group('file') if path_match else path_line
                line = path_match.group('line') if path_match else ''

                # If any entry's function or path are present the trace is valid
                # Otherwise if none of the entries are valid, we skip this address
                valid = valid or func != '??' or path != '??'

                # ROM ELF files do not provide paths, so we replace '??' with 'ROM'
                if path == '??' and is_rom:
                    path = 'ROM'

                # Add the trace entry
                trace.append(PcAddressLocation(func, path, line))

            # Step 5: Store the address and its trace in result (if valid and contains entries), go to next section
            if valid and trace:
                result[address] = trace

        return result
