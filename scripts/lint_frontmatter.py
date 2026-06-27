#!/usr/bin/env python3
"""Frontmatter linter for wiki source docs — stdlib only (no pyyaml/jsonschema).

Validates each markdown's YAML frontmatter against the rules in
frontmatter.schema.json (read at runtime, single source of truth):
  - required: type, source_app
  - type in the controlled enum
  - source_app / tags match the controlled-vocabulary pattern
For `type: api` docs, also require an H1 and — when there is NO companion
openapi.json next to the file — at least one `METHOD /path` endpoint line.

Usage:
  python lint_frontmatter.py [paths...]          # default: all *.md under cwd
Exit non-zero (and print errors) on any nonconforming file.

ponytail: tiny frontmatter parser for our subset (scalar / inline-list / dash-list),
not a full YAML engine — that's all the schema allows anyway.
"""

import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "frontmatter.schema.json"), encoding="utf-8") as _schema_f:
    _SCHEMA = json.load(_schema_f)
_ENDPOINT = re.compile(r"^\s*(GET|POST|PUT|DELETE|PATCH)\s+/\S*", re.MULTILINE)
_H1 = re.compile(r"^#\s+\S", re.MULTILINE)


def parse_frontmatter(text):
    """Return (frontmatter dict, body). dict is {} when no frontmatter block."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4 :]
    fm = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):  # inline list
            fm[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        elif val == "":
            fm[key] = []  # dash-list follows (rare); treated empty
        else:
            fm[key] = val.strip("'\"")
    return fm, body


def _match(pattern, value):
    return re.match(pattern, value) is not None


def lint_file(path):
    """Return a list of rule violations for one markdown file (empty = OK)."""
    errs = []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    fm, body = parse_frontmatter(text)
    props = _SCHEMA["properties"]

    for req in _SCHEMA["required"]:
        if req not in fm or fm[req] in ("", [], None):
            errs.append(f"缺必填 frontmatter: {req}")

    t = fm.get("type")
    if t is not None and t not in props["type"]["enum"]:
        errs.append(f"type='{t}' 不在受控詞彙 {props['type']['enum']}")

    sa = fm.get("source_app")
    if sa and not _match(props["source_app"]["pattern"], sa):
        errs.append(f"source_app='{sa}' 須小寫+連字號")

    for tag in fm.get("tags", []) or []:
        if not _match(props["tags"]["items"]["pattern"], tag):
            errs.append(f"tag='{tag}' 須小寫+連字號（受控詞彙）")

    if t == "api":
        if not _H1.search(body):
            errs.append("api 文件缺 H1 標題")
        has_openapi = os.path.exists(os.path.join(os.path.dirname(path) or ".", "openapi.json"))
        if not has_openapi and not _ENDPOINT.search(body):
            errs.append("api 文件沒有 openapi.json 又缺 `METHOD /path` endpoint 行")
    return errs


def main(argv):
    """Lint the given markdown paths (or all *.md under cwd); return process exit code."""
    paths = argv[1:]
    if not paths:
        paths = [
            os.path.join(d, f)
            for d, _, fs in os.walk(".")
            for f in fs
            if f.endswith(".md") and ".git" not in d
        ]
    bad = 0
    for p in paths:
        if not p.endswith(".md"):
            continue
        errs = lint_file(p)
        if errs:
            bad += 1
            print(f"✗ {p}")
            for e in errs:
                print(f"    - {e}")
    if bad:
        print(f"\n{bad} 個檔不合規。規範見 wiki-doc-author skill 的 SKILL.md。")
        return 1
    print("frontmatter lint: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
