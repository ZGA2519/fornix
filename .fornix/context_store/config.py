"""Per-repo settings in .fornix/config.json, committed beside memories/ so every session of the repo shares them.

An env var wins over the file, the file over the built-in default. The store reads them on every call, so a
change applies to the next select or isolate with no restart; the context-sync hook reads sync_k on every prompt.

    python -m context_store.config                        print each setting and where it came from
    python -m context_store.config --k 12 --sync-k 10     save them to config.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

MAX_K = 100
DEFAULTS = {"k": 8, "sync_k": 6}  # k: select and isolate with no k given; sync_k: the hook's per-prompt recall
ENV = {"k": "CONTEXT_K", "sync_k": "CONTEXT_SYNC_K"}


def _root() -> Path:
    return Path(os.environ.get("CONTEXT_DIR", Path(__file__).resolve().parent.parent))


def check(name: str, value, where: str = "") -> int:
    """value as a k in 1..MAX_K, or a ValueError naming where it came from."""
    label = where or name
    if isinstance(value, bool):  # json true would pass int()
        raise ValueError(f"{label}={value!r} is not a whole number")  # noqa: TRY004 - ValueError is what the server surfaces
    try:
        k = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}={value!r} is not a whole number") from None
    if isinstance(value, float) and value != k:
        raise ValueError(f"{label}={value!r} is not a whole number")
    if not 1 <= k <= MAX_K:
        raise ValueError(f"{label}={k} is out of range, use 1..{MAX_K}")
    return k


def path(root: Path | None = None) -> Path:
    return (root or _root()) / "config.json"


def load(root: Path | None = None) -> dict:
    """The file as written, {} when there is none. Unknown keys are kept, so a newer fornix's settings survive a save."""
    p = path(root)
    if not p.is_file() or not p.read_text().strip():
        return {}
    try:
        doc = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{p} is not valid JSON ({e})") from None
    if not isinstance(doc, dict):
        raise ValueError(f"{p} must hold a JSON object, e.g. {json.dumps(DEFAULTS)}")  # noqa: TRY004 - as above
    return doc


def resolve(name: str, root: Path | None = None) -> tuple[int, str]:
    """(value, source): source is the env var name, 'config.json' or 'default'."""
    if (raw := os.environ.get(ENV[name], "").strip()):
        return check(name, raw, ENV[name]), ENV[name]
    doc = load(root)
    if name in doc:
        where = f"{path(root)}: {name}"
        if not isinstance(doc[name], int) or isinstance(doc[name], bool):  # a JSON number, as the hook's parser needs
            raise ValueError(f"{where}={doc[name]!r} must be a JSON number, e.g. {json.dumps({name: DEFAULTS[name]})}")
        return check(name, doc[name], where), "config.json"
    return DEFAULTS[name], "default"


def get(name: str, root: Path | None = None) -> int:
    return resolve(name, root)[0]


def save(root: Path | None = None, **values) -> dict:
    """Merge the given settings (None = leave as is) into config.json and return what the file now holds."""
    unknown = set(values) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown setting {sorted(unknown)}; known: {sorted(DEFAULTS)}")
    fresh = {n: check(n, v) for n, v in values.items() if v is not None}
    doc = load(root)
    if fresh:
        doc.update(fresh)
        p = path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m context_store.config", description=__doc__.split("\n\n")[0])
    ap.add_argument("--k", type=int, help=f"default k for select and isolate (1..{MAX_K}, built-in {DEFAULTS['k']})")
    ap.add_argument("--sync-k", type=int, help=f"k the context-sync hook recalls per prompt (1..{MAX_K}, built-in {DEFAULTS['sync_k']})")
    a = ap.parse_args(argv)
    try:
        if a.k is not None or a.sync_k is not None:
            save(k=a.k, sync_k=a.sync_k)
            print(f"saved {path()}")
        for name in DEFAULTS:
            value, source = resolve(name)
            note = f"  (overrides config.json, unset {source} to use the file)" if source in ENV.values() and name in load() else ""
            print(f"{name:<7} {value:<4} from {source}{note}")
    except ValueError as e:
        ap.exit(2, f"config: {e}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
