# global.py: Global Noticing Plugin

import string

from pylinkirc import conf, utils, world
from pylinkirc.coremods import permissions
from pylinkirc.log import log

DEFAULT_FORMAT = "[$sender@$fullnetwork] $text"

def g(irc, source, args):
    """<message text>

    Sends out a Instance-wide notice.
    """
    permissions.check_permissions(irc, source, ["global.global"])
    message = " ".join(args).strip()

    if not message:
        irc.error("Refusing to send an empty message.")
        return

    global_conf = conf.conf.get('global') or {}
    template = string.Template(global_conf.get('format', DEFAULT_FORMAT))

    exempt_channels = set(global_conf.get('exempt_channels', set()))

    netcount = 0
    chancount = 0
    for netname, ircd in world.networkobjects.items():
        # Skip networks that aren't ready and dummy networks which don't have .pseudoclient set
        if ircd.connected.is_set() and ircd.pseudoclient:
            netcount += 1
            for channel in ircd.pseudoclient.channels:

                local_exempt_channels = exempt_channels | set(ircd.serverdata.get('global_exempt_channels', set()))

                skip = False
                for exempt in local_exempt_channels:
                    if ircd.match_text(exempt, str(channel)):
                        log.debug('global: Skipping channel %s%s for exempt %r', netname, channel, exempt)
                        skip = True
                        break

                if skip:
                    continue

                subst = {'sender': irc.get_friendly_name(source),
                         'network': irc.name,
                         'fullnetwork': irc.get_full_network_name(),
                         'current_channel': channel,
                         'current_network': netname,
                         'current_fullnetwork': ircd.get_full_network_name(),
                         'text': message}

                # Disable relaying or other plugins handling the global message.
                ircd.msg(channel, template.safe_substitute(subst), loopback=False)

                chancount += 1

    irc.reply('Done. Sent to %d channels across %d networks.' % (chancount, netcount))

utils.add_cmd(g, "global", featured=True)
