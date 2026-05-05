# FeynMap Portability Changes

## 🎯 Overview

FeynMap has been successfully transformed from a Django-specific tool into a portable, framework-agnostic code analysis system while preserving all physics concepts and notation.

## 📋 Changes Made

### 1. Configuration System (`config.py`)
- **New file**: Created comprehensive configuration system
- **Framework configs**: Django, Flask, FastAPI, Rails, Generic
- **Pattern-based detection**: Configurable rules for each framework
- **Extensible design**: Easy to add new frameworks

### 2. Parser Updates (`feyn_parser.py`)
- **Framework parameter**: Added `framework='auto'` to constructor
- **Pattern matching**: Replaced hardcoded Django patterns with configurable rules
- **Multi-framework support**: Detects models, views, serializers based on framework
- **Template parsing**: Framework-specific template syntax support
- **ORM patterns**: Configurable ORM usage detection

### 3. Main Script Updates (`main.py`)
- **Framework argument**: Added `--framework` CLI option
- **Enhanced CLI**: Better argument parsing with argparse
- **Framework reporting**: Shows detected framework in output
- **Import fixes**: Works both as module and standalone

### 4. Package Structure
- **setup.py**: Complete package installation setup
- **README.md**: Comprehensive documentation
- **Relative imports**: Works both ways (module/standalone)
- **Example usage**: Demonstrates portability

## 🔧 Framework Support

### Django (Default - Backward Compatible)
```python
# Models: class User(models.Model)
# Views: class UserView(View), class UserAPIView(APIView)
# Serializers: class UserSerializer(serializers.ModelSerializer)
# Templates: {{ user.name }}, {% if user %}
# ORM: User.objects.all(), User.objects.get()
```

### Flask
```python
# Models: class User(db.Model)
# Views: @app.route('/users'), @bp.route('/users')
# Serializers: class UserSchema(ma.Schema)
# Templates: {{ user.name }}, {% if user %}
# ORM: User.query.all(), db.session.add()
```

### FastAPI
```python
# Models: class User(BaseModel), class User(SQLModel)
# Views: @app.get('/users'), @router.get('/users')
# Serializers: class User(BaseModel)
# Templates: Separate frontend (no template parsing)
# ORM: session.get(User), User.select()
```

### Ruby on Rails
```ruby
# Models: class User < ApplicationRecord
# Views: class UsersController < ApplicationController
# Serializers: class UserSerializer
# Templates: <%= user.name %>, <% if user %>
# ORM: User.where(), User.find()
```

## 📊 Usage Examples

### Command Line
```bash
# Auto-detect (defaults to Django for backward compatibility)
feynmap /path/to/project

# Specific framework
feynmap /path/to/project --framework flask
feynmap /path/to/project --framework fastapi
feynmap /path/to/project --framework rails

# With options
feynmap . --target-nodes "UserView,PostModel" --no-lazy-load
```

### Python API
```python
from feyn_parser import FeynExtractor

# Framework-specific analysis
django_extractor = FeynExtractor("/django/project", framework="django")
flask_extractor = FeynExtractor("/flask/project", framework="flask")

# Auto-detection
auto_extractor = FeynExtractor("/unknown/project", framework="auto")
```

## 🎨 Preserved Physics Concepts

All physics-inspired notation and concepts have been preserved:

- **Particles**: Models/Entities (P)
- **Vertices**: Views/Controllers (V)
- **Transforms**: Serializers/Schemas (⊗)
- **Propagators**: HTTP/AJAX calls (g, em)
- **Ghost States**: Dead code detection
- **Metadata**: Mass, Energy, Charge, Spin, Coupling

## 🔄 Backward Compatibility

The changes are **100% backward compatible**:

```bash
# Old usage still works
python main.py /path/to/django/project

# New usage provides more options
python main.py /path/to/django/project --framework django
```

## 🚀 Benefits

1. **Multi-framework**: Works with Django, Flask, FastAPI, Rails, and custom frameworks
2. **Extensible**: Easy to add new framework configurations
3. **Configurable**: Pattern-based detection system
4. **Portable**: Can be installed as a Python package
5. **Maintainable**: Clean separation of framework-specific logic
6. **Future-proof**: Ready for new frameworks and patterns

## 📁 File Structure

```
feynmap/
├── __init__.py
├── config.py              # NEW: Framework configurations
├── feyn_parser.py         # UPDATED: Framework-agnostic parser
├── feyn_notation.py       # UNCHANGED: Physics notation
├── main.py                # UPDATED: Framework support
├── setup.py               # NEW: Package installation
├── README.md              # NEW: Comprehensive docs
├── example_usage.py       # NEW: Usage examples
└── PORTABILITY_CHANGES.md # THIS FILE
```

## ✅ Testing Results

All tests pass:
- ✅ Django framework detection
- ✅ Flask framework detection  
- ✅ FastAPI framework detection
- ✅ Generic framework support
- ✅ Command line interface
- ✅ Python API
- ✅ Backward compatibility
- ✅ Package installation

## 🎯 Mission Accomplished

FeynMap is now a **portable, framework-agnostic code analysis tool** that maintains its unique physics-inspired approach while being usable across multiple web frameworks and project types.
