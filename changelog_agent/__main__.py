"""Allow `python3 -m changelog_agent` to run the CLI."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
