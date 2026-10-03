"""Versioned, deterministic adapters. No arbitrary user-supplied URLs."""

__all__ = ["registry"]


def __getattr__(name):
    # Leaf parsers need neither online fetching nor database capture code.
    # import_module also installs the registry on this package for later access.
    if name != "registry":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module
    return import_module(f"{__name__}.registry")
