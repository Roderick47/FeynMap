# FeynMap V2 - Portable Code Analysis with Physics-Inspired Notation

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

FeynMap is a powerful code analysis tool that uses physics-inspired notation to help developers and AI editors understand codebase architecture. Originally designed for Django projects, it's now portable across multiple frameworks including Flask, FastAPI, and Ruby on Rails. Transform complex code relationships into elegant physics diagrams.

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

- **Multi-Framework Support**: Django, Flask, FastAPI, Ruby on Rails, and generic projects
- **Physics-Inspired Notation**: Uses particle physics concepts to represent code relationships intuitively
- **Smart Lazy Loading**: Analyze only the components you care about for faster results
- **Interaction Chain Depth Tracing**: Recursively follow view → service → utility → model call paths instead of stopping at one-hop relationships
- **Semantic Similarity Clustering**: Group functionally similar nodes even when they are not directly connected, such as CRUD views for the same model or serializers touching the same data
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

# Analyze specific framework
feynmap /path/to/project --framework django
feynmap /path/to/project --framework flask
feynmap /path/to/project --framework fastapi
feynmap /path/to/project --framework rails

# Lazy loading - analyze specific nodes only
feynmap . --target-nodes "UserView,PostModel"

# Disable lazy loading to analyze entire codebase
feynmap . --no-lazy-load

# Specify output directory
feynmap . --output-dir ./analysis_results

# Trace deeper interaction chains (default depth: 4 hops)
feynmap . --trace-depth 6
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

## 🔧 Supported Frameworks

### Django (Default)
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

### Ruby on Rails
- **Models**: Classes inheriting from `ApplicationRecord`
- **Views**: Controllers in `app/controllers/` directory
- **Serializers**: Classes ending with `Serializer`
- **Templates**: `.html.erb`, `.erb`, `.haml` files
- **ORM**: `Model.where()`, `Model.find()`, etc.

### Generic
- Basic pattern detection for any Python project
- Configurable rules for custom frameworks

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

### Ghost States Detection Output

```
[!] GHOST STATES DETECTED (3):
  - OldUserModel (models.py:156) - No references found
  - LegacyAuthView (views.py:289) - No references found
  - DeprecatedSerializer (serializers.py:412) - No references found

Run with --no-lazy-load to analyze the full codebase.
```

## 🎨 Physics Notation Guide

FeynMap maps software architecture to particle physics concepts for intuitive visualization.

### Force Carriers (Propagators)

These represent different types of communication or flow:

- `g` - Gravity-like (HTTP requests, API calls)
- `em` - Electromagnetic-like (AJAX calls, WebSocket connections)
- `w` - Weak-like (background signals, event triggers)
- `s` - Strong-like (async operations, scheduled tasks)

### Particles

These represent code components:

- `P` - Standard particle (Model/Entity, database table)
- `V` - Vertex (View/Controller, request handler)
- `⊗` - Transform (Serializer/Schema, data transformer)
- `𝔽` - Template state (HTML template, template rendering)
- `𝕁` - Function state (Utility function, service method)

### Metadata Annotations

These quantify properties of components:

- `ₘ` - Mass/Complexity (0.0-10.0, lines of code normalized)
- `ᴱ` - Energy/Activity (0.0-10.0, call frequency/importance)
- `ᶜ` - Charge/Importance (0.0-1.0, criticality to system)
- `ˢ` - Spin/Rotation (direction of data flow)

### Example Notation Breakdown

```
g[URL]{ₘ0.1,ᴱ1.0,ᶜ0.9} -> V[UserView]{ₘ2.3,ᴱ2.1,ᶜ0.8} -> P[User]{ₘ1.5,ᴱ0.7,ᶜ0.9} -> ⊗[UserSerializer]{ₘ1.2,ᴱ0.5,ᶜ0.7}
│                          │                              │                        │
Gravity carrier (HTTP)     View component                 Model component        Serializer (transformer)
minimal complexity         moderate complexity            simple model           transforms data
high importance            high activity                  critical               low activity
```

## ⚙️ Configuration

### Custom Framework Config

Create a configuration for your custom framework:

```python
from feynmap.config import FrameworkConfig, FRAMEWORKS

class MyFrameworkConfig(FrameworkConfig):
    def __init__(self):
        super().__init__()
        self.name = "myframework"
        self.model_patterns = [
            {"type": "class_inheritance", "pattern": "MyModel"}
        ]
        self.view_patterns = [
            {"type": "class_name_suffix", "pattern": "Handler"},
            {"type": "function_decorator", "pattern": "@route"}
        ]
        self.serializer_patterns = [
            {"type": "class_name_suffix", "pattern": "Transformer"}
        ]

# Register your framework
FRAMEWORKS['myframework'] = MyFrameworkConfig()

# Now use it
from feynmap import FeynExtractor
extractor = FeynExtractor("/path/to/project", framework="myframework")
```

### Pattern Types

- `class_inheritance`: Detect classes inheriting from specific base classes
- `class_name_suffix`: Match class names ending with specific suffix
- `class_decoration`: Detect classes with specific decorators
- `function_decorator`: Detect functions with specific decorators
- `function_name_contains`: Match functions with substring in name

### Configuration File

Create a `.feynmap.json` in your project root:

```json
{
  "framework": "django",
  "target_nodes": ["UserView", "PostModel"],
  "exclude_patterns": ["tests/", "migrations/"],
  "lazy_load": true,
  "output_dir": "./feyn_analysis"
}
```

## 🧠 Advanced Usage

### Lazy Loading - Targeted Analysis

Analyze only specific components and their dependencies:

```bash
feynmap . --target-nodes "UserView,PostModel,CommentSerializer"
```

This is much faster for large codebases:

```python
from feynmap import FeynExtractor

extractor = FeynExtractor("/path/to/project", framework="django")
# Only analyze specific nodes
graph_data = extractor.scan(target_nodes=["UserView", "PostModel"])
print(f"Analyzed {len(graph_data['nodes'])} nodes")
```

### Semantic Similarity Clustering

Semantic clustering runs as part of the normal FeynMap pipeline and writes `feyn_semantic_clusters.json` next to the standard ledgers:

```bash
feynmap . --framework django --trace-depth 6
```

Use this output when you want to understand a codebase by purpose instead of one node at a time. FeynMap infers cluster membership from explicit graph relationships, data subjects touched by `PARTICLE_ENTANGLEMENT` edges, common CRUD intent in class/function names, serializers/schemas, frontend surfaces, and shared semantic tokens. This means disconnected nodes can still be grouped when they operate on the same concept.

### Ghost State Detection

Automatically identify unused code (ghost states):

```bash
feynmap . --detect-ghosts
```

In Python:

```python
from feynmap import GhostDetector

detector = GhostDetector("/path/to/project")
ghost_states = detector.find_unused_code()

for ghost in ghost_states:
    print(f"Unused: {ghost['name']} ({ghost['file']}:{ghost['line']})")
```

### Full Codebase Analysis

Disable lazy loading for complete analysis:

```bash
feynmap . --no-lazy-load --detect-ghosts
```

### Custom Analysis Pipeline

```python
from feynmap.feyn_parser import FeynExtractor
from feynmap.feyn_notation import FeynNotator

# Extract graph data
extractor = FeynExtractor("/path/to/project", framework="django")
graph_data = extractor.scan()

# Generate custom analysis
high_complexity_views = []
for node in graph_data["nodes"]:
    if node["type"] == "VERTEX":
        complexity = node["metadata"].get("mass", 0)
        if complexity > 3.0:
            high_complexity_views.append({
                "name": node["id"],
                "complexity": complexity,
                "file": node["metadata"].get("file_path")
            })

# Sort by complexity
high_complexity_views.sort(key=lambda x: x["complexity"], reverse=True)

# Print report
print("High Complexity Views:")
for view in high_complexity_views[:10]:
    print(f"  {view['name']}: {view['complexity']:.1f} ({view['file']})")
```

### Recursive Interaction Tracing

FeynMap now traces interaction chains recursively from backend vertices and frontend states. In addition to direct view relationships such as `View → Serializer → Model`, it records project-local function and class calls as mediator nodes (`ψ`) and follows them until the configured depth is reached. This exposes paths such as:

```text
g[URL] -> V[UserView] -> ψ[build_user_profile] -> ψ[normalize_email] -> P[User]
```

Use `--trace-depth` to increase or reduce chain length. Cycles are ignored per trace path so recursive helpers and repeated service calls do not loop forever.

## 📋 Requirements

### Python Version
- Python 3.8+

### Dependencies
- **Core**: None (uses Python standard library only)
- **Optional**: 
  - For better AST parsing: `ast` (built-in)
  - For Rails support: `ruby_parser` (recommended)

### System Requirements
- 512MB RAM minimum
- Disk space: ~50MB for installation

### Performance Notes

| Codebase Size | Time (w/ lazy load) | Time (full scan) |
|---------------|-------------------|-----------------|
| <10K LOC      | <1 second         | 1-2 seconds    |
| 10K-50K LOC   | 1-3 seconds       | 5-10 seconds   |
| 50K-200K LOC  | 3-10 seconds      | 15-30 seconds  |
| 200K+ LOC     | 10-30 seconds     | 60+ seconds    |

## 🔧 Troubleshooting

### Issue: Framework Not Detected

**Problem**: FeynMap can't auto-detect your framework.

**Solutions**:
```bash
# Explicitly specify framework
feynmap . --framework django

# List supported frameworks
feynmap --list-frameworks
```

### Issue: No Output Generated

**Problem**: `feyn_ledger.json` not created.

**Solutions**:
```bash
# Check verbose output
feynmap . --verbose

# Verify project structure matches framework
# For Django: ensure manage.py and app directories exist
# For Flask: ensure app.py or wsgi.py exists

# Try generic framework
feynmap . --framework generic
```

### Issue: Ghost Detection Too Aggressive

**Problem**: Valid code marked as ghost state.

**Solutions**:
```bash
# Disable ghost detection
feynmap . --no-detect-ghosts

# Check false positives
feynmap . --detect-ghosts --verbose

# Increase sensitivity threshold
feynmap . --ghost-threshold 0.8
```

### Issue: Out of Memory on Large Projects

**Problem**: `MemoryError` on very large codebases.

**Solutions**:
```bash
# Use lazy loading with target nodes
feynmap . --target-nodes "AppView,CoreModel" --lazy-load

# Exclude unnecessary directories
feynmap . --exclude "tests/,migrations/,node_modules/"

# Process incrementally
feynmap . --framework django --lazy-load
```

### Issue: Import Errors

**Problem**: `ModuleNotFoundError` when running analysis.

**Solutions**:
```bash
# Ensure project dependencies are installed
pip install -r requirements.txt

# Run from project root
cd /path/to/project
feynmap .

# Verify Python path
feynmap . --python-path "/path/to/project"
```

### Getting Help

- **Documentation**: https://github.com/Roderick47/FeynMap/wiki
- **Issues**: https://github.com/Roderick47/FeynMap/issues
- **Discussions**: https://github.com/Roderick47/FeynMap/discussions

## 🤝 Contributing

We welcome contributions! Here's how to get started:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Add tests for new functionality
4. Ensure all tests pass (`pytest`)
5. Commit your changes (`git commit -m 'Add AmazingFeature'`)
6. Push to the branch (`git push origin feature/AmazingFeature`)
7. Open a Pull Request

### Development Setup

```bash
git clone https://github.com/Roderick47/FeynMap.git
cd FeynMap
pip install -e ".[dev]"
pytest
```

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🔗 Related Projects

- [FeynDiagram](https://github.com/Roderick47/FeynDiagram) - Visualization tool for FeynMap output
- [FeynLab](https://github.com/Roderick47/FeynLab) - Experimental features and research

## 📚 Citation

If you use FeynMap in your research or projects, please cite:

```bibtex
@software{feynmap2024,
  title={FeynMap: Physics-Inspired Code Analysis for AI-Assisted Development},
  author={Roderick47},
  year={2024},
  url={https://github.com/Roderick47/FeynMap}
}
```

Or in plain text:

```
FeynMap: Physics-Inspired Code Analysis for AI-Assisted Development
By: Roderick47 (2024)
https://github.com/Roderick47/FeynMap
```

## 📈 Roadmap

- [ ] VSCode Extension for real-time analysis
- [ ] Interactive web dashboard for visualization
- [ ] Integration with GitHub Actions for CI/CD
- [ ] Support for Go, Rust, and Java
- [ ] Performance profiling output format
- [ ] Dependency graph export (GraphML, DOT)

---

**FeynMap** - Making code architecture as elegant as particle physics! ⚛️

**Questions?** Open an [issue](https://github.com/Roderick47/FeynMap/issues) or start a [discussion](https://github.com/Roderick47/FeynMap/discussions).
