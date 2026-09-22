from feynmap.adapters.python_boundaries import (
    _build_boundary_index,
    _node_for_line,
    _owners_for_lines,
)
from feynmap.core import NodeKind, SemanticGraph, SemanticNode, SourceLocation


def _node(name, kind, line, end_line=None, path="pkg/mod.py"):
    return SemanticNode(
        id="node:" + name,
        name=name,
        kind=kind,
        language="python",
        location=SourceLocation(path, line, end_line),
    )


def _legacy_owner(nodes, line):
    exact = []
    preceding = []
    for node in nodes:
        start = node.location.line or 1
        end = node.location.end_line
        if end is not None and start <= line <= end:
            exact.append(node)
        elif start <= line:
            preceding.append(node)
    if exact:
        exact.sort(
            key=lambda item: (item.location.end_line or item.location.line or 1)
            - (item.location.line or 1)
        )
        return exact[0]
    if preceding:
        preceding.sort(key=lambda item: item.location.line or 1, reverse=True)
        return preceding[0]
    return None


def test_owners_for_lines_matches_historical_resolution():
    owners = [
        _node("outer", NodeKind.FUNCTION, 5, 80),
        _node("inner", NodeKind.FUNCTION, 20, 30),
        _node("later", NodeKind.METHOD, 100, 120),
        _node("unknown_end", NodeKind.HANDLER, 140, None),
    ]
    lines = [1, 5, 19, 20, 25, 31, 79, 81, 100, 121, 140, 200]

    resolved = _owners_for_lines(owners, lines)

    for line in lines:
        expected = _legacy_owner(owners, line)
        actual = resolved.get(line)
        assert (actual.id if actual else None) == (expected.id if expected else None)


def test_boundary_index_scans_graph_once_and_groups_by_path():
    module = _node("module", NodeKind.MODULE, 1)
    function = _node("function", NodeKind.FUNCTION, 10, 20)
    other = _node("other", NodeKind.FUNCTION, 1, 2, path="other.py")
    non_python = SemanticNode(
        id="node:js",
        name="js",
        kind=NodeKind.FUNCTION,
        language="javascript",
        location=SourceLocation("pkg/mod.py", 1, 2),
    )
    graph = SemanticGraph(nodes=[module, function, other, non_python])

    modules, owners = _build_boundary_index(graph)

    assert modules["pkg/mod.py"] is module
    assert owners["pkg/mod.py"] == [function]
    assert owners["other.py"] == [other]
    assert "javascript" not in {node.language for rows in owners.values() for node in rows}


def test_single_line_compatibility_helper_uses_same_semantics():
    module = _node("module", NodeKind.MODULE, 1)
    outer = _node("outer", NodeKind.FUNCTION, 5, 50)
    inner = _node("inner", NodeKind.FUNCTION, 20, 25)
    graph = SemanticGraph(nodes=[module, outer, inner])

    assert _node_for_line(graph, "pkg/mod.py", 22) is inner
    assert _node_for_line(graph, "pkg/mod.py", 40) is outer
