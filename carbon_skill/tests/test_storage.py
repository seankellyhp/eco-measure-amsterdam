import csv
import io
import os
import sqlite3
import threading

import psutil
import pytest

from carbon_skill import db, end, export, legacy, monitor, paths, runs, usage

from legacy_fixture import HEADER, write_run, write_transcript

ME = psutil.Process()


def make_run(label="r", state="stopped", sess=None, agent_pid=None, agent_ctime=None, samples=1, **extra):
    """A run row without a monitor. A 'running' one is bound to this test
    process, which is alive, so the sweep leaves it alone."""
    fields = {
        "label": label, "state": state, "created_at": db.now_iso(), "started_at": "2026-11-10T10:00:00+01:00",
        "measure_secs": 10.0, "grid_country": "NLD", "grid_source": "test", "carbon_version": "test",
        "agent_pid": agent_pid, "agent_ctime": agent_ctime,
        # A stopped test run has nothing to save; keep the sweep from trying.
        "usage_note": "test",
    }
    if state == "running":
        fields.update(monitor_pid=ME.pid, monitor_ctime=ME.create_time())
        fields.update(agent_pid=agent_pid or ME.pid, agent_ctime=agent_ctime or ME.create_time())
    else:
        fields["ended_at"] = "2026-11-10T10:30:00+01:00"
    fields.update(extra)
    run_id = db.insert_run(fields, sess)
    with db.opened() as conn:
        for i in range(samples):
            db.add_sample(conn, run_id, db.sample_from_codecarbon(
                {"timestamp": "2026-11-10T10:00:10", "duration": 10.0 * (i + 1), "energy_consumed": 0.001 * (i + 1),
                 "emissions": 0.0004 * (i + 1)}))
    return run_id


# --------------------------------------------------------------------------- #
# db
# --------------------------------------------------------------------------- #


def test_new_database_gets_schema_and_version():
    with db.opened() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.VERSION
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        assert {"session", "run", "sample", "api_call", "provider_estimate", "run_total", "run_tokens"} <= tables
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.health() == (db.VERSION, "ok")


def test_newer_database_is_refused():
    db.connect().close()
    raw = sqlite3.connect(db.path())
    raw.execute(f"PRAGMA user_version={db.VERSION + 1}")
    raw.close()
    with pytest.raises(paths.Failure, match="newer carbon"):
        db.connect()


def test_partial_schema_is_refused():
    raw = sqlite3.connect(db.path())
    raw.execute("CREATE TABLE run (id INTEGER PRIMARY KEY)")
    raw.close()
    with pytest.raises(paths.Failure, match="only part of carbon's tables"):
        db.connect()


def test_two_connections_write_without_locking():
    run_id = make_run(samples=0)
    errors = []

    def writer(n):
        try:
            with db.opened() as conn:
                for _ in range(n):
                    db.add_sample(conn, run_id, db.sample_from_codecarbon({"duration": 1.0}))
        except Exception as exc:  # pragma: no cover - the failure being tested for
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(50,)) for _ in range(2)]
    for t in threads:
        t.start()
    for _ in range(50):
        db.update_run(run_id, error=None)
    for t in threads:
        t.join()
    assert not errors
    assert [s["seq"] for s in db.samples(run_id)] == list(range(1, 101))


# --------------------------------------------------------------------------- #
# monitor output handler
# --------------------------------------------------------------------------- #


class _Data:
    def __init__(self, **values):
        self.values = values


def test_sqlite_output_rows_and_static_once():
    run_id = make_run(samples=0)
    conn = db.connect()
    out = monitor.SqliteOutput(conn, run_id)
    for i in range(3):
        out.out(_Data(timestamp="2026-11-10T10:00:00", duration=10.0 * (i + 1), energy_consumed=0.1 * (i + 1),
                      cpu_model=f"cpu{i}", cpu_count=24, run_id="cc-1"), None)
    rows = db.samples(run_id)
    assert [r["seq"] for r in rows] == [1, 2, 3]
    run = db.get_run(run_id)
    assert run["cpu_model"] == "cpu0" and run["cpu_count"] == 24 and run["codecarbon_run_id"] == "cc-1"
    assert run["last_flush_at"] == rows[-1]["ts"]

    conn.close()
    out.out(_Data(duration=1.0), None)  # closed connection: printed, never raised
    assert len(db.samples(run_id)) == 3


# --------------------------------------------------------------------------- #
# usage
# --------------------------------------------------------------------------- #


def test_usage_round_trip_and_idempotent(tmp_path):
    t = write_transcript(tmp_path / "s.jsonl")
    sess = {"harness": "claude-code", "transcript": str(t), "how": "test"}
    run_id = make_run(sess=sess, usage_note=None, ended_at="2026-11-10T10:30:00+01:00")
    assert usage.save(run_id) and usage.save(run_id)
    with db.opened() as conn:
        assert conn.execute("SELECT count(*) FROM api_call").fetchone()[0] == 8
        assert conn.execute("SELECT count(*) FROM provider_estimate").fetchone()[0] == 8
        assert conn.execute("SELECT count(*) FROM provider_estimate WHERE model_used IS NULL").fetchone()[0] == 1
    from carbon_skill import provider_impacts, tokens

    run = db.get_run(run_id)
    calls, ests = usage.load(run)
    fresh = tokens.load(run["started_at"], run["ended_at"], sess)
    assert calls == fresh
    assert provider_impacts.summary(calls, ests) == provider_impacts.summary(fresh)


def test_usage_missing_transcript_sets_note(tmp_path):
    sess = {"harness": "claude-code", "transcript": str(tmp_path / "gone.jsonl"), "how": "test"}
    run_id = make_run(sess=sess, usage_note=None)
    assert not usage.save(run_id)
    run = db.get_run(run_id)
    assert run["usage_saved_at"] is None and "transcript gone" in run["usage_note"]


# --------------------------------------------------------------------------- #
# labels, @id, delete
# --------------------------------------------------------------------------- #


def test_label_means_newest_and_id_is_exact(capsys):
    a, b = make_run("same"), make_run("same")
    assert runs.find("same")["id"] == b
    assert runs.find(f"@{a}")["id"] == a and runs.find(f"@{b}")["id"] == b
    with pytest.raises(paths.Failure):
        runs.find("@999")
    with pytest.raises(paths.UsageError):
        runs.find("@x")
    (paths.run_dir(b)).mkdir()
    assert end.command_delete("same") == 0
    assert "1 older run(s)" in capsys.readouterr().out
    assert not paths.run_dir(b).exists()
    assert runs.find("same")["id"] == a


def test_deleted_id_is_never_reused():
    make_run("x")
    b = make_run("x")
    db.delete_run(b)
    assert make_run("x") > b


def test_delete_refuses_live_run():
    run_id = make_run("live", state="running")
    with pytest.raises(paths.Failure, match="still running"):
        end.command_delete(f"@{run_id}")


# --------------------------------------------------------------------------- #
# the current session's run
# --------------------------------------------------------------------------- #

S1 = {"harness": "claude-code", "transcript": "/t/one.jsonl", "how": "$CLAUDE_CODE_SESSION_ID"}
S2 = {"harness": "claude-code", "transcript": "/t/two.jsonl", "how": "$CLAUDE_CODE_SESSION_ID"}
AGENT = {"pid": 4242, "create_time": 1.0, "name": "claude", "how": "CLAUDE_PID"}


def _here(monkeypatch, sess, inside=True, agent=AGENT):
    monkeypatch.setattr(runs, "here", lambda: (agent, sess, inside))


def test_current_run_is_this_sessions(monkeypatch):
    mine = make_run("mine", sess=S1)
    make_run("theirs", sess=S2)  # newer, other session
    _here(monkeypatch, S1)
    assert runs.find(None)["id"] == mine


def test_current_run_prefers_live(monkeypatch):
    live = make_run("a", state="running", sess=S1)
    make_run("b", sess=S1)  # newer but stopped
    _here(monkeypatch, S1)
    assert runs.find(None)["id"] == live


def test_current_run_by_agent_process(monkeypatch):
    mine = make_run("mine", agent_pid=4242, agent_ctime=1.0)
    make_run("theirs", agent_pid=5555, agent_ctime=1.0)
    _here(monkeypatch, None)
    assert runs.find(None)["id"] == mine


def test_no_run_in_this_session_fails_and_leaves_others(monkeypatch, capsys):
    other = make_run("theirs", state="running", sess=S2)
    _here(monkeypatch, S1)
    with pytest.raises(paths.Failure, match="No run was started in this session"):
        end.command_end(None)
    assert runs.is_live(other)


def test_outside_any_session_uses_newest(monkeypatch, capsys):
    make_run("old")
    newest = make_run("new")
    _here(monkeypatch, None, inside=False, agent={**AGENT, "pid": 1, "how": "top of the process tree"})
    assert runs.find(None)["id"] == newest
    assert "No agent session detected; using the most recent run 'new'" in capsys.readouterr().err


def _real_here(monkeypatch, agent, sess, known_agent):
    """The real runs.here(), with only what it reads from the machine replaced."""
    from carbon_skill import procs, tokens

    monkeypatch.setattr(procs, "detect_agent", lambda: agent)
    monkeypatch.setattr(procs, "under_known_agent", lambda: known_agent)
    monkeypatch.setattr(tokens, "resolve_session", lambda pid, cwd: sess)


PARENT = {"pid": 4242, "create_time": 1.0, "name": "codex", "how": "first non-shell parent"}
GUESS = {"harness": "claude-code", "transcript": "/t/two.jsonl", "how": "newest transcript in x (INFERRED from cwd)"}


def test_agent_without_session_never_takes_another_sessions_run(monkeypatch):
    """An agent found only by walking the process tree, with no session (Codex):
    still inside a session, so rule 3 must not hand it someone else's run."""
    other = make_run("theirs", state="running", sess=S2)
    _real_here(monkeypatch, PARENT, None, known_agent=True)
    assert runs.here()[2] is True
    with pytest.raises(paths.Failure, match="No run was started in this session"):
        end.command_end(None)
    assert runs.is_live(other)


def test_agent_without_session_finds_its_own_run(monkeypatch):
    mine = make_run("mine", agent_pid=4242, agent_ctime=1.0)
    make_run("theirs", sess=S2)
    _real_here(monkeypatch, PARENT, None, known_agent=True)
    assert runs.current_run() == (runs.status(mine), "agent")


def test_guessed_session_never_selects_a_run(monkeypatch, capsys):
    """Two sessions in one folder: the cwd guess names the other one's transcript."""
    mine = make_run("mine", agent_pid=4242, agent_ctime=1.0)
    other = make_run("theirs", state="running", sess=S2)  # newer, live, and what the guess points at
    _real_here(monkeypatch, PARENT, GUESS, known_agent=True)
    assert runs.find(None)["id"] == mine

    db.delete_run(mine)
    with pytest.raises(paths.Failure, match="No run was started in this session"):
        end.command_end(None)
    assert runs.is_live(other)

    end.command_list(session_only=True)
    assert "No runs in this session" in capsys.readouterr().out


def test_plain_terminal_in_a_project_folder_says_so(monkeypatch, capsys):
    """A terminal whose cwd matches a session's folder is still outside any session."""
    make_run("theirs", sess=S2)
    newest = make_run("new")
    terminal = {"pid": 77, "create_time": 1.0, "name": "gnome-terminal-server", "how": "first non-shell parent"}
    _real_here(monkeypatch, terminal, GUESS, known_agent=False)
    assert runs.find(None)["id"] == newest
    assert "No agent session detected; using the most recent run 'new'" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #


def test_list_filters(monkeypatch, capsys):
    make_run("x", sess=S1)
    make_run("y", sess=S2)
    make_run("x", sess=S2)
    _here(monkeypatch, S1)

    def rows(**kw):
        end.command_list(**kw)
        out = capsys.readouterr().out.splitlines()
        return [line.split()[1] for line in out[1:] if line.strip() and not line.strip().startswith("[")
                and line.split()[0].isdigit()]

    assert rows() == ["x", "y", "x"]
    assert rows(label="x") == ["x", "x"]
    assert rows(n=1) == ["x"]
    assert rows(session_only=True) == ["x"]
    end.command_list()
    out = capsys.readouterr().out
    assert "energy Wh" in out and "[Relay the table" in out and " 1.000 " in out


# --------------------------------------------------------------------------- #
# import and export
# --------------------------------------------------------------------------- #


def test_import_new_layout_and_bash_era(tmp_path):
    root = paths.data_root()
    t = write_transcript(tmp_path / "s.jsonl")
    write_run(root, "new-layout", t)
    bash = write_run(root, "bash-era", None)
    for name in ("run.json", "status.json"):
        (bash / name).unlink()
    (bash / "started_at").write_text("2026-11-10T10:00:00+01:00\n")
    (bash / "ended_at").write_text("2026-11-10T10:30:00+01:00\n")
    (bash / "stopped_by").write_text("carbon_end\n")

    db.connect().close()  # first open imports
    assert not (root / "new-layout").exists() and (root / "imported" / "new-layout" / "emissions.csv").exists()
    assert (root / "imported" / "bash-era").is_dir()

    new = runs.find("new-layout")
    assert new["state"] == "stopped" and new["cpu_method"] == "RAPL" and new["usage_saved_at"]
    assert db.last_sample(new["id"])[1] == 6  # only the last CodeCarbon run_id
    old = runs.find("bash-era")
    assert old["started_at"] == "2026-11-10T10:00:00+01:00" and old["stopped_by"] == "carbon end"
    assert old["carbon_version"] == "bash"

    # No recorded end: the last sample's time bounds the token window.
    open_end = write_run(root, "open-end", None)
    for name in ("run.json", "status.json"):
        (open_end / name).unlink()
    (open_end / "started_at").write_text("2026-11-10T10:00:00+01:00\n")
    assert legacy.import_all(quiet=True)
    run = runs.find("open-end")
    assert run["ended_at"] == db.last_sample(run["id"])[0]["ts"]

    # A later import pass finds nothing new.
    assert legacy.import_all(quiet=True) == []


def test_export_csv_has_codecarbon_header():
    run_id = make_run("exp", samples=3, cpu_count=24.0, codecarbon_run_id="cc-9")
    text = export.csv_text(db.get_run(run_id))
    rows = list(csv.DictReader(io.StringIO(text)))
    assert next(csv.reader(io.StringIO(text))) == HEADER
    assert len(rows) == 3 and rows[-1]["energy_consumed"] == "0.003" and rows[0]["cpu_count"] == "24"
    assert rows[0]["run_id"] == "cc-9" and rows[0]["project_name"] == "exp"


def test_export_sql_loads_into_empty_database(tmp_path):
    make_run("dump", samples=2)
    sql = "\n".join(db.dump())
    target = sqlite3.connect(tmp_path / "copy.db")
    target.executescript(sql)
    assert target.execute("SELECT count(*) FROM sample").fetchone()[0] == 2
    assert target.execute("SELECT label FROM run").fetchone()[0] == "dump"
    target.close()


def _restore(monkeypatch, tmp_path, sql):
    root = tmp_path / "restored"
    root.mkdir()
    target = sqlite3.connect(root / "carbon.db")
    target.executescript(sql)
    target.close()
    monkeypatch.setenv("CARBON_RUN_ROOT", str(root))


def test_export_sql_restores_a_database_carbon_opens(tmp_path, monkeypatch):
    run_id = make_run("dump", samples=2)
    sql = "\n".join(db.dump())
    _restore(monkeypatch, tmp_path, sql)
    assert db.health() == (db.VERSION, "ok")
    assert runs.find("dump")["id"] == run_id and db.last_sample(run_id)[1] == 2
    assert make_run("after") == run_id + 1  # and it takes new runs


def test_dump_without_version_is_adopted(tmp_path, monkeypatch):
    """A dump written before the version line was added (plain iterdump)."""
    run_id = make_run("dump")
    with db.opened() as conn:
        sql = "\n".join(conn.iterdump())
    assert "user_version" not in sql
    _restore(monkeypatch, tmp_path, sql)
    assert db.health() == (db.VERSION, "ok")
    assert runs.find("dump")["id"] == run_id


def test_cli_export_and_list(tmp_path, capsys):
    from carbon_skill import cli

    run_id = make_run("cli", samples=2)
    out = tmp_path / "e.csv"
    assert cli.main(["export", f"@{run_id}", "-o", str(out)]) == 0
    assert out.read_text().startswith("timestamp,project_name,run_id")
    assert cli.main(["export", "cli", "--format", "sql"]) == 2
    assert cli.main(["history", "-n", "0"]) == 0
    assert os.path.exists(db.path())
