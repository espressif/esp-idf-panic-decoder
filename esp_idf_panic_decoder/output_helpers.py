# SPDX-FileCopyrightText: 2023 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0

from typing import Optional
import sys


ANSI_RED = '\033[1;31m'
ANSI_NORMAL = '\033[0m'


def red_print(message: str, newline: Optional[str] = '\n') -> None:
    """Print message in red color to stderr"""
    sys.stderr.write(f'{ANSI_RED}{message}{ANSI_NORMAL}{newline}')
    sys.stderr.flush()
