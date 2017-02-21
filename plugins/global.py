# global.py: Global Notice Plugin, akin to /msg Global GLOBAL

from pylinkirc import utils
from pylinkirc.log import log

# TODO: use IRCParser if subject is wanted?

# TODO: maybe add service bot for global messages?

def _global(irc, source, args):
    """<message text>

    Sends out a global notice to all channels."""

    

utils.add_cmd(_global, "global")





