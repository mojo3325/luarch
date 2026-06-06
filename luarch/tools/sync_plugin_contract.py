from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = REPO_ROOT / "plugin" / "TBG_BuildingPostProcessor.plugin.lua"
START_MARKER = "-- BEGIN TBG CONTRACT SYNC"
END_MARKER = "-- END TBG CONTRACT SYNC"


def render_contract_block() -> str:
    sys.path.insert(0, str(REPO_ROOT))
    import export_contract

    return export_contract.render_plugin_contract_block()


def replace_contract_block(text: str, block: str) -> str:
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise RuntimeError("Could not find synced contract block markers in plugin file.")

    end_line = text.find("\n", end)
    if end_line == -1:
        end_line = len(text)
    else:
        end_line += 1

    return text[:start] + block + text[end_line:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync the plugin contract block from export_contract.py.")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if the plugin contract block is stale.")
    args = parser.parse_args()

    current = PLUGIN_PATH.read_text(encoding="utf-8")
    rendered = render_contract_block()
    updated = replace_contract_block(current, rendered)

    if updated == current:
        if args.check:
            print("plugin contract block is up to date")
        return 0

    if args.check:
        print("plugin contract block is stale")
        return 1

    PLUGIN_PATH.write_text(updated, encoding="utf-8")
    print("synced plugin contract block")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
