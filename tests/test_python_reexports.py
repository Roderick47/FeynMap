from pathlib import Path

from feynmap import EdgeKind, FeynMapEngine


def _has_edge(graph, source_qname, target_qname, kind):
    source = next(node for node in graph.nodes if node.qualified_name == source_qname)
    target = next(node for node in graph.nodes if node.qualified_name == target_qname)
    return any(
        edge.source == source.id and edge.target == target.id and edge.kind == kind
        for edge in graph.edges
    )


def test_transitive_package_reexport_resolves_to_defining_symbol(tmp_path: Path):
    package = tmp_path / "pkg"
    sub = package / "sub"
    sub.mkdir(parents=True)

    (package / "__init__.py").write_text(
        "from .sub import Thing\n__all__ = ['Thing']\n",
        encoding="utf-8",
    )
    (sub / "__init__.py").write_text(
        "from .impl import Thing\n__all__ = ['Thing']\n",
        encoding="utf-8",
    )
    (sub / "impl.py").write_text(
        "class Thing:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        "from pkg import Thing\n\ndef build():\n    return Thing()\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), language="python", framework="none")

    assert _has_edge(graph, "app.build", "pkg.sub.impl.Thing", EdgeKind.CALLS)
    assert _has_edge(graph, "app", "pkg.sub.impl.Thing", EdgeKind.IMPORTS)

    metadata = graph.metadata["python_reexport_resolution"]
    assert metadata["resolved_aliases"] >= 2
    assert metadata["call_edges_added"] >= 1
    assert metadata["strategy"] == "unique-static-alias-chain-only"


def test_reexport_call_keeps_alias_chain_as_evidence(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from .impl import Service\n__all__ = ['Service']\n",
        encoding="utf-8",
    )
    (package / "impl.py").write_text(
        "class Service:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        "from pkg import Service\n\ndef make():\n    return Service()\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), language="python", framework="none")
    source = next(node for node in graph.nodes if node.qualified_name == "consumer.make")
    target = next(node for node in graph.nodes if node.qualified_name == "pkg.impl.Service")
    edge = next(
        edge
        for edge in graph.edges
        if edge.source == source.id and edge.target == target.id and edge.kind == EdgeKind.CALLS
    )

    resolution = edge.attributes["python_resolution"]
    assert resolution["strategy"] == "package_reexport"
    assert resolution["alias_chain"] == ["pkg.Service", "pkg.impl.Service"]
    assert edge.evidence[0].detector == "python.ast.reexport_call"


def test_reexported_type_annotation_grounds_instance_method_call(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from .impl import Registry\n__all__ = ['Registry']\n",
        encoding="utf-8",
    )
    (package / "impl.py").write_text(
        "class Registry:\n    def ping(self):\n        return True\n",
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        "from typing import Optional\n"
        "from pkg import Registry\n\n"
        "class Engine:\n"
        "    def __init__(self, registry: Optional[Registry] = None):\n"
        "        self.registry = registry or Registry()\n\n"
        "    def run(self):\n"
        "        return self.registry.ping()\n",
        encoding="utf-8",
    )

    graph = FeynMapEngine().analyze(str(tmp_path), language="python", framework="none")
    source = next(node for node in graph.nodes if node.qualified_name == "consumer.Engine.run")
    target = next(node for node in graph.nodes if node.qualified_name == "pkg.impl.Registry.ping")
    edge = next(
        edge
        for edge in graph.edges
        if edge.source == source.id and edge.target == target.id and edge.kind == EdgeKind.CALLS
    )

    resolution = edge.attributes["python_resolution"]
    assert resolution["strategy"] == "instance_attribute_type_reexport"
    assert resolution["type_alias_chain"] == ["pkg.Registry", "pkg.impl.Registry"]
    assert edge.evidence[0].detector == "python.ast.instance_attribute_call"

    metadata = graph.metadata["python_attribute_resolution"]
    assert metadata["reexport_aliases_consulted"] >= 1
    assert metadata["alias_grounded_call_edges"] >= 1
