import json
from pathlib import Path

import pytest

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
    assert s.scopes() == [{"scope": "main", "count": 3, "tags": {"auth": 2, "front": 1}}, {"scope": "task-auth", "count": 0, "tags": {}}]

    # the JSONL is the truth: hand-edit it and the index follows
    f = tmp_path / "memories" / "main.jsonl"
    f.write_text(f.read_text().replace("React", "Preact"))
    assert "Preact" in s.select("frontend framework")[0]["text"]

    # a second Store on the same folder (another AI session) sees the same memory
    assert Store(tmp_path).select("", k=10) == s.select("", k=10)

    # secrets are refused before anything changes, so a refused correction keeps the old memory
    for leak in ["key AKIAABCDEFGHIJKLMNOP", "db is postgres://app:s3cretpw@db:5432/x", "password = hunter2"]:
        with pytest.raises(ValueError, match="secret"):
            s.write(leak, id=up["id"])
    with pytest.raises(ValueError, match="secret"):
        s.compress("main", [up["id"]], "Frontend, deploy key AKIAABCDEFGHIJKLMNOP")
    assert up["id"] in {r["id"] for r in s.select("", k=10)}

    # look-alikes pass, and forget deletes by id
    ok = s.write("Clients send the token: Authorization header from task-auth-refactor-notes, password in $DB_PASSWORD")
    assert s.forget([ok["id"]]) == {"removed": [ok["id"]]}
    with pytest.raises(KeyError):
        s.forget([ok["id"]])

    # since keeps what was written or corrected from then on; no offset means local time
    old = {"id": "old000000000", "ts": "2020-01-01T00:00:00+00:00", "text": "Legacy API ran on PHP 5", "tags": [], "source": ""}
    f.write_text(f.read_text() + json.dumps(old) + "\n")
    assert "old000000000" in {r["id"] for r in s.select("", k=20)}
    assert "old000000000" not in {r["id"] for r in s.select("", k=20, since="2021-01-01")}
    assert s.select("legacy php api", k=1)[0]["id"] == "old000000000"
    assert "old000000000" not in {r["id"] for r in s.select("legacy php api", since="2021-01-01T00:00+07:00")}
    assert s.select("", since="2999-01-01") == []
    with pytest.raises(ValueError, match="since"):
        s.select("", since="last week")


def test_trail_logs_prompts_and_tool_calls(tmp_path: Path):
    from context_store.store import trail

    trail({"session_id": "s1", "prompt": "add a retry to the fetcher"}, tmp_path)
    trail({"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "pytest -q"}, "tool_response": {"stdout": "3 passed"}}, tmp_path)
    trail({"tool_name": "Read", "tool_input": {"file_path": ".env"}, "tool_response": "DB_PASSWORD=hunter22"}, tmp_path)
    trail({"tool_name": "Read", "tool_input": {}, "tool_response": "x" * 9000}, tmp_path)

    s = Store(tmp_path)
    logged = s.select("", "detail", k=10)[::-1]
    assert [r["tags"] for r in logged[:2]] == [["detail", "prompt"], ["detail", "tool", "bash"]]
    assert "pytest -q" in logged[1]["text"] and "3 passed" in logged[1]["text"] and logged[1]["source"] == "s1"
    assert "hunter22" not in logged[2]["text"] and ".env" in logged[2]["text"]  # the secret part masked, the action kept
    assert len(logged[3]["text"]) == 4000
    assert s.select("", k=10) == []  # main stays clean for the recall loop



def test_config_env_beats_file_beats_default(tmp_path: Path, monkeypatch):
    from context_store import config

    monkeypatch.delenv("CONTEXT_K", raising=False)
    monkeypatch.delenv("CONTEXT_SYNC_K", raising=False)
    assert config.resolve("k", tmp_path) == (8, "default") and config.get("sync_k", tmp_path) == 6

    (tmp_path / "config.json").write_text('{"future": true}')
    assert config.save(tmp_path, k=12, sync_k=None) == {"future": True, "k": 12}  # unknown keys survive a save
    assert config.resolve("k", tmp_path) == (12, "config.json") and config.get("sync_k", tmp_path) == 6

    monkeypatch.setenv("CONTEXT_K", "3")
    assert config.resolve("k", tmp_path) == (3, "CONTEXT_K")

    for bad in (0, 101, "lots", 2.5, True):
        with pytest.raises(ValueError):
            config.save(tmp_path, k=bad)
    with pytest.raises(ValueError):
        config.save(tmp_path, kk=4)
    assert json.loads((tmp_path / "config.json").read_text())["k"] == 12  # a refused save changes nothing

    monkeypatch.setenv("CONTEXT_K", "0")
    with pytest.raises(ValueError, match="CONTEXT_K=0"):
        config.get("k", tmp_path)
    monkeypatch.delenv("CONTEXT_K")
    (tmp_path / "config.json").write_text('{"k": "9"}')  # the hook only reads numbers, so the store refuses strings too
    with pytest.raises(ValueError, match="JSON number"):
        config.get("k", tmp_path)
    (tmp_path / "config.json").write_text("{nope")
    with pytest.raises(ValueError, match="not valid JSON"):
        config.get("k", tmp_path)


def test_config_cli(tmp_path: Path, monkeypatch, capsys):
    from context_store import config

    monkeypatch.setenv("CONTEXT_DIR", str(tmp_path))
    monkeypatch.delenv("CONTEXT_K", raising=False)
    monkeypatch.delenv("CONTEXT_SYNC_K", raising=False)
    assert config.main(["--sync-k", "10"]) == 0
    out = capsys.readouterr().out
    assert "k       8    from default" in out and "sync_k  10   from config.json" in out, out
    with pytest.raises(SystemExit) as e:
        config.main(["--k", "500"])
    assert e.value.code == 2 and json.loads((tmp_path / "config.json").read_text()) == {"sync_k": 10}


def test_select_default_k_follows_config(tmp_path: Path, monkeypatch):
    """No k given: the repo's config.json decides, re-read on every call; an explicit k still wins."""
    monkeypatch.delenv("CONTEXT_K", raising=False)

    class Flat:  # stand-in embedder, so this runs without downloading the model
        def embed(self, texts):
            return [[1.0] + [0.0] * 383 for _ in texts]

    s = Store(tmp_path)
    s._model = Flat()
    lines = [json.dumps({"id": f"m{i:011d}", "ts": f"2026-01-{i + 1:02d}T00:00:00+00:00", "text": f"fact {i}", "tags": [], "source": ""})
             for i in range(12)]
    (tmp_path / "memories/main.jsonl").write_text("\n".join(lines) + "\n")
    assert len(s.select("")) == 8
    (tmp_path / "config.json").write_text('{"k": 3}')
    assert [r["id"] for r in s.select("")] == ["m00000000011", "m00000000010", "m00000000009"]
    assert len(s.select("", k=5)) == 5
    monkeypatch.setenv("CONTEXT_K", "11")
    assert len(s.select("")) == 11
