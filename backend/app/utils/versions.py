from importlib import metadata


def package_version(name: str) -> str | None:
    """Installed version of a pip package, or None if it isn't installed."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


# Bump when the heuristic's logic changes, so stored results stay interpretable.
TAMPERING_HEURISTIC_VERSION = "heuristic-v2"
