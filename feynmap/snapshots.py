"""Deterministic repository snapshot identity and persistent semantic graph storage.

Phase 2A gives FeynMap a stable object to query. A snapshot binds one semantic
graph to the repository content and analysis configuration that produced it.
Snapshots are immutable; a separate pointer marks the current snapshot for a
repository.
"""
from __future__ import annotations

import configparser
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from .core.model import SEMANTIC_SCHEMA_VERSION, SemanticGraph


SNAPSHOT_SCHEMA = "feynmap.repository_snapshot"
SNAPSHOT_SCHEMA_VERSION = "1.0.0"
EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".feynmap",
}


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class FileFingerprint:
    path: str
    sha256: str
    size: int

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "FileFingerprint":
        return cls(
            path=str(payload.get("path", "")),
            sha256=str(payload.get("sha256", "")),
            size=int(payload.get("size", 0)),
        )


@dataclass
class RepositorySnapshot:
    snapshot_id: str
    repository_key: str
    locator: str
    root_hint: str
    revision: Optional[str]
    content_hash: str
    graph_hash: str
    graph_schema_version: str
    analysis_options: Dict[str, Any]
    files: List[FileFingerprint] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self, include_files: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema": SNAPSHOT_SCHEMA,
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "repository_key": self.repository_key,
            "locator": self.locator,
            "root_hint": self.root_hint,
            "revision": self.revision,
            "content_hash": self.content_hash,
            "graph_hash": self.graph_hash,
            "graph_schema_version": self.graph_schema_version,
            "analysis_options": self.analysis_options,
            "file_count": len(self.files),
            "created_at": self.created_at,
        }
        if include_files:
            payload["files"] = [item.to_dict() for item in self.files]
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "RepositorySnapshot":
        schema = payload.get("schema")
        if schema and schema != SNAPSHOT_SCHEMA:
            raise ValueError("unsupported snapshot schema: %s" % schema)
        version = payload.get("schema_version")
        if version and version != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported snapshot schema version: %s" % version)
        return cls(
            snapshot_id=str(payload.get("snapshot_id", "")),
            repository_key=str(payload.get("repository_key", "")),
            locator=str(payload.get("locator", "")),
            root_hint=str(payload.get("root_hint", "")),
            revision=payload.get("revision"),
            content_hash=str(payload.get("content_hash", "")),
            graph_hash=str(payload.get("graph_hash", "")),
            graph_schema_version=str(payload.get("graph_schema_version", SEMANTIC_SCHEMA_VERSION)),
            analysis_options=dict(payload.get("analysis_options") or {}),
            files=[FileFingerprint.from_dict(item) for item in payload.get("files", []) if isinstance(item, dict)],
            created_at=str(payload.get("created_at", _utc_now())),
        )


def repository_file_inventory(project_path: Path) -> List[FileFingerprint]:
    """Hash repository files deterministically while excluding generated/cache dirs."""
    root = project_path.resolve()
    result: List[FileFingerprint] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
        except OSError:
            continue
        result.append(FileFingerprint(relative.as_posix(), digest.hexdigest(), size))
    return result


def _git_directory(root: Path) -> Optional[Path]:
    marker = root / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():
        try:
            content = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if content.startswith("gitdir:"):
            raw = content.split(":", 1)[1].strip()
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (root / candidate).resolve()
            return candidate
    return None


def _git_revision(root: Path) -> Optional[str]:
    git_dir = _git_directory(root)
    if git_dir is None:
        return None
    head = git_dir / "HEAD"
    try:
        value = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value.startswith("ref:"):
        return value or None
    ref = value.split(":", 1)[1].strip()
    ref_path = git_dir / ref
    try:
        return ref_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        packed = git_dir / "packed-refs"
        try:
            for line in packed.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#") or line.startswith("^"):
                    continue
                sha, _, name = line.partition(" ")
                if name.strip() == ref:
                    return sha.strip() or None
        except OSError:
            return None
    return None


def _sanitize_locator(value: str) -> str:
    text = value.strip()
    if "://" not in text:
        return text
    parts = urlsplit(text)
    hostname = parts.hostname or ""
    if parts.port:
        hostname = "%s:%s" % (hostname, parts.port)
    return urlunsplit((parts.scheme, hostname, parts.path, parts.query, parts.fragment))


def _git_origin(root: Path) -> Optional[str]:
    git_dir = _git_directory(root)
    if git_dir is None:
        return None
    config_path = git_dir / "config"
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(str(config_path), encoding="utf-8")
    except (OSError, configparser.Error):
        return None
    section = 'remote "origin"'
    if not parser.has_section(section):
        return None
    try:
        value = parser.get(section, "url")
    except (configparser.Error, KeyError):
        return None
    return _sanitize_locator(value) if value else None


def repository_locator(project_path: Path) -> str:
    root = project_path.resolve()
    origin = _git_origin(root)
    return origin or "path:%s" % root.as_posix()


def capture_repository_snapshot(
    project_path: Path,
    graph: SemanticGraph,
    analysis_options: Optional[Dict[str, Any]] = None,
    created_at: Optional[str] = None,
) -> RepositorySnapshot:
    """Bind a semantic graph to deterministic repository and analysis identity."""
    root = project_path.resolve()
    files = repository_file_inventory(root)
    locator = repository_locator(root)
    repository_key = _sha256_text(locator)
    revision = _git_revision(root)
    inventory_payload = [item.to_dict() for item in files]
    content_hash = _sha256_text(_canonical_json(inventory_payload))
    graph_payload = graph.to_dict()
    graph_hash = _sha256_text(_canonical_json(graph_payload))
    options = dict(analysis_options or {})
    if not options:
        for key in ("language_selection", "framework_selection"):
            if key in graph.metadata:
                options[key] = graph.metadata[key]
    identity_payload = {
        "repository_key": repository_key,
        "revision": revision,
        "content_hash": content_hash,
        "graph_hash": graph_hash,
        "graph_schema_version": SEMANTIC_SCHEMA_VERSION,
        "analysis_options": options,
    }
    snapshot_id = _sha256_text(_canonical_json(identity_payload))
    return RepositorySnapshot(
        snapshot_id=snapshot_id,
        repository_key=repository_key,
        locator=locator,
        root_hint=root.as_posix(),
        revision=revision,
        content_hash=content_hash,
        graph_hash=graph_hash,
        graph_schema_version=SEMANTIC_SCHEMA_VERSION,
        analysis_options=options,
        files=files,
        created_at=created_at or _utc_now(),
    )


class SnapshotStore:
    """SQLite-backed immutable snapshot store with a per-repository current pointer."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    repository_key TEXT NOT NULL,
                    locator TEXT NOT NULL,
                    root_hint TEXT NOT NULL,
                    revision TEXT,
                    content_hash TEXT NOT NULL,
                    graph_hash TEXT NOT NULL,
                    graph_schema_version TEXT NOT NULL,
                    analysis_options_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    inventory_json TEXT NOT NULL,
                    graph_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_repository
                    ON snapshots(repository_key, created_at);
                CREATE TABLE IF NOT EXISTS current_snapshots (
                    repository_key TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id)
                );
                """
            )

    def save(self, snapshot: RepositorySnapshot, graph: SemanticGraph, set_current: bool = True) -> None:
        graph_json = _canonical_json(graph.to_dict())
        if _sha256_text(graph_json) != snapshot.graph_hash:
            raise ValueError("graph does not match snapshot graph_hash")
        inventory_json = _canonical_json([item.to_dict() for item in snapshot.files])
        if _sha256_text(inventory_json) != snapshot.content_hash:
            raise ValueError("snapshot inventory does not match content_hash")

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT graph_hash, content_hash FROM snapshots WHERE snapshot_id = ?",
                (snapshot.snapshot_id,),
            ).fetchone()
            if existing is not None:
                if existing["graph_hash"] != snapshot.graph_hash or existing["content_hash"] != snapshot.content_hash:
                    raise ValueError("immutable snapshot id collision")
            else:
                connection.execute(
                    """
                    INSERT INTO snapshots (
                        snapshot_id, repository_key, locator, root_hint, revision,
                        content_hash, graph_hash, graph_schema_version,
                        analysis_options_json, created_at, inventory_json, graph_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.repository_key,
                        snapshot.locator,
                        snapshot.root_hint,
                        snapshot.revision,
                        snapshot.content_hash,
                        snapshot.graph_hash,
                        snapshot.graph_schema_version,
                        _canonical_json(snapshot.analysis_options),
                        snapshot.created_at,
                        inventory_json,
                        graph_json,
                    ),
                )
            if set_current:
                connection.execute(
                    """
                    INSERT INTO current_snapshots(repository_key, snapshot_id, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(repository_key) DO UPDATE SET
                        snapshot_id = excluded.snapshot_id,
                        updated_at = excluded.updated_at
                    """,
                    (snapshot.repository_key, snapshot.snapshot_id, _utc_now()),
                )

    def load(self, snapshot_id: str) -> Tuple[RepositorySnapshot, SemanticGraph]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise KeyError("unknown snapshot: %s" % snapshot_id)
        files_payload = json.loads(row["inventory_json"])
        snapshot = RepositorySnapshot(
            snapshot_id=row["snapshot_id"],
            repository_key=row["repository_key"],
            locator=row["locator"],
            root_hint=row["root_hint"],
            revision=row["revision"],
            content_hash=row["content_hash"],
            graph_hash=row["graph_hash"],
            graph_schema_version=row["graph_schema_version"],
            analysis_options=json.loads(row["analysis_options_json"]),
            files=[FileFingerprint.from_dict(item) for item in files_payload],
            created_at=row["created_at"],
        )
        graph_payload = json.loads(row["graph_json"])
        graph = SemanticGraph.from_dict(graph_payload)
        if _sha256_text(_canonical_json(graph.to_dict())) != snapshot.graph_hash:
            raise ValueError("stored graph failed snapshot hash verification")
        return snapshot, graph

    def current_snapshot_id(self, repository_key: str) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT snapshot_id FROM current_snapshots WHERE repository_key = ?",
                (repository_key,),
            ).fetchone()
        return str(row["snapshot_id"]) if row is not None else None

    def load_current(self, repository_key: str) -> Optional[Tuple[RepositorySnapshot, SemanticGraph]]:
        snapshot_id = self.current_snapshot_id(repository_key)
        return self.load(snapshot_id) if snapshot_id else None

    def list_snapshots(self, repository_key: str) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT snapshot_id, revision, content_hash, graph_hash, created_at
                FROM snapshots
                WHERE repository_key = ?
                ORDER BY created_at DESC, snapshot_id DESC
                """,
                (repository_key,),
            ).fetchall()
        return [dict(row) for row in rows]


def capture_and_store(
    project_path: Path,
    graph: SemanticGraph,
    store: SnapshotStore,
    analysis_options: Optional[Dict[str, Any]] = None,
) -> RepositorySnapshot:
    snapshot = capture_repository_snapshot(project_path, graph, analysis_options=analysis_options)
    store.save(snapshot, graph, set_current=True)
    return snapshot
