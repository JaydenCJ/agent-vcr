"""Allow ``python -m agent_vcr`` as an equivalent of the ``agent-vcr`` script."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
