"""Tests for the evaluation framework."""

from __future__ import annotations

import json
from pathlib import Path

from coding_agent.evals.runner import check_assertion
from coding_agent.evals.task import EvalAssertion, EvalTask

# ── EvalTask loading ──────────────────────────────────────────────────


def test_load_task_from_dict() -> None:
    data = {
        "id": "t1",
        "name": "Test",
        "description": "A test task",
        "prompt": "Do something",
        "assertions": [
            {"type": "file_exists", "path": "a.txt"},
        ],
    }
    task = EvalTask.from_dict(data)
    assert task.id == "t1"
    assert len(task.assertions) == 1
    assert task.assertions[0].type == "file_exists"


def test_load_all_tasks(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"0{i}.json").write_text(json.dumps({
            "id": f"t{i}", "name": f"Task {i}",
            "description": "d", "prompt": "p",
            "assertions": [],
        }))
    tasks = EvalTask.load_all(tmp_path)
    assert len(tasks) == 3
    assert tasks[0].id == "t0"


def test_load_builtin_tasks() -> None:
    tasks_dir = Path(__file__).parent.parent.parent / "src" / "coding_agent" / "evals" / "tasks"
    tasks = EvalTask.load_all(tasks_dir)
    assert len(tasks) == 10


# ── Assertion checking ────────────────────────────────────────────────


def test_file_exists_pass(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("hi")
    r = check_assertion(EvalAssertion(type="file_exists", path="x.txt"), tmp_path)
    assert r.passed


def test_file_exists_fail(tmp_path: Path) -> None:
    r = check_assertion(EvalAssertion(type="file_exists", path="nope.txt"), tmp_path)
    assert not r.passed


def test_file_contains_pass(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("hello world")
    r = check_assertion(
        EvalAssertion(type="file_contains", path="f.txt", content="hello"),
        tmp_path,
    )
    assert r.passed


def test_file_contains_fail(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("hello world")
    r = check_assertion(
        EvalAssertion(type="file_contains", path="f.txt", content="zzz"),
        tmp_path,
    )
    assert not r.passed


def test_file_contains_missing_file(tmp_path: Path) -> None:
    r = check_assertion(
        EvalAssertion(type="file_contains", path="nope.txt", content="x"),
        tmp_path,
    )
    assert not r.passed


def test_file_not_contains_pass(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("hello")
    r = check_assertion(
        EvalAssertion(type="file_not_contains", path="f.txt", content="zzz"),
        tmp_path,
    )
    assert r.passed


def test_file_not_contains_fail(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("hello")
    r = check_assertion(
        EvalAssertion(type="file_not_contains", path="f.txt", content="hello"),
        tmp_path,
    )
    assert not r.passed


def test_file_equals_pass(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("exact")
    r = check_assertion(
        EvalAssertion(type="file_equals", path="f.txt", content="exact"),
        tmp_path,
    )
    assert r.passed


def test_file_equals_fail(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("different")
    r = check_assertion(
        EvalAssertion(type="file_equals", path="f.txt", content="exact"),
        tmp_path,
    )
    assert not r.passed


def test_command_output_pass(tmp_path: Path) -> None:
    r = check_assertion(
        EvalAssertion(type="command_output", command="echo hello", expected="hello"),
        tmp_path,
    )
    assert r.passed


def test_command_output_fail(tmp_path: Path) -> None:
    r = check_assertion(
        EvalAssertion(type="command_output", command="echo hello", expected="goodbye"),
        tmp_path,
    )
    assert not r.passed


def test_unknown_assertion_type(tmp_path: Path) -> None:
    r = check_assertion(EvalAssertion(type="magic", path="x"), tmp_path)
    assert not r.passed


# ── EvalAssertion.describe ────────────────────────────────────────────


def test_assertion_describe() -> None:
    a = EvalAssertion(type="file_exists", path="a.txt")
    assert "a.txt" in a.describe()

    a2 = EvalAssertion(type="file_contains", path="b.txt", content="hello")
    assert "hello" in a2.describe()
