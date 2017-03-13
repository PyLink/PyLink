# global.py: Global Noticing Plugin

import string

from pylinkirc import conf, utils, world
from pylinkirc.log import log
from pylinkirc.coremods import permissions

DEFAULT_FORMAT = "[$sender@$fullnetwork] $text"

def g(irc, source, args):
    """<message text>

    Sends out a Instance-wide notice.
    """
    permissions.checkPermissions(irc, source, ["global.global"])
    message = " ".join(args)
    template = string.Template(conf.conf.get('global', {}).get("format", DEFAULT_FORMAT))

    for name, ircd in world.networkobjects.items():
        if ircd.connected.is_set():  # Only attempt to send to connected networks
            for channel in ircd.pseudoclient.channels:
                subst = {'sender': irc.getFriendlyName(source),
                         'network': irc.name,
                         'fullnetwork': irc.getFullNetworkName(),
                         'current_channel': channel,
                         'current_network': ircd.name,
                         'current_fullnetwork': ircd.getFullNetworkName(),
                         'text': message}

                # Disable relaying or other plugins handling the global message.
                ircd.msg(channel, template.safe_substitute(subst), loopback=False)


utils.add_cmd(g, "global", featured=True)
