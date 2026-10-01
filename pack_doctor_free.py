#!/usr/bin/env python3
"""
Pack Doctor (FREE EDITION) — what is actually installed in your pack?

A quest that rewards `minecraft:diamond_swrd`, a recipe that outputs an item
from a mod you removed, a loot table pointing at `create:brass_igot`. None of
these crash. None of them log an error. They just quietly give the player
nothing, and you find out when someone complains three weeks later.

This reads every jar in your mods folder, builds an index of every ID that
actually exists, then checks every ID referenced in your datapacks, KubeJS
scripts, quests and configs against it.

No dependencies. No install. Python 3.8+.

    python pack_doctor.py index  "E:/Server/mods"
    python pack_doctor.py check  "E:/Server/mods" --against "E:/Server/kubejs"
    python pack_doctor.py mods   "E:/Server/mods"

Copyright (c) 2026. Sold as-is under the licence in LICENSE.txt.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

VERSION = "1.0.0-free"

UPGRADE_NOTICE = """
  ----------------------------------------------------------------------
  This is the FREE edition: `mods` and `index`.

  The full version adds `check`, which is the part that finds problems:
  it reads every ID your datapacks, KubeJS scripts, quests and configs
  reference and tells you which ones point at nothing -- the typo'd ids
  that silently give the player no item, register no recipe, roll no
  loot, and never log an error.

  It tiers findings by confidence, knows that KubeJS startup scripts
  REGISTER content, and suggests the id you probably meant.

  https://kaiven.gumroad.com/
  ----------------------------------------------------------------------
"""


BAR = "=" * 72
THIN = "-" * 72

# Translation keys are the most reliable ID source in a Forge jar: every
# registered item/block/entity needs one to display a name.
#   "item.create.brass_ingot"  ->  create:brass_ingot
KEY_RE = re.compile(
    r"^(item|block|entity|fluid|enchantment|effect|biome|potion|attribute)"
    r"\.([a-z0-9_]+)\.([a-z0-9_./]+)$"
)

# An ID as it appears in a datapack, script or config -- but ONLY inside a
# quoted string. Unquoted `key: value` is JavaScript and NBT object syntax:
# `{amount:25}` and `{tank:{amount:4000}}` look identical to a namespaced ID
# and produced nothing but false alarms until this was tightened.
STRING_RE = re.compile(r"""(['"`])((?:(?!\1)[^\\]|\\.){0,400})\1""")
REF_RE = re.compile(r"^#?([a-z][a-z0-9_]{1,63}):([a-z0-9_][a-z0-9_./-]{0,127})$")

# Files worth scanning for ID references.
SCAN_EXT = {".json", ".js", ".ts", ".snbt", ".toml", ".nbt", ".mcfunction", ".cfg"}

# Namespaces that are never mod content, so a hit on them means nothing.
NOISE_NS = {
    "http", "https", "ftp", "file", "data", "javascript", "mailto",
    "c", "forge", "fabric", "common", "tag", "type", "function", "value",
    "minecraft_",
}

# Keys whose values are prose or paths, not IDs.
NOISE_KEYS = {"description", "subtitle", "title", "text", "name", "translate",
              "comment", "author", "url", "icon_path"}


# ---------------------------------------------------------------------------
# Reading jars
# ---------------------------------------------------------------------------

class Mod:
    __slots__ = ("jar", "mod_id", "version", "name", "deps", "ids", "namespaces")

    def __init__(self, jar: str):
        self.jar = jar
        self.mod_id: Optional[str] = None
        self.version: Optional[str] = None
        self.name: Optional[str] = None
        self.deps: List[str] = []
        self.ids: Set[str] = set()
        self.namespaces: Set[str] = set()

    @property
    def basename(self) -> str:
        return os.path.basename(self.jar)


def _read_mods_toml(text: str, mod: Mod) -> None:
    """mods.toml is TOML, but the fields we need are simple enough to regex.

    Writing a TOML parser (or depending on tomli for 3.8-3.10) is not worth it
    for four scalar fields that mod authors write in a very narrow style.
    """
    m = re.search(r'^\s*modId\s*=\s*"([^"]+)"', text, re.M)
    if m:
        mod.mod_id = m.group(1)
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.M)
    if m:
        mod.version = m.group(1)
    m = re.search(r'^\s*displayName\s*=\s*"([^"]+)"', text, re.M)
    if m:
        mod.name = m.group(1)
    for d in re.finditer(r'^\s*modId\s*=\s*"([^"]+)"', text, re.M):
        if d.group(1) != mod.mod_id:
            mod.deps.append(d.group(1))


def read_jar(path: str) -> Optional[Mod]:
    """Pull the mod's identity and every ID it registers out of one jar."""
    mod = Mod(path)
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()

            # Forge lets mods.toml write version="${file.jarVersion}", which is
            # substituted at build time from the jar manifest. Unresolved, it is
            # the literal string, so read the manifest for the real value.
            manifest_ver = None
            try:
                mf = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
                mm = re.search(r"^Implementation-Version:\s*(.+?)\s*$", mf, re.M)
                if mm:
                    manifest_ver = mm.group(1)
            except Exception:
                pass

            for n in names:
                if n.endswith("META-INF/mods.toml"):
                    try:
                        _read_mods_toml(z.read(n).decode("utf-8", "replace"), mod)
                    except Exception:
                        pass
                    break

            for n in names:
                if not (n.startswith("assets/") and n.endswith("/lang/en_us.json")):
                    continue
                try:
                    data = json.loads(z.read(n).decode("utf-8", "replace"))
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                for key in data:
                    km = KEY_RE.match(key)
                    if km:
                        _, ns, path_ = km.group(1), km.group(2), km.group(3)
                        mod.ids.add(f"{ns}:{path_.replace('.', '/')}")
                        mod.namespaces.add(ns)

            # A mod can ship data for a namespace without a lang entry
            # (tags, loot tables, worldgen). Record the namespace so we do
            # not report every one of its IDs as unknown.
            for n in names:
                if n.startswith("data/") and n.count("/") >= 2:
                    mod.namespaces.add(n.split("/")[1])
    except zipfile.BadZipFile:
        return None
    except Exception:
        return None

    if mod.version and mod.version.startswith("${"):
        mod.version = manifest_ver or None
    if not mod.mod_id:
        mod.mod_id = os.path.splitext(mod.basename)[0]
    return mod


def scan_mods(folder: str) -> List[Mod]:
    jars = sorted(
        os.path.join(folder, f) for f in os.listdir(folder)
        if f.lower().endswith(".jar")
    )
    mods = []
    for j in jars:
        m = read_jar(j)
        if m:
            mods.append(m)
    return mods


# ---------------------------------------------------------------------------
# Reference scanning
# ---------------------------------------------------------------------------

class Ref:
    __slots__ = ("ident", "file", "line")

    def __init__(self, ident: str, file: str, line: int):
        self.ident = ident
        self.file = file
        self.line = line


# KubeJS startup scripts REGISTER new content. An ID created there exists at
# runtime but appears in no jar, so without this every custom item in the pack
# is reported as a typo.
DEFINES_RE = re.compile(
    r"(?:\.create|registry\.create|event\.create)\s*\(\s*['\"`]([a-z0-9_]+:[a-z0-9_./-]+)",
)






# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def header(title: str, subtitle: str = "") -> str:
    out = [BAR, f" PACK DOCTOR {VERSION}", f" {title}"]
    if subtitle:
        out.append(f" {subtitle}")
    out.append(BAR)
    return "\n".join(out) + "\n"


def cmd_mods(args) -> int:
    mods = scan_mods(args.mods)
    print(header("Installed mods", f"{len(mods)} jars in {args.mods}"))

    by_id: Dict[str, List[Mod]] = defaultdict(list)
    for m in mods:
        by_id[m.mod_id].append(m)

    dupes = {k: v for k, v in by_id.items() if len(v) > 1}
    if dupes:
        print("DUPLICATE MOD IDS — the server will refuse to start\n" + THIN)
        for mid, group in sorted(dupes.items()):
            print(f"  {mid}")
            for m in group:
                print(f"    {m.basename}")
        print("\n  Delete the older jar in each pair. Copying a new version in does")
        print("  not replace a file whose NAME changed.\n")

    print(f"{'MOD ID':<32} {'VERSION':<16} IDS   JAR")
    print(THIN)
    for m in sorted(mods, key=lambda x: (x.mod_id or "")):
        print(f"{(m.mod_id or '?'):<32} {(m.version or '?'):<16} {len(m.ids):<5} {m.basename[:40]}")

    total = sum(len(m.ids) for m in mods)
    print(THIN)
    print(f"{len(mods)} mods, {total} registered IDs, {len(dupes)} duplicate ids")
    print(UPGRADE_NOTICE)
    return 1 if dupes else 0


def cmd_index(args) -> int:
    mods = scan_mods(args.mods)
    index: Set[str] = set()
    for m in mods:
        index |= m.ids

    if args.json:
        print(json.dumps({
            "tool": "pack-doctor", "version": VERSION,
            "mods": len(mods), "ids": sorted(index),
        }, indent=2))
        return 0

    print(header("ID index", f"{len(mods)} mods in {args.mods}"))
    by_ns: Dict[str, int] = defaultdict(int)
    for i in index:
        by_ns[i.split(":", 1)[0]] += 1
    print(f"{'NAMESPACE':<32} IDS")
    print(THIN)
    for ns, n in sorted(by_ns.items(), key=lambda kv: -kv[1]):
        print(f"{ns:<32} {n}")
    print(THIN)
    print(f"{len(index)} IDs across {len(by_ns)} namespaces")
    print(UPGRADE_NOTICE)
    return 0




def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pack_doctor",
        description="Find modpack IDs that silently do nothing.",
    )
    ap.add_argument("--version", action="version", version=f"pack-doctor {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("mods", help="list installed mods, flag duplicates")
    p.add_argument("mods")
    p.set_defaults(func=cmd_mods)

    p = sub.add_parser("index", help="index every ID your mods register")
    p.add_argument("mods")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_index)


    args = ap.parse_args(argv)
    if not os.path.isdir(args.mods):
        print(f"error: not a folder: {args.mods}", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
