"""Independent expected routes and seeded Python/compact regression.

Runs on both Python versions even when the optional Rust wheel is absent.
The native wheel repeats this corpus in the rust-native-build workflow.
"""
from pathlib import Path

from feynmap.rust_routing_conformance import (
    SEED,
    SYNTHETIC_REQUESTS_PER_GRAPH,
    SYNTHETIC_SIZES,
    run_oracles,
    run_seeded,
    synthetic_graph,
)


ROOT = Path(__file__).resolve().parents[1]
ORACLES = ROOT / "tests/fixtures/contracts/s6_7_routing_oracles.json"


def test_independent_routing_oracles_match_python_and_compact_boundary():
    count, identifiers = run_oracles(ORACLES)
    assert count == 12
    assert len(set(identifiers)) == count
    assert "oracle/lexical-tie/stable-lexical-tie" in identifiers
    assert "oracle/unicode-casefold/unicode-uppercase-query" in identifiers
    assert "oracle/anchor-and-adjacency/empty-query-with-anchored-neighbor" in identifiers


def test_seeded_python_compact_reference_stays_deterministic():
    count, regions = run_seeded(None)
    assert count == len(SYNTHETIC_SIZES) * SYNTHETIC_REQUESTS_PER_GRAPH
    assert regions[0] == 1
    assert regions[-1] >= 400


def test_independent_synthetic_graph_reproducibility():
    first = synthetic_graph(37, seed=SEED)
    second = synthetic_graph(37, seed=SEED)
    assert [item.id for item in first.nodes] == [item.id for item in second.nodes]
    assert [item.name for item in first.nodes] == [item.name for item in second.nodes]
    assert [(edge.source, edge.target) for edge in first.edges] == [
        (edge.source, edge.target) for edge in second.edges
    ]
