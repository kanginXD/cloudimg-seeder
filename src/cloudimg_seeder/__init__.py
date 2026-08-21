"""Public library API."""

from importlib.metadata import version as _version

from cloudimg_seeder.arch import GuestArch
from cloudimg_seeder.disk import OutputFormat
from cloudimg_seeder.errors import SeedError
from cloudimg_seeder.seeder import SeedConfig, seed

__version__ = _version("cloudimg-seeder")

__all__ = [
    "GuestArch",
    "OutputFormat",
    "SeedConfig",
    "SeedError",
    "__version__",
    "seed",
]
