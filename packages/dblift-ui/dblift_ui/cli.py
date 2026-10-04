"""The ``ui`` command: start the local server and open the browser."""

import argparse
import secrets
import socket
import sys
import threading
import webbrowser
from typing import Any, Callable, Dict

import uvicorn
from dblift_ui.server import create_app

HOST = "127.0.0.1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dblift ui", description="Open the local web interface for your migrations."
    )
    parser.add_argument(
        "--port", type=int, default=0, help="Port to listen on (default: a free port)."
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Print the address without opening a browser."
    )
    return parser


def pick_port(requested: int) -> int:
    if requested:
        return requested
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return int(probe.getsockname()[1])


def launch_url(port: int, token: str) -> str:
    return f"http://{HOST}:{port}/?token={token}"


def open_browser_soon(url: str) -> None:
    """Open *url* once the server has had a moment to start listening."""
    timer = threading.Timer(1.0, webbrowser.open, args=(url,))
    timer.daemon = True
    timer.start()


def run_ui(args: Any) -> int:
    options = build_parser().parse_args(list(getattr(args, "terminal_args", []) or []))
    port = pick_port(options.port)
    token = secrets.token_urlsafe(32)
    url = launch_url(port, token)
    sys.stdout.write(f"\n  DBLift UI  ->  {url}\n  Press Ctrl+C to stop.\n\n")
    sys.stdout.flush()
    if not options.no_browser:
        open_browser_soon(url)
    uvicorn.run(create_app(token=token, port=port), host=HOST, port=port, log_level="warning")
    return 0


def terminal_commands() -> Dict[str, Callable[[Any], int]]:
    return {"ui": run_ui}
