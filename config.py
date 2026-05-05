"""
Configuration system for FeynMap - makes it portable across different frameworks
"""

class FrameworkConfig:
    """Base configuration for web framework detection patterns"""
    
    def __init__(self):
        self.model_patterns = []
        self.view_patterns = []
        self.serializer_patterns = []
        self.template_extensions = []
        self.code_extensions = []
        self.template_patterns = {}
        self.orm_patterns = []
        self.exclude_dirs = ["venv", "__pycache__", ".git", "node_modules"]
        
    def get_model_detection_rules(self):
        """Return AST detection rules for models"""
        return self.model_patterns
    
    def get_view_detection_rules(self):
        """Return AST detection rules for views"""
        return self.view_patterns
    
    def get_serializer_detection_rules(self):
        """Return AST detection rules for serializers"""
        return self.serializer_patterns
    
    def get_template_patterns(self):
        """Return regex patterns for template parsing"""
        return self.template_patterns
    
    def get_orm_patterns(self):
        """Return regex patterns for ORM usage"""
        return self.orm_patterns


class DjangoConfig(FrameworkConfig):
    """Django-specific configuration"""
    
    def __init__(self):
        super().__init__()
        self.model_patterns = [
            {"type": "class_inheritance", "pattern": "models.Model"}
        ]
        self.view_patterns = [
            {"type": "class_name_suffix", "pattern": "View"},
            {"type": "class_name_suffix", "pattern": "APIView"},
            {"type": "function_name_contains", "pattern": "view"},
            {"type": "function_name_contains", "pattern": ["dashboard", "home", "detail", "create", "edit", "list"]}
        ]
        self.serializer_patterns = [
            {"type": "class_name_suffix", "pattern": "Serializer"}
        ]
        self.template_extensions = [".html"]
        self.code_extensions = [".py"]
        self.template_patterns = {
            "variables": r'{{\s*([\w\.]+)\s*}}',
            "tags": r'{%\s*[^%]+\s*%}',
            "js_functions": r'function\s+(\w+)\s*\(',
            "arrow_functions": r'(\w+)\s*=\s*(?:async\s+)?(?:function\s*\([^)]*\)|\([^)]*\))\s*=>',
            "fetch_calls": r'fetch\s*\(\s*[\'"]([^\'"]+)[\'"]',
            "async_functions": r'async\s+function\s+(\w+)',
            "event_listeners": r'addEventListener\s*\(\s*[\'"]([^\'"]+)[\'"]'
        }
        self.orm_patterns = [
            r'(\w+)\.objects\.(all|get|filter|create|update|delete)',
            r'(\w+)\.objects\.first\(\)',
            r'(\w+)\.objects\.last\(\)',
            r'(\w+)\.objects\.count\(\)'
        ]


class FlaskConfig(FrameworkConfig):
    """Flask-specific configuration"""
    
    def __init__(self):
        super().__init__()
        self.model_patterns = [
            {"type": "class_inheritance", "pattern": "db.Model"},
            {"type": "class_inheritance", "pattern": "SQLAlchemy"}
        ]
        self.view_patterns = [
            {"type": "function_decorator", "pattern": "@app.route"},
            {"type": "function_decorator", "pattern": "@bp.route"},
            {"type": "function_name_contains", "pattern": ["dashboard", "home", "detail", "create", "edit", "list"]}
        ]
        self.serializer_patterns = [
            {"type": "class_name_suffix", "pattern": "Schema"},
            {"type": "class_inheritance", "pattern": "ma.Schema"}
        ]
        self.template_extensions = [".html", ".jinja", ".jinja2"]
        self.code_extensions = [".py"]
        self.template_patterns = {
            "variables": r'{{\s*([\w\.]+)\s*}}',
            "tags": r'{%\s*[^%]+\s*%}',
            "js_functions": r'function\s+(\w+)\s*\(',
            "arrow_functions": r'(\w+)\s*=\s*(?:async\s+)?(?:function\s*\([^)]*\)|\([^)]*\))\s*=>',
            "fetch_calls": r'fetch\s*\(\s*[\'"]([^\'"]+)[\'"]',
            "async_functions": r'async\s+function\s+(\w+)',
            "event_listeners": r'addEventListener\s*\(\s*[\'"]([^\'"]+)[\'"]'
        }
        self.orm_patterns = [
            r'(\w+)\.query\.(all|first|get|filter|count)',
            r'(\w+)\.query\.filter_by\(',
            r'db\.session\.(add|commit|delete|query)'
        ]


class FastAPIConfig(FrameworkConfig):
    """FastAPI-specific configuration"""
    
    def __init__(self):
        super().__init__()
        self.model_patterns = [
            {"type": "class_inheritance", "pattern": "BaseModel"},
            {"type": "class_inheritance", "pattern": "SQLModel"},
            {"type": "class_decoration", "pattern": "table"}
        ]
        self.view_patterns = [
            {"type": "function_decorator", "pattern": "@app."},
            {"type": "function_decorator", "pattern": "@router."},
            {"type": "class_decoration", "pattern": "APIRouter"}
        ]
        self.serializer_patterns = [
            {"type": "class_inheritance", "pattern": "BaseModel"},
            {"type": "class_name_suffix", "pattern": "Schema"}
        ]
        self.template_extensions = []  # FastAPI typically uses separate frontend
        self.code_extensions = [".py"]
        self.template_patterns = {}
        self.orm_patterns = [
            r'session\.get\((\w+)',
            r'session\.query\((\w+)',
            r'(\w+)\.select\(\)',
            r'session\.execute\(.*select\((\w+)\)'
        ]


class RailsConfig(FrameworkConfig):
    """Ruby on Rails-specific configuration"""
    
    def __init__(self):
        super().__init__()
        self.model_patterns = [
            {"type": "class_inheritance", "pattern": "ApplicationRecord"}
        ]
        self.view_patterns = [
            {"type": "file_path_pattern", "pattern": "app/controllers/"},
            {"type": "class_name_suffix", "pattern": "Controller"}
        ]
        self.serializer_patterns = [
            {"type": "class_name_suffix", "pattern": "Serializer"}
        ]
        self.template_extensions = [".html.erb", ".erb", ".haml"]
        self.code_extensions = [".rb"]
        self.template_patterns = {
            "variables": r'<%=\s*([\w\.]+)\s*%>',
            "tags": r'<%\s*[^%]+\s*%>',
            "js_functions": r'function\s+(\w+)\s*\(',
            "arrow_functions": r'(\w+)\s*=\s*(?:async\s+)?(?:function\s*\([^)]*\)|\([^)]*\))\s*=>',
            "fetch_calls": r'fetch\s*\(\s*[\'"]([^\'"]+)[\'"]',
            "async_functions": r'async\s+function\s+(\w+)',
            "event_listeners": r'addEventListener\s*\(\s*[\'"]([^\'"]+)[\'"]'
        }
        self.orm_patterns = [
            r'(\w+)\.where\(',
            r'(\w+)\.find\(',
            r'(\w+)\.all',
            r'(\w+)\.first',
            r'(\w+)\.create\('
        ]


# Framework registry
FRAMEWORKS = {
    'django': DjangoConfig,
    'flask': FlaskConfig,
    'fastapi': FastAPIConfig,
    'rails': RailsConfig,
    'generic': FrameworkConfig  # Default fallback
}


def get_framework_config(framework_name='auto'):
    """
    Get framework configuration by name or auto-detect
    """
    if framework_name == 'auto':
        # Auto-detection logic could be implemented here
        # For now, default to Django for backward compatibility
        framework_name = 'django'
    
    config_class = FRAMEWORKS.get(framework_name.lower(), FrameworkConfig)
    return config_class()


# Default configuration for backward compatibility
DEFAULT_CONFIG = DjangoConfig()
