class FeynNotator:
    # Physics-inspired symbols with force carriers and quantum states
    SYMBOLS = {
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
    METADATA_SYMBOLS = {
        "mass": "ₘ",           # Mass/complexity
        "charge": "ᶜ",         # Charge/importance  
        "spin": "ˢ",           # Spin/rotation
        "energy": "ᴱ",         # Energy/activity
        "coupling": "ᶜ",        # Coupling strength
        "lifetime": "ᵗ",       # Lifetime/stability
    }
    
    @classmethod
    def generate_enhanced_string(cls, trace, metadata=None):
        """Generate physics-inspired notation with embedded metadata."""
        parts = []
        for i, (role, name) in enumerate(trace):
            symbol = cls.SYMBOLS.get(role, "?")
            meta_data = metadata.get(i, {}) if metadata else {}
            meta_str = cls._format_metadata(meta_data)
            parts.append(f"{symbol}[{name}]{meta_str}")
        return " -> ".join(parts)
    
    @classmethod
    def generate_string(cls, trace):
        """Legacy method for backward compatibility."""
        return cls.generate_enhanced_string(trace)
    
    @classmethod
    def _format_metadata(cls, metadata):
        """Format metadata as superscript/subscript notation."""
        if not metadata:
            return ""
        
        parts = []
        for key, value in metadata.items():
            symbol = cls.METADATA_SYMBOLS.get(key, "")
            if symbol and value is not None:
                # Format as subscript/superscript
                if key in ["mass", "charge", "spin"]:
                    parts.append(f"{symbol}{value}")
                elif key in ["energy", "coupling"]:
                    parts.append(f"{symbol}^{value}")
                else:
                    parts.append(f"{symbol}{value}")
        
        if parts:
            return "{" + ",".join(parts) + "}"
        return ""
    
    @classmethod
    def generate_diagram_data(cls, trace, metadata=None):
        """Generate structured data for Feynman diagram visualization."""
        diagram = {
            "vertices": [],
            "propagators": [],
            "particles": [],
            "interactions": []
        }
        
        for i, (role, name) in enumerate(trace):
            node_data = {
                "id": i,
                "name": name,
                "type": role,
                "symbol": cls.SYMBOLS.get(role, "?"),
                "metadata": metadata.get(i, {}) if metadata else {}
            }
            
            if role.startswith("VERTEX"):
                diagram["vertices"].append(node_data)
            elif role.startswith("PROPAGATOR"):
                diagram["propagators"].append(node_data)
            elif role.startswith("PARTICLE") or role in ["FRONTEND", "JAVASCRIPT"]:
                diagram["particles"].append(node_data)
            
            diagram["interactions"].append(node_data)
        
        return diagram