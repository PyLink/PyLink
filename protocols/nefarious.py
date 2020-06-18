"""
nefarious.py: Migration stub to the new P10 protocol module.
"""

from pylinkirc.log import log
from pylinkirc.protocols.p10 import P10Protocol

__all__ = ['NefariousProtocol']


class NefariousProtocol(P10Protocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        log.warning("(%s) protocols/nefarious.py has been renamed to protocols/p10.py, which "
                    "now also supports other IRCu variants. Please update your configuration, "
                    "as this migration stub will be removed in a future version.",
                    self.name)

Class = NefariousProtocol
