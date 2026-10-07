# Pack Doctor — Free Edition

Find the IDs in your modpack that point at nothing. They give the player no
item, register no recipe, roll no loot — and never log an error.

```bash
python pack_doctor_free.py check "MyServer/mods" --against "MyServer"
python pack_doctor_free.py mods  "MyServer/mods"
python pack_doctor_free.py index "MyServer/mods"
```

One file. No dependencies. Python 3.8+. Forge and NeoForge, 1.16–1.21.

Or install it from PyPI and skip the download:

```bash
pip install pack-doctor
pack-doctor check "MyServer/mods" --against "MyServer"
```

## What the free edition does

**`check`** — the reason this exists. Cross-references every ID your scripts,
datapacks, quests and configs reference against the IDs your installed jars
actually register, and names the ones that match nothing.

```bash
python pack_doctor_free.py check path/to/mods --against path/to/pack
```

The certain findings are free: an ID whose **namespace has no installed mod at
all** is unambiguously dead, and a pack that lost a mod can carry hundreds of
them. Nothing crashes, nothing logs, and the first you hear of it is a player
asking why a quest gave them nothing.

**`mods`** — every jar with its real mod id, version and how many IDs it
registers. Flags duplicate mod ids, which are a hard startup failure and are
almost always an old jar you forgot to delete. It resolves
`${file.jarVersion}` from the jar manifest, so you get the real version rather
than Forge's unsubstituted placeholder.

**`index`** — every item, block, entity, fluid, enchantment and effect ID your
installed mods register.

## What the full version adds

The **suggestion engine**: `cooked_caned_fish` → *did you mean
`cooked_canned_fish`?* — and the confidence tiers that make that list worth
reading. On a real 233-mod pack, naive matching produced 169 "typos", most of
them nonsense. Comparing paths rather than whole IDs, and tiering by
confidence, cut it to 63 — three of which were real and still live in a pack
thousands of people play.

Knowing an ID is dead is worth having for free. Knowing what you *meant*,
without wading through a hundred false positives, is the part worth paying for.

<https://kaiven.gumroad.com/l/pack-doctor>

### One honest limit

Suggestions use a 0.90 similarity cutoff on the path. That catches dropped and
doubled letters (`stampler` → `stapler`, 0.933) but **misses transpositions**:
`wigdet` → `widget` scores 0.833 and will not be suggested. Lowering the cutoff
brings the false positives straight back, so it stays where it is.


## What it doesn't do

It does not tell you what you *meant*. The free edition names the dead ID; it
does not guess the live one you were reaching for, and it does not tier findings
by confidence. On a 233-mod pack that is the difference between a list of 169
candidates and 63 worth actually reading.

It reads files, never the running game, and it never writes to your pack.

<https://kaiven.gumroad.com/l/pack-doctor>

## How this was built

Built by Jakoby Tuckta with Claude, against a live 234-mod Forge server. The
code was written with Claude; the crash reports, the production server it was
tested on, and the calls about what shipped are mine. Every commit is tagged
`Co-Authored-By: Claude`.

The first version passed every test we wrote and then diagnosed three of eight
real crash reports — because the same author had written both the samples and
the patterns. It was rebuilt from thirteen genuine crash reports. That rebuild,
not who typed it, is why it works. [The full account of what the real data
corrected](https://jaakoby.github.io/how-this-was-built.html).

## Honest limits

IDs come from translation keys, which covers everything a player can see, but a
registry entry with no lang key cannot be confirmed from the jar. It reads files,
not the running game.

## Related reading

- [KubeJS recipe or tag silently does nothing](https://jaakoby.github.io/guides/kubejs-recipe-not-working.html)
  — the failure mode this tool exists to catch, explained end to end
- [How to find which mod is crashing your server](https://jaakoby.github.io/guides/which-mod-is-crashing-my-server.html)

Free to use on any server you own or administer — see `LICENSE.txt`. Not
affiliated with Mojang, Microsoft, MinecraftForge or NeoForged.
