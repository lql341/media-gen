#!/usr/bin/env python3
"""media-gen configuration entry point.

Implementation lives in the :mod:`mediaconfig` package (paths / profiles / store /
probe / cli); this module stays as the stable import path and the CLI entry:

    import media_config as config   # media.py, wizard.py, mcp_server.py
    python3 scripts/media_config.py add <name> --protocol openai --base-url <url>
"""

from __future__ import annotations

import sys

from mediaconfig import *  # noqa: F401,F403
from mediaconfig import main

if __name__ == "__main__":
    sys.exit(main())
