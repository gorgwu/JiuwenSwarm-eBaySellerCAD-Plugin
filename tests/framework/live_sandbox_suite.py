"""Run the Sandbox action suite using tools resolved from this plugin's manifest.

This is a developer test.  It never targets Production.  By default it keeps the
existing per-write confirmation prompts.  ``--approve-writes`` is deliberately
required to automate those Sandbox writes.
"""
from __future__ import annotations

import argparse
import asyncio
import builtins
import sys
from pathlib import Path
from unittest.mock import patch

from test_framework_integration import load_tools

# The established Sandbox runner supplies fixture handling, safety checks,
# journals, and cleanup compatibility.  This adapter replaces its direct source
# classes with the concrete tools agent-core resolved from manifest.json.
SANDBOX_DIR = Path(__file__).resolve().parents[1] / "sandbox"
sys.path.insert(0, str(SANDBOX_DIR))
import sandbox_tools  # noqa: E402


def connect_resolved_tools() -> None:
    tools = load_tools()
    sandbox_tools.EbaySellerReadTool = type(tools["ebayseller_read"])
    sandbox_tools.EbaySellerListingWriteTool = type(tools["ebayseller_listing_write"])
    sandbox_tools.EbaySellerOfferWriteTool = type(tools["ebayseller_offer_write"])
    sandbox_tools.CLASSES = (
        sandbox_tools.EbaySellerReadTool,
        sandbox_tools.EbaySellerListingWriteTool,
        sandbox_tools.EbaySellerOfferWriteTool,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--read-suite", action="store_true", help="Run the 14 safe reads through agent-core.")
    group.add_argument("--live-suite", action="store_true", help="Run the full fixture-based suite through agent-core.")
    parser.add_argument("--fixtures", help="Private fixture JSON required by --live-suite.")
    parser.add_argument("--journal", help="Private run journal used by --live-suite cleanup.")
    parser.add_argument("--approve-writes", action="store_true", help="Automatically answer YES to Sandbox write prompts.")
    args = parser.parse_args()
    if args.approve_writes and not args.live_suite:
        parser.error("--approve-writes can be used only with --live-suite")
    if args.live_suite and not args.fixtures:
        parser.error("--live-suite requires --fixtures")

    connect_resolved_tools()
    forwarded = ["sandbox_tools.py", "--read-suite" if args.read_suite else "--live-suite"]
    if args.fixtures:
        forwarded.extend(["--fixtures", args.fixtures])
    if args.journal:
        forwarded.extend(["--journal", args.journal])
    with patch.object(sys, "argv", forwarded):
        if args.approve_writes:
            # This is intentionally explicit and Sandbox-only; sandbox_tools also
            # checks EBAY_ENV and the Sandbox API host before it can issue a call.
            with patch.object(builtins, "input", return_value="YES"):
                return asyncio.run(sandbox_tools.run())
        return asyncio.run(sandbox_tools.run())


if __name__ == "__main__":
    raise SystemExit(main())
