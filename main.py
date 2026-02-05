#!/usr/bin/env python3
# Copyright (c) 2026 Dedalus Labs, Inc. and its contributors
# SPDX-License-Identifier: MIT

"""Linear MCP Server entry point."""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from server import main

if __name__ == "__main__":
    asyncio.run(main())
