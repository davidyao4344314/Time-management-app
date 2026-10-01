"""Temporary module facades; forward legacy names without copying mutable state."""

import sys
from types import ModuleType


class _ForwardingModule(ModuleType):
    def __getattr__(self, name):
        target = self.__dict__.get("_forwarded_names", {}).get(name)
        if target is None:
            raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")
        module, attribute = target
        return getattr(module, attribute)

    def __setattr__(self, name, value):
        target = self.__dict__.get("_forwarded_names", {}).get(name)
        if target is None:
            super().__setattr__(name, value)
        else:
            module, attribute = target
            setattr(module, attribute, value)

    def __delattr__(self, name):
        target = self.__dict__.get("_forwarded_names", {}).get(name)
        if target is None:
            super().__delattr__(name)
        else:
            module, attribute = target
            delattr(module, attribute)

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(self._forwarded_names))


def forward_module(module_name, targets):
    """Keep legacy reads, assignments and test patches routed to their owner."""
    module = sys.modules[module_name]
    module._forwarded_names = targets
    module.__class__ = _ForwardingModule
