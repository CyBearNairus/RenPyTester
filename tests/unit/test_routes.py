import pytest

from renpytester.model import ERROR, Finding
from renpytester.routes import Coverage, Frontier
from renpytester.runner import Exploration, split_labels

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
    assert (report["executed"], report["total"], report["low_confidence"]) == (2, 5, 0)
    assert report["files"] == {"game/a.rpy": [2, 3], "game/b.rpy": [0, 2]}
    assert report["labels"]["start"] == {
        "file": "game/a.rpy", "line": 3, "executed": 2, "low_confidence": 0, "total": 3}
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
    assert frontier.waiting == {(None, (1,)), (None, (2,))}
    assert [step["choice"] for step in frontier.path] == ["A"]

    frontier.feed({"ev": "path_end", "reason": "end", "covered": []})
    assert frontier.path == []
    assert frontier.reasons == {"end": 1}

    frontier.feed({"ev": "branch_start", "prefix": [2], "path": []})
    frontier.feed({"ev": "decision", "kind": "menu", "file": "game/a.rpy", "line": 5, "choice": "C", "index": 2})
    assert frontier.waiting == {(None, (1,))}
    assert frontier.made_up is False
    assert [step["choice"] for step in frontier.path] == ["C"]
    assert frontier.last == {"file": "game/a.rpy", "line": 5}
    assert frontier.done is None


@pytest.mark.req("EXP-014")
def test_statements_reached_only_after_a_skip_are_counted_apart():
    coverage = Coverage()
    coverage.add_map(MAP)
    coverage.add_executed(["label:start"], ["game/a.rpy#1", "label:other", "game/b.rpy#1"])
    coverage.add_executed(["game/a.rpy#1"])
    report = coverage.report()
    assert (report["executed"], report["low_confidence"], report["total"]) == (2, 2, 5)
    assert report["labels"]["other"]["low_confidence"] == 2
    assert report["unreached_labels"] == []


@pytest.mark.req("EXP-007", "RUN-012", "EXP-013")
def test_frontier_follows_label_runs():
    frontier = Frontier(Coverage())
    frontier.feed({"ev": "start", "map": MAP, "labels": ["other", "third"]})
    assert frontier.labels == ["other", "third"]
    step = {"kind": "label", "file": "game/b.rpy", "line": 1, "choice": "other", "index": 0}
    frontier.feed({"ev": "label_start", "label": "other", "path": [step]})
    frontier.feed({"ev": "branch", "prefix": [1], "label": "other"})
    assert frontier.labels == ["third"]
    assert frontier.label_runs == 1
    assert frontier.waiting == {("other", (1,))}
    # Whatever happens now happens in a state the tool made up.
    assert frontier.made_up is True
    frontier.feed({"ev": "path_end", "reason": "end", "covered": []})
    assert frontier.made_up is False

    # A process that takes over is told what is left, and keeps to it.
    second = Frontier(Coverage(), frontier.waiting, frontier.labels)
    second.feed({"ev": "start", "map": MAP, "labels": []})
    assert second.labels == ["third"]


@pytest.mark.req("RUN-014", "EXP-011")
def test_labels_are_shared_out_between_the_processes_that_do_not_explore_the_story():
    labels = ["label%02d" % i for i in range(20)]
    # One process: it explores the story and then plays the labels itself.
    assert split_labels(labels, 1) == []
    shares = split_labels(labels, 3)
    assert len(shares) == 2
    assert sorted(name for share in shares for name in share) == labels
    # A handful of labels is not worth more than one extra process.
    assert split_labels(labels[:5], 8) == [labels[:5]]
    assert split_labels([], 8) == []


@pytest.mark.req("NFR-001", "EXP-015")
def test_findings_are_put_in_an_order_that_does_not_depend_on_which_process_reported_first():
    def finding(line, label=None):
        path = [{"kind": "label", "choice": label}] if label else []
        return Finding("exception", ERROR, "finding.exception", {}, "game/a.rpy", line, path=path)

    def order(arrivals):
        exploration = Exploration(["first", "second"])
        for lane, item in arrivals:
            exploration.collect(item, lane, 1)
        return [f.line for _key, f in sorted(exploration.findings, key=lambda entry: entry[0])]

    story, first, second = finding(1), finding(2, "first"), finding(3, "second")
    assert order([(0, story), (0, first), (0, second)]) == [1, 2, 3]
    assert order([(2, second), (1, first), (0, story)]) == [1, 2, 3]
