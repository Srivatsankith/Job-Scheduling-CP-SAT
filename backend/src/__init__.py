"""DynamIQ manufacturing scheduling backend.

Import solver explicitly from ``src.cp_sat_scheduler`` so data tools remain
usable before the optional solver dependency is installed.
"""
from .schema_mapper import SchemaMapping
__all__ = ["SchemaMapping"]
