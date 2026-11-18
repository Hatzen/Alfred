"""CLI and daemon entrypoint for the Alfred AI Assistant."""

from __future__ import annotations

import argparse
from typing import List, Optional

import uvicorn

from src.brain.assistant import AlfredAssistant
from src.config import AlfredConfig
from src.web.server import create_app


def build_arg_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser for starting the Alfred daemon."""
    parser = argparse.ArgumentParser(description="Start the Alfred AI Assistant daemon.")
    parser.add_argument("--env-file", default=".env", help="Path to .env configuration file")
    parser.add_argument("--host", default=None, help="Bind host address (overrides .env)")
    parser.add_argument("--port", type=int, default=None, help="HTTP/WebSocket port (overrides .env)")
    parser.add_argument("--lang", default=None, choices=["de", "en"], help="Default language (overrides .env)")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--production",
        dest="simulation",
        action="store_false",
        default=None,
        help="Run with real host audio hardware & live backends (overrides ALFRED_SIMULATION)",
    )
    mode_group.add_argument(
        "--simulation",
        dest="simulation",
        action="store_true",
        help="Run with simulated hardware fallbacks (overrides ALFRED_SIMULATION)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """Launch the FastAPI daemon server."""
    args = build_arg_parser().parse_args(argv)
    config = AlfredConfig.from_env(
        env_file=args.env_file,
        override=True,
        host=args.host,
        port=args.port,
        default_language=args.lang,
        simulation_mode=args.simulation,
    )
    assistant = AlfredAssistant(config=config)
    app = create_app(assistant=assistant)
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
