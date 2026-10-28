"""Compare an old-image capture with a new-image capture of the same replay."""
import collections
import json
import sys

AB = sys.argv[1]
site = sys.argv[2]
load = lambda p: [json.loads(l) for l in open(p)]
old = load(f"{AB}/cap.{site}_old.jsonl")
new = load(f"{AB}/cap.{site}_new.jsonl")

is_env = lambda m: m[0].startswith("emon/")
new_legacy = [m for m in new if not is_env(m)]
env = [m for m in new if is_env(m)]
print(f"old {len(old)}  new {len(new)} = legacy {len(new_legacy)} + emon/ {len(env)}")

assert not any(is_env(m) for m in old), "old image published emon/"
assert not any(m[2] for m in new_legacy), "a legacy topic became retained"

# Legacy: identical except topics the new code drops (channels named Unused)
old_topics = collections.Counter(m[0] for m in old)
new_topics = collections.Counter(m[0] for m in new_legacy)
dropped = {t for t in old_topics if t not in new_topics}
added = {t for t in new_topics if t not in old_topics}
changed = {t for t in new_topics if t in old_topics and new_topics[t] != old_topics[t]}
print(f"legacy topics: old {len(old_topics)}, new {len(new_topics)}, "
      f"dropped {len(dropped)}, added {len(added)}, count changed {len(changed)}")
for t in sorted(added)[:10]: print("  ADDED", t)
for t in sorted(changed)[:10]: print("  COUNT", t, old_topics[t], new_topics[t])
old_kept = [m[:2] for m in old if m[0] not in dropped]
same = old_kept == [m[:2] for m in new_legacy]
print(f"legacy sequence identical after removing dropped topics: {same}")
if not same:
    for i, (a, b) in enumerate(zip(old_kept, new_legacy)):
        if a != b[:2]:
            print("  first difference at", i, a, b); break
print("dropped topics, payloads seen:")
for t in sorted(dropped):
    vals = sorted({m[1] for m in old if m[0] == t})
    print(f"  {t}  x{old_topics[t]}  {vals[:4]}{' ...' if len(vals) > 4 else ''}")

# Envelopes: valid JSON with a value
bad = []
for t, p, r in env:
    if t == "emon/config":
        continue
    try:
        d = json.loads(p)
    except ValueError:
        bad.append((t, p)); continue
    if "v" not in d:   # retain flag is cleared on live delivery; see retained.py
        bad.append((t, p))
print(f"envelopes: {len(env)} messages on {len({m[0] for m in env})} topics, malformed {len(bad)}")
for b in bad[:5]: print("  BAD", b)
cfg = [m for m in env if m[0] == "emon/config"]
print(f"emon/config published {len(cfg)}x, retained {all(m[2] for m in cfg)}, "
      f"file {json.loads(cfg[0][1])['file'] if cfg else None}")
print("sample envelopes:")
seen = set()
for t, p, r in env:
    k = t.split("/")[1]
    if k not in seen and t != "emon/config":
        seen.add(k); print("  ", t, p)
