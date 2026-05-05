# 🚀 FeynMap Quick Start Guide

## For New Projects

### 1. Install FeynMap
```bash
# Option A: Install from source (current)
git clone https://github.com/feynmap/feynmap.git
cd feynmap
pip install -e .

# Option B: Copy to project
cp -r feynmap /path/to/your/project/
```

### 2. Analyze Your Project
```bash
# Navigate to your project
cd /path/to/your/project

# Auto-detect framework and analyze
feynmap .

# Specify framework
feynmap . --framework django  # or flask, fastapi, rails, generic
```

### 3. View Results
```bash
# Check generated files
cat feyn_ledger.json          # Basic notation
cat feyn_ledger_enhanced.json  # Enhanced notation with metadata
```

## For IDE Agents

### 1. Basic Integration
```python
from feyn_parser import FeynExtractor

# Initialize agent
extractor = FeynExtractor('/path/to/project', framework='auto')
graph_data = extractor.scan()

print(f"Found {len(graph_data['nodes'])} components")
```

### 2. Get Context for Current File
```python
from ide_agent_example import FeynMapIDEAgent

# Create agent
agent = FeynMapIDEAgent('/path/to/project')
agent.initialize()

# Get context when user opens a file
context = agent.get_context_for_file('models.py')
print(f"Components in file: {context['components']}")
```

### 3. Smart Suggestions
```python
# Get suggestions for current work
suggestions = agent.suggest_next_action(
    current_line=25,
    current_text="class UserView(View):"
)

for suggestion in suggestions:
    print(f"💡 {suggestion['message']}")
```

## Example Workflow

### Step 1: Initial Analysis
```bash
$ feynmap . --framework django
==================================================
 FEYNMAP V2 - ENHANCED PHYSICS NOTATION (DJANGO)
==================================================
[✓] NO GHOST STATES: Every node is active in the Standard Model.
[SUCCESS] Enhanced Ledger and Graph updated.
[INFO] Enhanced notation saved to 'feyn_ledger_enhanced.json'
[INFO] Framework: django
[INFO] Analyzed 15 nodes and 23 edges
```

### Step 2: Check Results
```json
// feyn_ledger_enhanced.json
{
  "UserView": {
    "notation": "g[URL]{ₘ0.1,ᴱ1.0,ᶜ0.9} -> V[UserView]{ₘ1.2,ᴱ0.8,ᶜ0.7}",
    "metadata": {
      "interaction_type": "backend",
      "complexity": 1.3,
      "energy": 1.8,
      "coupling": 0.9
    }
  }
}
```

### Step 3: IDE Agent Integration
```python
# Your IDE agent can now provide:
# - Context-aware suggestions
# - Architecture insights  
# - Code generation
# - Ghost state detection
```

## Key Features

### 🔍 Auto-Detection
- Automatically detects Django, Flask, FastAPI, Rails projects
- Falls back to generic for custom frameworks

### 🎯 Smart Analysis
- Physics-inspired notation for code relationships
- Complexity metrics and suggestions
- Ghost state (dead code) detection

### 🤖 IDE Integration
- Real-time context awareness
- Intelligent code suggestions
- Automated refactoring recommendations

### 📊 Visualization Ready
- Structured data for diagram generation
- Component relationship mapping
- Architecture overview

## Next Steps

1. **Install FeynMap** in your project
2. **Run initial analysis** to understand your codebase
3. **Integrate with IDE** using the Python API
4. **Customize patterns** for your specific framework
5. **Extend functionality** with custom analysis rules

## Need Help?

- 📖 Read `INTEGRATION_GUIDE.md` for detailed integration
- 🔧 Check `config.py` for framework patterns
- 💡 See `ide_agent_example.py` for implementation ideas
- 📧 Open an issue for questions or feature requests

---

**Happy coding with FeynMap!** ⚛️
