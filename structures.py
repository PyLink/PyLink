"""
structures.py - PyLink data structures module.

This module contains custom data structures that may be useful in various situations.
"""

import collections

class KeyedDefaultdict(collections.defaultdict):
    """
    Subclass of defaultdict allowing the key to be passed to the default factory.
    """
    def __missing__(self, key):
        if self.default_factory is None:
            # If there is no default factory, just let defaultdict handle it
            super().__missing__(self, key)
        else:
            value = self[key] = self.default_factory(key)
            return value
