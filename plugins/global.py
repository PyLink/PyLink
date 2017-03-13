# global.py: Global Noticing Plugin

from pylinkirc import conf, utils, world
from pylinkirc.log import log
from pylinkirc.coremods import permissions

def g(irc, source, args):
    """<message text>

    Sends out a Instance-wide notice.
    """
    permissions.checkPermissions(irc, source, ["global.global"])
    message = " ".join(args)
    message = message + " (sent by %s@%s)" % (irc.getFriendlyName(irc.called_by), irc.getFullNetworkName())
    for name, ircd in world.networkobjects.items():
        if ircd.connected.is_set():  # Only attempt to send to connected networks
            for channel in ircd.pseudoclient.channels:
                # Disable relaying or other plugins handling the global message.
                ircd.msg(channel, message, loopback=False)


utils.add_cmd(g, "global", featured=True)
