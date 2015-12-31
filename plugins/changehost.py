"""
Changehost plugin - automatically changes the hostname of matching users.
"""

# Import hacks to access utils and log.
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import string

# ircmatch library from https://github.com/mammon-ircd/ircmatch
# (pip install ircmatch)
import ircmatch

import utils
import world
from log import log

# Characters allowed in a hostname.
allowed_chars = string.ascii_letters + '-./:' + string.digits

def handle_uid(irc, sender, command, args):
    """
    Listener for new connections.
    """

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

    target = args['uid']

    for host_glob, host_template in changehost_hosts.items():
        if ircmatch.match(0, host_glob, utils.getHostmask(irc, target)):
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

utils.add_hook(handle_uid, 'UID')
