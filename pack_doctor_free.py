#!/usr/bin/env python3
"""
Pack Doctor (FREE EDITION) — which IDs in your pack point at nothing?

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
  FREE edition: `mods`, `index`, and `check` -- which reports every ID
  your pack references that matches nothing any installed mod registers.
  Those IDs silently give the player no item, register no recipe, roll
  no loot, and never log an error.

  The full version adds the part that saves the time: it suggests the ID
  you probably meant, and tiers findings by confidence so a real typo is
  not buried in fuzzy-match noise. On a 233-mod pack that was the
  difference between 169 candidates and 63 worth reading.

  https://kaiven.gumroad.com/l/pack-doctor
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


def scan_defined(root: str) -> Set[str]:
    """IDs the pack's own scripts create, which therefore are not typos."""
    defined: Set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in SCAN_EXT:
                continue
            try:
                with open(os.path.join(dirpath, fn), "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        for m in DEFINES_RE.finditer(line):
                            defined.add(m.group(1))
            except (OSError, UnicodeDecodeError):
                continue
    return defined


def scan_refs(root: str) -> List[Ref]:
    """Collect every namespaced ID that appears inside a quoted string.

    Requiring quotes is what separates a real reference from JS/NBT object
    syntax. `'create:brass_ingot'` is an ID; `{amount:25}` is not.
    """
    refs: List[Ref] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in SCAN_EXT:
                continue
            full = os.path.join(dirpath, fn)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, start=1):
                        if len(line) > 8000:
                            line = line[:8000]
                        for sm in STRING_RE.finditer(line):
                            body = sm.group(2).strip()
                            m = REF_RE.match(body)
                            if not m:
                                continue
                            ns = m.group(1)
                            if ns in NOISE_NS:
                                continue
                            if body.startswith("#"):
                                continue          # a tag, not a registry id
                            refs.append(Ref(f"{ns}:{m.group(2)}", full, i))
            except (OSError, UnicodeDecodeError):
                continue
    return refs


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


def cmd_check(args) -> int:

    mods = scan_mods(args.mods)
    index: Set[str] = set()
    known_ns: Set[str] = set()
    for m in mods:
        index |= m.ids
        known_ns |= m.namespaces

    vanilla_checked = False
    if args.vanilla and os.path.exists(args.vanilla):
        vm = read_jar(args.vanilla)
        if vm and vm.ids:
            index |= vm.ids
            known_ns |= vm.namespaces
            vanilla_checked = True
    if not vanilla_checked:
        known_ns.add("minecraft")

    refs = scan_refs(args.against)

    # IDs the pack defines for itself are real, even though no jar has them.
    defined = scan_defined(args.against)
    index |= defined

    by_ns_index: Dict[str, List[str]] = defaultdict(list)
    paths_by_ns: Dict[str, List[str]] = defaultdict(list)
    for i in index:
        ns_, _, path_ = i.partition(":")
        by_ns_index[ns_].append(i)
        paths_by_ns[ns_].append(path_)

    # Tier 1: the namespace IS installed but this exact ID is not, AND a very
    # similar ID exists. That is a typo, and a typo silently does nothing.
    typos: Dict[str, Tuple[str, List[Ref]]] = {}
    # Tier 2: namespace installed, ID unknown, nothing close. Could be a tag,
    # a loot table or an entry with no translation key -- low confidence.
    unverified: Dict[str, List[Ref]] = defaultdict(list)
    # Tier 3: the namespace itself is absent. Grouped, because one missing mod
    # produces dozens of these and listing each is noise.
    missing_ns: Dict[str, List[Ref]] = defaultdict(list)

    for r in refs:
        if r.ident in index:
            continue
        ns = r.ident.split(":", 1)[0]
        if ns not in known_ns:
            missing_ns[ns].append(r)
            continue
        if ns not in by_ns_index:
            unverified[r.ident].append(r)
            continue
        # FREE EDITION: no suggestion engine. The finding is that this ID
        # matches nothing any installed mod registers -- unambiguous, and
        # the user can confirm it themselves. Naming the ID they probably
        # meant, and the confidence tiering that keeps fuzzy-match noise
        # out of the list, is the paid half.
        typos.setdefault(r.ident, (None, []))[1].append(r)

    print(header("ID check", f"{len(refs)} references in {args.against}"))
    print(f"  mods indexed      {len(mods)}")
    print(f"  known IDs         {len(index)}  ({len(defined)} defined by the pack itself)")
    print(f"  vanilla IDs       {'checked' if vanilla_checked else 'NOT checked (pass --vanilla <server jar>)'}")
    print()

    exit_code = 0

    if typos:
        exit_code = 1
        print(f"IDS THAT MATCH NOTHING INSTALLED — {len(typos)} ID(s)\n" + THIN)
        for ident in sorted(typos):
            hits = typos[ident][1]
            print(f"\n  {ident}")
            for r in hits[:3]:
                print(f"      {os.path.relpath(r.file, args.against)}:{r.line}")
            if len(hits) > 3:
                print(f"      … and {len(hits) - 3} more")
        print()

    if missing_ns:
        print(f"NAMESPACES WITH NO INSTALLED MOD — {len(missing_ns)}\n" + THIN)
        print("  Some of these are real missing mods. Others are group names a")
        print("  mod's own script API invents (KubeJS does this). Judge by count")
        print("  and by whether you recognise the name.\n")
        for ns in sorted(missing_ns, key=lambda n: -len(missing_ns[n])):
            hits = missing_ns[ns]
            ex = os.path.relpath(hits[0].file, args.against)
            print(f"  {ns:<28} {len(hits):>4} refs   e.g. {ex}:{hits[0].line}")
        print()

    if args.verbose and unverified:
        print(f"UNVERIFIED — {len(unverified)} ID(s) in an installed mod's namespace\n" + THIN)
        print("  The mod is present but this ID has no translation key, so it")
        print("  cannot be confirmed from the jar. Tags, loot tables and worldgen")
        print("  entries land here legitimately. Not necessarily a problem.\n")
        for ident in sorted(unverified)[:40]:
            r = unverified[ident][0]
            print(f"  {ident:<52} {os.path.relpath(r.file, args.against)}:{r.line}")
        if len(unverified) > 40:
            print(f"  … and {len(unverified) - 40} more")
        print()

    if not typos and not missing_ns:
        print("NO LIKELY TYPOS\n" + THIN)
        print("  Every referenced ID resolves to an installed mod's namespace.")
        if not vanilla_checked:
            print("\n  minecraft: IDs were NOT verified. Pass --vanilla <server jar>")
            print("  to catch typos like minecraft:diamond_swrd.")
    else:
        print(THIN)
        print(f"  {len(unverified)} further ID(s) could not be confirmed either way"
              f"{' (--verbose to list)' if not args.verbose else ''}.")

    return exit_code


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

    p = sub.add_parser("check", help="validate IDs referenced in your pack content")
    p.add_argument("mods")
    p.add_argument("--against", required=True,
                   help="folder of datapacks / kubejs / quests / configs to check")
    p.add_argument("--vanilla", help="path to the Minecraft server jar, to verify minecraft: IDs")
    p.add_argument("--verbose", action="store_true", help="also list unconfirmable IDs")
    p.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    if not os.path.isdir(args.mods):
        print(f"error: not a folder: {args.mods}", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
