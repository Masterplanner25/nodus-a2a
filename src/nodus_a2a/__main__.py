"""CLI entry-point: python -m nodus_a2a

Commands:
    python -m nodus_a2a --version
    python -m nodus_a2a serve --name "..." --description "..." [options]

The serve command starts an A2A server with no tools registered.  In practice
you will construct an A2AHttpServer in Python, wire it to your NodusRuntime,
and call serve() from your own code.  The CLI is primarily useful for smoke
testing connectivity and verifying the Agent Card is well-formed.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import ServerConfig
from .transport import A2AHttpServer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m nodus_a2a",
        description=(
            f"nodus-a2a {__version__} — A2A 1.0.0 adapter for Nodus {__version__}\n"
            "Serve nodus-lang std:tools over the A2A protocol."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"nodus-a2a {__version__}",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    serve = sub.add_parser(
        "serve",
        help="Start an A2A server (no tools; useful for smoke testing)",
        description=(
            "Start an A2A 1.0.0 server with no tools registered.\n"
            "Every SendMessage returns an error DataPart explaining that no\n"
            "tools are registered.  Use this to verify network connectivity\n"
            "and that the Agent Card is being served correctly.\n\n"
            "For production use, construct A2AHttpServer directly in Python\n"
            "and wire it to your NodusRuntime.tool_registry."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    serve.add_argument("--name", required=True, help="Agent name (appears in Agent Card)")
    serve.add_argument(
        "--description", required=True,
        help="Human-readable agent description"
    )
    serve.add_argument(
        "--base-url",
        default="",
        metavar="URL",
        help="Public HTTPS base URL for the Agent Card (e.g. https://myagent.example.com)",
    )
    serve.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    serve.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    serve.add_argument(
        "--agent-version",
        default="0.1.0",
        metavar="VER",
        help="Agent version string in the Agent Card (default: 0.1.0)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "serve":
        config = ServerConfig(
            base_url=args.base_url or f"http://{args.host}:{args.port}",
            agent_name=args.name,
            agent_description=args.description,
            agent_version=args.agent_version,
            host=args.host,
            port=args.port,
        )
        server = A2AHttpServer(
            config=config,
            invoke=_no_tools_invoke,
            tool_names=[],
            tools=[],
        )
        print(
            f"nodus-a2a {__version__} — starting (no tools registered)\n"
            f"  Agent Card: http://{args.host}:{args.port}/.well-known/agent-card.json\n"
            f"  SendMessage: POST http://{args.host}:{args.port}/message:send\n"
            "Press Ctrl-C to stop."
        )
        try:
            server.serve()
        except KeyboardInterrupt:
            server.close()
            print("\nStopped.")
    else:
        parser.print_help()
        sys.exit(0)


def _no_tools_invoke(name: str, args: dict) -> object:
    raise RuntimeError(
        "No tools are registered. "
        "Wire A2AHttpServer to a NodusRuntime in Python to register tools."
    )


if __name__ == "__main__":
    main()
