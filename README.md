# Pack Doctor — Free Edition

See what is actually installed in your modded Minecraft pack, and catch the
duplicate jars that stop a server booting.

```bash
python pack_doctor_free.py mods   "MyServer/mods"
python pack_doctor_free.py index  "MyServer/mods"
```

One file. No dependencies. Python 3.8+. Forge and NeoForge, 1.16–1.21.

## What the free edition does

**`mods`** — every jar in your mods folder with its real mod id, version and how
many IDs it registers. Flags duplicate mod ids, which are a hard startup failure
and are almost always an old jar you forgot to delete.

It resolves `${file.jarVersion}` from the jar manifest, so you get the real
version instead of Forge's unsubstituted placeholder.

**`index`** — every item, block, entity, fluid, enchantment and effect ID your
installed mods register, grouped by namespace. Useful on its own when you are
writing recipes or quests and need to know the exact ID of something.

## What it doesn't do

It does not check your pack's content. The full version adds `check`, which
reads every ID your datapacks, KubeJS scripts, quests and configs reference and
tells you which point at nothing — the typo'd IDs that silently give the player
no item, register no recipe, roll no loot, and never log an error.

<https://kaiven.gumroad.com/>

## Honest limits

IDs come from translation keys, which covers everything a player can see, but a
registry entry with no lang key cannot be confirmed from the jar. It reads files,
not the running game.

Free to use and to share, MIT. Not affiliated with Mojang, Microsoft,
MinecraftForge or NeoForged.
