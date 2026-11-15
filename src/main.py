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
    parser.add_argument("--host", default="0.0.0.0", help="Bind host address")
    parser.add_argument("--port", type=int, default=8020, help="HTTP/WebSocket server port")
    parser.add_argument("--lang", default="de", choices=["de", "en"], help="Default language")
    parser.add_argument("--simulation", action="store_true", help="Run with simulated hardware fallbacks")
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """Launch the FastAPI daemon server."""
    args = build_arg_parser().parse_args(argv)
    config = AlfredConfig(
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

