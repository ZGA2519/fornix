"""python3 test_setup.py: install into a temp dir twice; files land, the re-run is a no-op."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def run(*args):
    r = subprocess.run([sys.executable, HERE / "setup.py", *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_install_twice():
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        out = run(t, "-y")
        assert (t / ".fornix/context_store/server.py").is_file()
        assert not (t / ".fornix/index.db").exists() and not (t / ".fornix/.venv").exists()
        assert (t / ".fornix/memories/main.jsonl").is_file()
        assert "fornix" in json.loads((t / ".mcp.json").read_text())["mcpServers"]
        assert (t / ".claude/hooks/context-sync.sh").is_file()
        assert "context-sync.sh" in (t / ".claude/settings.json").read_text()
        assert (t / ".agent/prompts/context-stop-sync.md").is_file()
        assert "0 unchanged" in out, out

        (t / ".fornix/memories/extra.jsonl").write_text("")
        out = run(t, "-y")
        assert "kept as is, 2 stores" in out and "already present" in out and "already registered" in out, out
        assert (t / ".fornix/memories/extra.jsonl").is_file()


def test_no_hook_and_refuses_checkout():
    with tempfile.TemporaryDirectory() as tmp:
        out = run(tmp, "-y", "--no-hook")
        assert "skipped (skill only)" in out and not (pathlib.Path(tmp) / ".claude/hooks").exists()
    r = subprocess.run([sys.executable, HERE / "setup.py", HERE, "-y"], capture_output=True, text=True)
    assert r.returncode == 1 and "source checkout" in r.stderr, r.stderr


def test_migrates_context_install():
    """An install from before the rename: .context/ moves to .fornix/ whole, the old server key goes."""
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        (t / ".context/context_store").mkdir(parents=True)
        (t / ".context/memories").mkdir()
        (t / ".context/memories/main.jsonl").write_text('{"id": "a"}\n')
        (t / ".context/.sync-on").write_text("readonly")
        old = {"command": "uv", "args": ["run", "--directory", ".context", "python", "-m", "context_store.server", "mcp"]}
        (t / ".mcp.json").write_text(json.dumps({"mcpServers": {"context-system": old, "other": {"command": "x"}}}))
        out = run(t, "-y")
        assert "moved from .context/" in out and 'legacy "context-system" entry removed' in out, out
        assert not (t / ".context").exists()
        assert (t / ".fornix/memories/main.jsonl").read_text() == '{"id": "a"}\n'
        assert (t / ".fornix/.sync-on").read_text() == "readonly"
        assert set(json.loads((t / ".mcp.json").read_text())["mcpServers"]) == {"fornix", "other"}


def test_set_root_finds_repos_below_root():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        near, deep, toodeep = root / "api", root / "a/b/web", root / "1/2/3/4/5/lost"
        for r in (near, deep, toodeep):
            r.mkdir(parents=True)
            run(r, "-y", "--no-hook")
        out = run(root, "--set-root", "-y")
        servers = json.loads((root / ".mcp.json").read_text())["mcpServers"]
        assert set(servers) == {"fornix-api", "fornix-web"}, servers
        reg = (root / ".claude/context-sync.repos").read_text().splitlines()
        assert len(reg) == 2 and str(near) in " ".join(reg) and str(deep) in " ".join(reg), reg
        assert (root / ".claude/skills/context-sync/SKILL.md").is_file()
        assert "lost" not in out


def test_wizard_by_keys():
    """Drive the arrow-key wizard through a pty: down+enter picks skill only, enter twice keeps no clients and says yes."""
    if os.name == "nt":
        return
    import pty
    import select
    import time
    with tempfile.TemporaryDirectory() as tmp:
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["NO_COLOR"] = "1"
            os.execvp(sys.executable, [sys.executable, str(HERE / "setup.py"), tmp])
        out = b""

        def until(marker, timeout=15):
            nonlocal out
            end = time.time() + timeout
            while marker not in out and time.time() < end:
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        out += os.read(fd, 4096)
                    except OSError:
                        break
            assert marker in out, out.decode(errors="replace")

        until(b"sync loop"), os.write(fd, b"\x1b[B\r")
        until(b"other clients?"), os.write(fd, b"\r")
        until(b"write it?"), os.write(fd, b"\r")
        until(b"skipped (skill only)")
        os.waitpid(pid, 0)
        text = out.decode(errors="replace")
        assert "\u2714 how should the sync loop stay on? \u203a skill only" in text, text
        assert not (pathlib.Path(tmp) / ".claude/hooks").exists()
        assert (pathlib.Path(tmp) / ".mcp.json").is_file()


if __name__ == "__main__":
    test_install_twice()
    test_no_hook_and_refuses_checkout()
    test_migrates_context_install()
    test_set_root_finds_repos_below_root()
    test_wizard_by_keys()
    print("ok")
