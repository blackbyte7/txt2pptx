"""txt2pptx - turn text and documents into professional PowerPoint decks."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("txt2pptx")
except PackageNotFoundError:  # running from a source checkout without installation
    __version__ = "0.0.0+local"

__all__ = ["__version__"]
