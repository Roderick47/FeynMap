from typing import Any, Dict, List, Optional, Tuple


class FeynNotator:
    """Physics-inspired notation system for representing execution traces as Feynman diagrams."""
    
    # Physics-inspired symbols with force carriers and quantum states
    SYMBOLS: Dict[str, str] = {
        # Force carriers (propagators)
        "PROPAGATOR_HTTP": "g",      # Gravity-like (always present)
        "PROPAGATOR_AJAX": "em",     # Electromagnetic-like (fast, visible)
        "PROPAGATOR_SIGNAL": "w",    # Weak-like (background, slow)
        "PROPAGATOR_ASYNC": "s",      # Strong-like (powerful, binding)
        
        # Interaction vertices with coupling constants
        "VERTEX": "V",               # Standard vertex
        "VERTEX_COUPLING": "Vᶜ",     # High coupling
        "VERTEX_WEAK": "Vᵂ",         # Weak coupling
        
        # Quantum states (particles) with properties
        "PARTICLE": "P",             # Standard particle
        "PARTICLE_ANTIPARTICLE": "P̄", # Anti-particle
        "PARTICLE_VIRTUAL": "P*",    # Virtual particle
        "PARTICLE_BOUND": "P₍",     # Bound state
        
        # Field transformations and operators
        "TRANSFORM": "⊗",            # Standard transform
        "TRANSFORM_UNITARY": "U",     # Unitary operator
        "TRANSFORM_HERMITIAN": "H",   # Hermitian operator
        
        # Force mediators
        "VIRTUAL": "~",              # Virtual particle
        "MEDIATOR": "ψ",             # Force carrier
        
        # Frontend quantum states
        "FRONTEND": "𝔽",           # Template state
        "JAVASCRIPT": "𝕁",          # Function state
        "DEPENDENCY": "𝔻",          # External field
        "AJAX": "⚡",               # Force carrier
        "EVENT": "🎯"              # Interaction point
    }
    
    # Metadata symbols for physics properties
    METADATA_SYMBOLS: Dict[str, str] = {
        "mass": "ₘ",           # Mass/complexity
        "charge": "ᶜ",         # Charge/importance  
        "spin": "ˢ",           # Spin/rotation
        "energy": "ᴱ",         # Energy/activity
        "coupling": "ᵏ",        # Coupling strength (distinct from charge)
        "lifetime": "ᵗ",       # Lifetime/stability
    }
    
    # Metadata keys that use superscript formatting
    _SUPERSCRIPT_KEYS: set = {"energy", "coupling"}
    
    @classmethod
    def generate_enhanced_string(
        cls, 
        trace: List[Tuple[str, str]], 
        metadata: Optional[Dict[int, Dict[str, Any]]] = None
    ) -> str:
        """
        Generate physics-inspired notation with embedded metadata.
        
        Args:
            trace: List of (role, name) tuples representing the execution path.
            metadata: Optional dictionary mapping trace indices to metadata dictionaries.
        
        Returns:
            A formatted string representing the trace with physics notation and metadata.
            
        Example:
            >>> trace = [("VERTEX", "request"), ("PARTICLE", "response")]
            >>> FeynNotator.generate_enhanced_string(trace)
            'V[request] -> P[response]'
        """
        if not trace:
            return ""
        
        parts = []
        for i, (role, name) in enumerate(trace):
            symbol = cls.SYMBOLS.get(role, "?")
            meta_data = metadata.get(i, {}) if metadata else {}
            meta_str = cls._format_metadata(meta_data)
            parts.append(f"{symbol}[{name}]{meta_str}")
        
        return " -> ".join(parts)
    
    @classmethod
    def _format_metadata(cls, metadata: Dict[str, Any]) -> str:
        """
        Format metadata as superscript/subscript notation.
        
        Args:
            metadata: Dictionary of metadata key-value pairs.
        
        Returns:
            Formatted string with superscripts/subscripts, or empty string if no metadata.
            
        Example:
            >>> metadata = {"mass": 10, "energy": 5}
            >>> FeynNotator._format_metadata(metadata)
            '{ₘ10,ᴱ^5}'
        """
        if not metadata:
            return ""
        
        parts = []
        for key, value in metadata.items():
            if value is None:
                continue
            
            symbol = cls.METADATA_SYMBOLS.get(key)
            if not symbol:
                continue
            
            # Use superscript notation for energy and coupling keys
            if key in cls._SUPERSCRIPT_KEYS:
                parts.append(f"{symbol}^{value}")
            else:
                parts.append(f"{symbol}{value}")
        
        return "{" + ",".join(parts) + "}" if parts else ""
    
    @classmethod
    def generate_diagram_data(
        cls, 
        trace: List[Tuple[str, str]], 
        metadata: Optional[Dict[int, Dict[str, Any]]] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate structured data for Feynman diagram visualization.
        
        Args:
            trace: List of (role, name) tuples representing the execution path.
            metadata: Optional dictionary mapping trace indices to metadata dictionaries.
        
        Returns:
            Dictionary with 'vertices', 'propagators', 'particles', and 'interactions' keys,
            each containing a list of node data dictionaries.
            
        Example:
            >>> trace = [("VERTEX", "endpoint")]
            >>> data = FeynNotator.generate_diagram_data(trace)
            >>> data["vertices"][0]["name"]
            'endpoint'
        """
        if not trace:
            return {
                "vertices": [],
                "propagators": [],
                "particles": [],
                "interactions": []
            }
        
        diagram: Dict[str, List[Dict[str, Any]]] = {
            "vertices": [],
            "propagators": [],
            "particles": [],
            "interactions": []
        }
        
        for i, (role, name) in enumerate(trace):
            node_data: Dict[str, Any] = {
                "id": i,
                "name": name,
                "type": role,
                "symbol": cls.SYMBOLS.get(role, "?"),
                "metadata": metadata.get(i, {}) if metadata else {}
            }
            
            # Categorize node by its role
            if role.startswith("VERTEX"):
                diagram["vertices"].append(node_data)
            elif role.startswith("PROPAGATOR"):
                diagram["propagators"].append(node_data)
            elif role.startswith("PARTICLE") or role in ["FRONTEND", "JAVASCRIPT"]:
                diagram["particles"].append(node_data)
            
            # All nodes are also tracked in interactions
            diagram["interactions"].append(node_data)
        
        return diagram
