"""
Changehost plugin - automatically changes the hostname of matching users.
"""
from pylinkirc import utils, world
from pylinkirc.log import log

import string

# ircmatch library from https://github.com/mammon-ircd/ircmatch
# (pip install ircmatch)
import ircmatch

# Characters allowed in a hostname.
allowed_chars = string.ascii_letters + '-./:' + string.digits

def _changehost(irc, target, args):
    changehost_conf = irc.conf.get("changehost")

    if not changehost_conf:
        log.warning("(%s) Missing 'changehost:' configuration block; "
                    "Changehost will not function correctly!", irc.name)
        return
    elif irc.name not in changehost_conf.get('enabled_nets'):
        # We're not enabled on the network, break.
        return

    changehost_hosts = changehost_conf.get('hosts')
    if not changehost_hosts:
        log.warning("(%s) No hosts were defined in changehost::hosts; "
                    "Changehost will not function correctly!", irc.name)
        return

    for host_glob, host_template in changehost_hosts.items():
        if irc.matchHost(host_glob, target):
            # This uses template strings for simple substitution:
            # https://docs.python.org/3/library/string.html#template-strings
            template = string.Template(host_template)

            # Substitute using the fields provided the hook data. This means
            # that the following variables are available for substitution:
            # $uid, $ts, $nick, $realhost, $host, $ident, $ip
            new_host = template.substitute(args)

            # Replace characters that are not allowed in hosts with "-".
            for char in new_host:
                if char not in allowed_chars:
                    new_host = new_host.replace(char, '-')

            irc.proto.updateClient(target, 'HOST', new_host)

            # Only operate on the first match.
            break

def handle_uid(irc, sender, command, args):
    """
    Changehost listener for new connections.
    """

    target = args['uid']
    _changehost(irc, target, args)

utils.add_hook(handle_uid, 'UID')

@utils.add_cmd
def applyhosts(irc, sender, args):
    """[<network>]

    Applies all configured hosts for users on the given network, or the current network if none is specified."""

    try:  # Try to get network from the command line.
        network = world.networkobjects[args[0]]
    except IndexError:  # No network was given
        network = irc
    except KeyError:  # Unknown network
        irc.reply("Error: Unknown network '%s'." % network)
        return

    for user, userdata in network.users.copy().items():
        _changehost(network, user, userdata.__dict__)

    irc.reply("Done.")
