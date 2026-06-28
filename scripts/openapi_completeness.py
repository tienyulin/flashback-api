#!/usr/bin/env python3
"""OpenAPI completeness gate — stdlib only.

Reports endpoints/parameters/responses that are missing the descriptions and
examples that make API docs useful to AI agents (error schemas + examples are the
highest-value content). Same gap definition the wiki-doc-author skill uses to
help you fill them.

Usage:
  python openapi_completeness.py [openapi.json] [--fail]
  --fail : exit non-zero on any gap (use as a pre-commit gate). Default: warn (exit 0).

Fix gaps in CODE (route summary=/description=, Pydantic Field(description=...)),
then regenerate — openapi.json is generated, not hand-edited.
"""

import argparse
import json
import sys


def find_gaps(spec):
    """Return a list of human-readable completeness gaps in an OpenAPI spec."""
    gaps = []
    for path, item in (spec.get("paths") or {}).items():
        for method, op in (item or {}).items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            tag = f"{method.upper()} {path}"
            if not op.get("summary") and not op.get("description"):
                gaps.append(f"{tag}: 缺 summary/description")
            for p in op.get("parameters", []) or []:
                if not p.get("description"):
                    gaps.append(f"{tag}: parameter '{p.get('name', '?')}' 缺 description")
            responses = op.get("responses") or {}
            if not any(str(c).startswith(("4", "5")) for c in responses):
                gaps.append(f"{tag}: 缺 error response（4xx/5xx）")
            # request/response example present anywhere?
            has_example = json.dumps(op, ensure_ascii=False).find('"example') != -1
            if not has_example:
                gaps.append(f"{tag}: 缺 request/response 範例")
    return gaps


def main():
    """Load the spec, report gaps, and return a process exit code."""
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?", default="openapi.json")
    ap.add_argument("--fail", action="store_true", help="exit non-zero on any gap")
    args = ap.parse_args()
    try:
        with open(args.spec, encoding="utf-8") as f:
            spec = json.load(f)
    except FileNotFoundError:
        print(f"[completeness] 找不到 {args.spec} → 跳過（非 OpenAPI app）")
        return 0

    gaps = find_gaps(spec)
    if not gaps:
        print("[completeness] OK — 無缺漏")
        return 0
    print(f"[completeness] {len(gaps)} 處缺漏：")
    for g in gaps:
        print(f"    - {g}")
    print("補在程式碼（summary=/description=/Pydantic Field），或跑 `wiki-doc-author` skill 輔助。")
    return 1 if args.fail else 0


if __name__ == "__main__":
    sys.exit(main())
