import pytest

from renpytester.routes import Coverage, Frontier

MAP = {
    "files": {
        "game/a.rpy": ["label:start", "game/a.rpy#1", "game/a.rpy#2"], "game/b.rpy": ["label:other", "game/b.rpy#1"]},
    "labels": {
        "start": {"file": "game/a.rpy", "line": 3, "ids": ["label:start", "game/a.rpy#1", "game/a.rpy#2"]},
        "other": {"file": "game/b.rpy", "line": 1, "ids": ["label:other", "game/b.rpy#1"]}},
}


@pytest.mark.req("EXP-005")
def test_coverage_is_reported_per_file_and_per_label():
    coverage = Coverage()
    assert coverage.report() is None
    coverage.add_map(MAP)
    coverage.add_executed(["label:start", "game/a.rpy#1"])
    report = coverage.report()
    assert (report["executed"], report["total"]) == (2, 5)
    assert report["files"] == {"game/a.rpy": [2, 3], "game/b.rpy": [0, 2]}
    assert report["labels"]["start"] == {"file": "game/a.rpy", "line": 3, "executed": 2, "total": 3}
    assert report["unreached_labels"] == ["other"]
    assert coverage.percent() == 40


@pytest.mark.req("EXP-005", "RUN-012")
def test_coverage_from_several_processes_is_merged():
    coverage = Coverage()
    first = Frontier(coverage)
    first.feed({"ev": "start", "map": MAP})
    first.feed({"ev": "path_end", "reason": "end", "covered": ["label:start", "game/a.rpy#1"]})
    second = Frontier(coverage, first.waiting)
    second.feed({"ev": "start", "map": MAP})
    second.feed({"ev": "heartbeat", "covered": ["game/a.rpy#1", "label:other"], "steps": 9})
    assert coverage.count == 3
    assert coverage.total == 5
    assert second.steps == 9


@pytest.mark.req("RUN-012", "EXP-004")
def test_frontier_knows_what_is_waiting_and_where_the_current_path_is():
    frontier = Frontier(Coverage())
    frontier.feed({"ev": "start", "map": MAP})
    frontier.feed({"ev": "branch", "prefix": [1]})
    frontier.feed({"ev": "branch", "prefix": [2]})
    frontier.feed({"ev": "decision", "kind": "menu", "file": "game/a.rpy", "line": 5, "choice": "A", "index": 0})
    assert frontier.waiting == {(1,), (2,)}
    assert [step["choice"] for step in frontier.path] == ["A"]

    frontier.feed({"ev": "path_end", "reason": "end", "covered": []})
    assert frontier.path == []
    assert frontier.reasons == {"end": 1}

    frontier.feed({"ev": "branch_start", "prefix": [2], "path": []})
    frontier.feed({"ev": "decision", "kind": "menu", "file": "game/a.rpy", "line": 5, "choice": "C", "index": 2})
    assert frontier.waiting == {(1,)}
    assert [step["choice"] for step in frontier.path] == ["C"]
    assert frontier.last == {"file": "game/a.rpy", "line": 5}
    assert frontier.done is None
