# FeynMap V2 - Portable Code Analysis with Physics-Inspired Notation

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

FeynMap is a powerful code analysis tool that uses physics-inspired notation to help developers and AI editors understand Python codebase architecture. It currently supports Django, Flask, FastAPI, and generic Python projects. Transform complex code relationships into elegant physics diagrams.

> **Rails support has been removed for now.** FeynMap does not yet include a Ruby parser, so advertising Rails analysis would be misleading. Ruby support may return later through a proper language-adapter implementation.

## 📑 Table of Contents

- [Features](#-features)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Supported Frameworks](#-supported-frameworks)
- [Output & Examples](#-output--examples)
- [Physics Notation Guide](#-physics-notation-guide)
- [Configuration](#️-configuration)
- [Advanced Usage](#-advanced-usage)
- [Requirements](#-requirements)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

## 🚀 Features

- **Python Framework Support**: Django, Flask, FastAPI, and generic Python projects
- **Physics-Inspired Notation**: Uses particle physics concepts to represent code relationships intuitively
- **Smart Lazy Loading**: Analyze only the components you care about for faster results
- **Interaction Chain Depth Tracing**: Recursively follow view → service → utility → model call paths instead of stopping at one-hop relationships
- **Semantic Similarity Clustering**: Group functionally similar nodes even when they are not directly connected, such as CRUD views for the same model or serializers touching the same data
- **Change Impact Prediction**: Feed FeynMap a git diff to identify changed graph nodes and recursively trace reverse dependencies to views, serializers, templates, and other likely breakage surfaces
- **Ghost State Detection**: Automatically identify unused/dead code in your codebase
- **Enhanced Visualization**: Generate structured data compatible with Feynman diagram tools
- **Zero Runtime Dependencies**: Uses only Python standard library for core functionality
- **Configurable Patterns**: Define custom detection rules for your framework or codebase

## 📦 Installation

### Requirements

- Python 3.8 or higher
- pip or poetry

### From Source

```bash
git clone https://github.com/Roderick47/FeynMap.git
cd FeynMap
pip install -e .
```

### As a Python Package

```bash
pip install feynmap
```

## 🎯 Quick Start

### Command Line Usage

```bash
# Analyze current directory (auto-detect framework)
feynmap .

# Analyze a specific supported framework
feynmap /path/to/project --framework django
feynmap /path/to/project --framework flask
feynmap /path/to/project --framework fastapi
feynmap /path/to/project --framework generic

# Lazy loading - analyze specific nodes only
feynmap . --target-nodes "UserView,PostModel"

# Disable lazy loading to analyze entire codebase
feynmap . --no-lazy-load

# Specify output directory
feynmap . --output-dir ./analysis_results

# Trace deeper interaction chains (default depth: 4 hops)
feynmap . --trace-depth 6

# Predict blast radius from the current git diff
git diff | feynmap . --impact-diff -

# Predict blast radius from a saved patch file
feynmap . --impact-diff ./my-change.patch --impact-depth 8
```

### Python API

```python
from feynmap import FeynExtractor, FeynNotator

# Initialize with framework
extractor = FeynExtractor("/path/to/project", framework="django")
graph_data = extractor.scan()

# Access analysis results
print(f"Found {len(graph_data['nodes'])} nodes")
print(f"Found {len(graph_data['edges'])} relationships")

# Generate physics-inspired notation
ledger = {}
for node in graph_data["nodes"]:
    if node["type"] == "VERTEX":
        trace = [("PROPAGATOR_HTTP", "URL"), ("VERTEX", node["id"])]
        ledger[node["id"]] = FeynNotator.generate_enhanced_string(trace)

# Print notation for each view
for node_id, notation in ledger.items():
    print(f"{node_id}: {notation}")
```

### Change Impact Predictor

The Change Impact Predictor answers: **“If I change this model, what views, serializers, and templates break?”** It parses a unified git diff, maps changed files and line ranges back to graph nodes, then walks reverse dependency edges. Because FeynMap edges typically point from consumers to dependencies (`View -> Model`, `Template -> variable`, `Serializer -> Model`), reverse traversal reveals the consumer surfaces that may need review after the change.

Running with `--impact-diff` produces `feyn_change_impact.json` alongside the normal ledgers:

```json
{
  "changed_nodes": [{"id": "User", "type": "PARTICLE"}],
  "impacted_nodes": [
    {"id": "UserSerializer", "type": "TRANSFORM"},
    {"id": "UserDetailView", "type": "VERTEX"},
    {"id": "user_detail", "type": "FRONTEND"}
  ],
  "risk_summary": {
    "changed_node_count": 1,
    "impacted_node_count": 3,
    "potential_breaking_surfaces": ["UserSerializer", "UserDetailView", "user_detail"]
  }
}
```

## 🔧 Supported Frameworks

### Django
- **Models**: Classes inheriting from `models.Model`
- **Views**: Classes ending with `View` or `APIView`
- **Serializers**: Classes ending with `Serializer`
- **Templates**: `.html` files with Django template syntax
- **ORM**: `Model.objects.all()`, `Model.objects.get()`, etc.

### Flask
- **Models**: Classes inheriting from `db.Model` or `SQLAlchemy`
- **Views**: Functions with `@app.route` or `@bp.route` decorators
- **Serializers**: Classes ending with `Schema` or inheriting from `ma.Schema`
- **Templates**: `.html`, `.jinja`, `.jinja2` files
- **ORM**: `Model.query.all()`, `db.session.add()`, etc.

### FastAPI
- **Models**: Classes inheriting from `BaseModel` or `SQLModel`
- **Views**: Functions with `@app.` or `@router.` decorators
- **Serializers**: Classes inheriting from `BaseModel`
- **Templates**: Typically separate frontend (no template parsing)
- **ORM**: `session.get()`, `Model.select()`, etc.

### Generic Python
- Basic pattern detection for Python projects without a supported web framework
- Configurable rules for custom Python codebases

### Not currently supported
- Ruby on Rails
- Other non-Python frameworks

Selecting `framework="rails"` now raises a clear error instead of silently falling back to generic analysis.

## 📊 Output & Examples

FeynMap generates three JSON files in your project directory:

### `feyn_ledger.json` (Simple Notation)

```json
{
    "UserView": "g[URL] -> V[UserView] -> ψ[build_user_profile] -> ψ[normalize_email] -> P[User] -> ⊗[UserSerializer]",
    "PostModel": "P[Post]",
    "CommentView": "g[URL] -> V[CommentView] -> ψ[load_comment_thread] -> P[Comment] -> P[User] -> ⊗[CommentSerializer]",
    "AuthMiddleware": "s[async] -> 𝕁[validate_token]"
}
```

### `feyn_ledger_enhanced.json` (Rich Metadata)

```json
{
    "UserView": {
        "notation": "g[URL]{ₘ0.1,ᴱ1.0,ᶜ0.9} -> V[UserView]{ₘ2.3,ᴱ2.1,ᶜ0.8} -> P[User]{ₘ1.5,ᴱ0.7,ᶜ0.9} -> ⊗[UserSerializer]{ₘ1.2,ᴱ0.5,ᶜ0.7}",
        "diagram": {
            "vertices": [
                {"id": "UserView", "type": "view", "complexity": 2.3}
            ],
            "propagators": [
                {"id": "g[URL]", "type": "http", "activity": 1.0}
            ],
            "particles": [
                {"id": "User", "type": "model", "complexity": 1.5}
            ],
            "interactions": [
                {"from": "URL", "to": "UserView", "type": "request"}
            ]
        },
        "metadata": {
            "interaction_type": "backend",
            "complexity": 2.3,
            "energy": 2.1,
            "coupling": 0.9,
            "file_path": "views/users.py",
            "line_number": 42
        }
    },
    "PostModel": {
        "notation": "P[Post]{ₘ1.8,ᴱ0.9,ᶜ0.8}",
        "metadata": {
            "interaction_type": "data",
            "complexity": 1.8,
            "file_path": "models.py",
            "line_number": 15
        }
    }
}
```

### `feyn_semantic_clusters.json` (Mental Model Categories)

```json
{
    "clusters": [
        {
            "id": "semantic_cluster_001",
            "summary": "Crud Interface around User (create, read, update)",
            "role": "crud_interface",
            "data_subjects": ["User"],
            "intents": ["create", "read", "update"],
            "members": ["UserCreateView", "UserListView", "UserUpdateView"],
            "confidence": 0.95
        },
        {
            "id": "semantic_cluster_002",
            "summary": "Data Transform around User (transform)",
            "role": "data_transform",
            "data_subjects": ["User"],
            "members": ["UserSerializer", "UserPublicSerializer"],
            "confidence": 0.95
        }
    ],
    "node_memberships": {
        "UserCreateView": ["semantic_cluster_001"],
        "UserSerializer": ["semantic_cluster_002"]
    }
}
```

Semantic clusters are also copied onto matching entries in `feyn_ledger_enhanced.json`, so an AI agent can read exact interaction traces and higher-level mental categories from the same enhanced ledger.
