"""Screen Time storage with compatibility exports for the previous module."""

from backend.app.infrastructure.module_compat import forward_module
from backend.app.screen_time import storage

forward_module(__name__, {name: (storage, name) for name in dir(storage) if not name.startswith("__")})
