# FeynMap V2 - Portable Code Analysis with Physics-Inspired Notation

FeynMap is a powerful code analysis tool that uses physics-inspired notation to help AI editors understand codebase architecture. Originally designed for Django projects, it's now portable across multiple web frameworks.

## 🚀 Features

- **Multi-Framework Support**: Django, Flask, FastAPI, Ruby on Rails, and generic projects
- **Physics-Inspired Notation**: Uses particle physics concepts to represent code relationships
- **Smart Lazy Loading**: Analyze only the components you care about
- **Ghost State Detection**: Identify unused/dead code
- **Enhanced Visualization**: Generate structured data for Feynman diagrams
- **Zero Dependencies**: Uses only Python standard library

## 📦 Installation

### From Source
```bash
git clone https://github.com/feynmap/feynmap.git
cd feynmap
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

# Lazy loading - analyze specific nodes only
feynmap . --target-nodes "UserView,PostModel"

# Disable lazy loading
feynmap . --no-lazy-load
```

### Python API

```python
from feynmap import FeynExtractor, FeynNotator

# Initialize with framework
extractor = FeynExtractor("/path/to/project", framework="django")
graph_data = extractor.scan()

# Generate physics-inspired notation
ledger = {}
for node in graph_data["nodes"]:
    if node["type"] == "VERTEX":
        trace = [("PROPAGATOR_HTTP", "URL"), ("VERTEX", node["id"])]
        ledger[node["id"]] = FeynNotator.generate_enhanced_string(trace)
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

## 📊 Output Files

### `feyn_ledger.json`
```json
{
    "UserView": "g[URL] -> V[UserView] -> P[User] -> ⊗[UserSerializer]",
    "PostModel": "P[Post]"
}
```

### `feyn_ledger_enhanced.json`
```json
{
    "UserView": {
        "notation": "g[URL]{ₘ0.1,ᴱ1.0,ᶜ0.9} -> V[UserView]{...} -> P[User]{...}",
        "diagram": {
            "vertices": [...],
            "propagators": [...],
            "particles": [...],
            "interactions": [...]
        },
        "metadata": {
            "interaction_type": "backend",
            "complexity": 2.5,
            "energy": 3.2,
            "coupling": 0.9
        }
    }
}
```

## 🎨 Physics Notation Guide

### Force Carriers (Propagators)
- `g` - Gravity-like (HTTP requests)
- `em` - Electromagnetic-like (AJAX calls)
- `w` - Weak-like (background signals)
- `s` - Strong-like (async operations)

### Particles
- `P` - Standard particle (Model/Entity)
- `V` - Vertex (View/Controller)
- `⊗` - Transform (Serializer/Schema)
- `𝔽` - Template state
- `𝕁` - Function state

### Metadata
- `ₘ` - Mass/Complexity
- `ᴱ` - Energy/Activity
- `ᶜ` - Charge/Importance
- `ˢ` - Spin/Rotation

## ⚙️ Configuration

### Custom Framework Config

```python
from feynmap.config import FrameworkConfig, FRAMEWORKS

class MyFrameworkConfig(FrameworkConfig):
    def __init__(self):
        super().__init__()
        self.model_patterns = [
            {"type": "class_inheritance", "pattern": "MyModel"}
        ]
        self.view_patterns = [
            {"type": "class_name_suffix", "pattern": "Handler"}
        ]
        # ... more patterns

# Register your framework
FRAMEWORKS['myframework'] = MyFrameworkConfig
```

### Pattern Types

- `class_inheritance`: Detect inheritance from specific classes
- `class_name_suffix`: Match class name suffixes
- `class_decoration`: Detect class decorators
- `function_decorator`: Detect function decorators
- `function_name_contains`: Match substrings in function names

## 🧠 Advanced Usage

### Lazy Loading
```bash
# Analyze only specific components and their dependencies
feynmap . --target-nodes "UserView,PostModel,CommentSerializer"
```

### Ghost State Detection
FeynMap automatically identifies unused code (ghost states) in your codebase:
```
[!] GHOST STATES DETECTED (3):
  - OldModel
  - UnusedView
  - DeprecatedSerializer
```

### Custom Analysis
```python
from feynmap.feyn_parser import FeynExtractor
from feynmap.feyn_notation import FeynNotator

# Extract graph data
extractor = FeynExtractor("/path/to/project", framework="django")
graph_data = extractor.scan()

# Generate custom analysis
for node in graph_data["nodes"]:
    if node["type"] == "VERTEX":
        complexity = node["metadata"]["mass"]
        print(f"View {node['id']} has complexity {complexity}")
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details.

## 🔗 Related Projects

- [FeynDiagram](https://github.com/feynmap/feyndiagram) - Visualization tool for FeynMap output
- [FeynLab](https://github.com/feynmap/feynlab) - Experimental features and research

## 📚 Citation

If you use FeynMap in your research, please cite:

```
FeynMap: Physics-Inspired Code Analysis for AI-Assisted Development
Authors: FeynMap Team
Conference: AI-Assisted Software Engineering 2024
```

---

**FeynMap** - Making code architecture as elegant as particle physics! ⚛️
