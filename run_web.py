#!/usr/bin/env python3
"""Launch the wargame web UI.

Usage: python run_web.py [--port 8765]
Then open http://localhost:8765 in your browser.
"""

import argparse

import uvicorn

from wargame.web.server import app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    print(f"\n  Wargame UI: http://localhost:{args.port}\n")
    uvicorn.run(app, host=args.host, port=args.port)
