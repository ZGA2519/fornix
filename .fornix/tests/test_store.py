from pathlib import Path

from context_store.store import Store


def test_write_select_compress_isolate(tmp_path: Path):
    s = Store(tmp_path)
    a = s.write("Passwords are hashed with argon2-cffi", tags=["auth"], source="test")
    b = s.write("Frontend is React + Vite behind nginx", tags=["front"])
    s.write("Password hashing uses argon2 via argon2-cffi", tags=["auth"])  # near-duplicate of a

    hit = s.select("how are passwords stored")
    assert hit[0]["tags"] == ["auth"] and hit[0]["score"] > hit[-1]["score"]
    assert [r["tags"] for r in s.select("anything", tags=["front"])] == [["front"]]

    # write with an id corrects in place: same id, new text, tags kept, index follows
    up = s.write("Frontend is React 19 + Vite behind nginx", id=b["id"])
    assert up["id"] == b["id"] and up["tags"] == ["front"]
    assert "19" in s.select("frontend framework", k=1)[0]["text"] and len(s.select("", k=10)) == 3

    # compress without a summary merges near-duplicates and keeps the newest
    assert s.compress(threshold=0.85)["removed"] == [a["id"]]

    # isolate seeds a private scope from main
    iso = s.isolate("task-auth", seed_from="main", query="passwords", k=1)
    assert [r["origin"] for r in iso["seeded"]] and iso["memories"][0]["scope"] == "task-auth"
    s.write("Login tokens expire after 12h", "task-auth")

    # compress with a summary folds the isolated scope back into main
    ids = {r["id"] for r in s.select("", "task-auth", k=10)}
    out = s.compress("main", ids, "Auth: argon2 passwords, 12h JWT")
    assert set(out["removed"]) == ids and set(out["kept"]["supersedes"]) == ids
    assert s.scopes() == [{"scope": "main", "count": 3}, {"scope": "task-auth", "count": 0}]

    # the JSONL is the truth: hand-edit it and the index follows
    f = tmp_path / "memories" / "main.jsonl"
    f.write_text(f.read_text().replace("React", "Preact"))
    assert "Preact" in s.select("frontend framework")[0]["text"]

    # a second Store on the same folder (another AI session) sees the same memory
    assert Store(tmp_path).select("", k=10) == s.select("", k=10)
