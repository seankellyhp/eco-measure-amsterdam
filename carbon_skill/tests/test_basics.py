import json
from datetime import datetime, timezone

import pytest

from carbon_skill import agents, paths, provider_impacts, runs, tokens


@pytest.mark.parametrize("label", ["default", "t1", "idle.v2", "a_b-c", "x" * 64])
def test_label_ok(label):
    assert paths.valid_label(label)


@pytest.mark.parametrize("label", ["", "--project-name", "../x", "a/b", "x" * 65, ".hidden"])
def test_label_rejected(label):
    assert not paths.valid_label(label)
    with pytest.raises(paths.UsageError):
        paths.check_label(label)


def test_claude_code_message_split_over_lines_counts_once(tmp_path):
    usage = {"input_tokens": 10, "cache_read_input_tokens": 100, "output_tokens": 5}
    lines = [{"uuid": "u0", "timestamp": "2026-01-01T10:00:00Z"}] + [
        {"uuid": f"a{i}", "parentUuid": "u0", "timestamp": f"2026-01-01T10:00:0{i + 1}Z",
         "message": {"id": "m1", "model": "claude-opus-5", "usage": usage}}
        for i in range(3)
    ]
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    calls = tokens.collect(str(f), "claude-code", start, end).calls
    assert len(calls) == 1
    assert calls[0].latency == 3.0
    t = tokens.summary(calls)
    assert (t["sent"], t["received"]) == (110, 5)


def test_split_model():
    assert provider_impacts.split_model("openrouter/anthropic/claude-sonnet-4-5") == ("anthropic", "claude-sonnet-4-5")
    assert provider_impacts.split_model("us.anthropic.claude-opus-4-1-20250805-v1:0") == ("anthropic", "claude-opus-4-1-20250805")
    assert provider_impacts.split_model("gpt-3.5-turbo") == ("", "gpt-3.5-turbo")


def test_sweep_marks_dead_monitor():
    rundir = paths.data_root() / "dead"
    rundir.mkdir()
    runs.write_json(rundir / "status.json", {"state": "running", "pid": 999999999, "create_time": 1.0})
    runs.sweep()
    st = runs.status(rundir)
    assert st["state"] == "stopped" and st["stopped_by"] == "monitor died"


def test_install_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    agents.install("claude-code")
    folder = tmp_path / "claude" / "skills" / "carbon"
    text = (folder / "SKILL.md").read_text()
    assert "{{CARBON_CMD}}" not in text and "start  [label]" in text
    assert (folder / agents.MARKER).exists() and (folder / "reference" / "tokens.md").exists()
    assert "Removed" in agents.remove("claude-code") and not folder.exists()


def test_install_refuses_foreign_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    folder = tmp_path / "claude" / "skills" / "carbon"
    folder.mkdir(parents=True)
    with pytest.raises(paths.Failure):
        agents.install("claude-code")
    assert "left it alone" in agents.remove("claude-code")
