"""
nefarious.py: Migration stub to the new P10 protocol module.
"""

from pylinkirc.log import log
from pylinkirc.protocols.p10 import *

class NefariousProtocol(P10Protocol):
    def __init__(self, irc):
        super().__init__(irc)
        log.warning("(%s) protocols/nefarious.py has been renamed to protocols/p10.py, which "
                    "now also supports other IRCu variants. Please update your configuration, "
                    "as this migration stub will be removed in a future version.",
                    self.irc.name)

Class = NefariousProtocol
