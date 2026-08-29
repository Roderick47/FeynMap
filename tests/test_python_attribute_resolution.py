from feynmap import EdgeKind, FeynMapEngine


def _node(graph, qualified_name):
    matches = [node for node in graph.nodes if node.qualified_name == qualified_name]
    assert matches, "missing node %s" % qualified_name
    return matches[0]


def _has_edge(graph, source, target, kind):
    return any(edge.source == source.id and edge.target == target.id and edge.kind == kind for edge in graph.edges)


def test_resolves_self_attribute_method_from_unique_type_evidence(tmp_path):
    (tmp_path / "app.py").write_text(
        "from typing import Optional\n\n"
        "class Worker:\n"
        "    def run(self):\n"
        "        return 1\n\n"
        "class App:\n"
        "    def __init__(self, worker: Optional[Worker] = None):\n"
        "        self.worker = worker or Worker()\n\n"
        "    def execute(self):\n"
        "        return self.worker.run()\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), language="python", framework="none")
    execute = _node(graph, "app.App.execute")
    run = _node(graph, "app.Worker.run")

    assert _has_edge(graph, execute, run, EdgeKind.CALLS)
    edge = next(
        edge
        for edge in graph.edges
        if edge.source == execute.id and edge.target == run.id and edge.kind == EdgeKind.CALLS
    )
    assert edge.attributes["python_resolution"]["strategy"] == "instance_attribute_type"
    assert "app.Worker" in edge.attributes["python_resolution"]["candidate_types"]
    assert "self.worker.run" not in execute.attributes.get("python", {}).get("unresolved_calls", [])


def test_annotation_only_assignment_is_enough_when_type_is_unique(tmp_path):
    (tmp_path / "app.py").write_text(
        "class Worker:\n"
        "    def run(self):\n"
        "        return 1\n\n"
        "class App:\n"
        "    def __init__(self, worker: Worker):\n"
        "        self.worker = worker\n\n"
        "    def execute(self):\n"
        "        return self.worker.run()\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), language="python", framework="none")
    assert _has_edge(
        graph,
        _node(graph, "app.App.execute"),
        _node(graph, "app.Worker.run"),
        EdgeKind.CALLS,
    )


def test_ambiguous_attribute_types_remain_unresolved(tmp_path):
    (tmp_path / "app.py").write_text(
        "class WorkerA:\n"
        "    def run(self):\n"
        "        return 'a'\n\n"
        "class WorkerB:\n"
        "    def run(self):\n"
        "        return 'b'\n\n"
        "class App:\n"
        "    def __init__(self, flag):\n"
        "        self.worker = WorkerA() if flag else WorkerB()\n\n"
        "    def execute(self):\n"
        "        return self.worker.run()\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), language="python", framework="none")
    execute = _node(graph, "app.App.execute")
    worker_a = _node(graph, "app.WorkerA.run")
    worker_b = _node(graph, "app.WorkerB.run")

    assert not _has_edge(graph, execute, worker_a, EdgeKind.CALLS)
    assert not _has_edge(graph, execute, worker_b, EdgeKind.CALLS)
    assert "self.worker.run" in execute.attributes.get("python", {}).get("unresolved_calls", [])


def test_self_hosting_engine_resolver_relationship_is_now_grounded():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    graph = FeynMapEngine().analyze(str(root), language="python", framework="none")
    analyze = _node(graph, "feynmap.engine.FeynMapEngine.analyze")
    resolve = _node(graph, "feynmap.integration.IntegrationResolver.resolve")

    assert _has_edge(graph, analyze, resolve, EdgeKind.CALLS)
