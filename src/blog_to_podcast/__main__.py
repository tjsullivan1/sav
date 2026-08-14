"""CLI entry point that launches the Streamlit app."""

from __future__ import annotations

import sys
from pathlib import Path

APP_PATH = Path(__file__).parent / "app.py"


def main() -> int:
    """Launch the Streamlit server for the blog-to-podcast app."""
    from streamlit.web import cli as stcli

    sys.argv = ["streamlit", "run", str(APP_PATH), *sys.argv[1:]]
    return stcli.main()  # type: ignore[no-any-return]


if __name__ == "__main__":
    raise SystemExit(main())
