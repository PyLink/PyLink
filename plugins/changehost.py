"""
Changehost plugin - automatically changes the hostname of matching users.
"""
from pylinkirc import utils, world, conf
from pylinkirc.log import log
from pylinkirc.coremods import permissions

import string

# ircmatch library from https://github.com/mammon-ircd/ircmatch
# (pip install ircmatch)
import ircmatch

# Characters allowed in a hostname.
allowed_chars = string.ascii_letters + '-./:' + string.digits

def _changehost(irc, target, args):
    changehost_conf = conf.conf.get("changehost")

    if target not in irc.users:
        return
    elif irc.isInternalClient(target):
        log.debug('(%s) Skipping changehost on internal client %s', irc.name, target)
        return

    if not changehost_conf:
        log.warning("(%s) Missing 'changehost:' configuration block; "
                    "Changehost will not function correctly!", irc.name)
        return
    elif irc.name not in changehost_conf.get('enabled_nets'):
        # We're not enabled on the network, break.
        return

    match_ip = changehost_conf.get('match_ip', False)
    match_realhosts = changehost_conf.get('match_realhosts', False)

    changehost_hosts = changehost_conf.get('hosts')
    if not changehost_hosts:
        log.warning("(%s) No hosts were defined in changehost::hosts; "
                    "Changehost will not function correctly!", irc.name)
        return

    args = args.copy()
    if not changehost_conf.get('force_host_expansion'):
       del args['host']

    log.debug('(%s) Changehost args: %s', irc.name, args)

    for host_glob, host_template in changehost_hosts.items():
        log.debug('(%s) Changehost: checking mask %s', irc.name, host_glob)
        if irc.matchHost(host_glob, target, ip=match_ip, realhost=match_realhosts):
            log.debug('(%s) Changehost matched mask %s', irc.name, host_glob)
            # This uses template strings for simple substitution:
            # https://docs.python.org/3/library/string.html#template-strings
            template = string.Template(host_template)

            # Substitute using the fields provided the hook data. This means
            # that the following variables are available for substitution:
            # $uid, $ts, $nick, $realhost, $ident, and $ip.

            # $host is explicitly forbidden by default because it can cause
            # recursive loops when IP or real host masks are used to match a
            # target. vHost updates do not affect these fields, so any further
            # execution of 'applyhosts' will cause $host to expand again to
            # the user's new host, causing the vHost to grow rapidly in size.
            # That said, it is possible to get away with this expansion if
            # you're careful with what you're doing, and that is why this
            # hidden option exists. -GLolol

            try:
                new_host = template.substitute(args)
            except KeyError as e:
                log.warning('(%s) Bad expansion %s in template %s' % (irc.name, e, host_template))
                continue

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

def handle_chghost(irc, sender, command, args):
    """
    Handles incoming CHGHOST requests for optional host-change enforcement.
    """
    changehost_conf = conf.conf.get("changehost")
    if not changehost_conf:
        return

    target = args['target']

    if (not irc.isInternalClient(sender)) and (not irc.isInternalServer(sender)):
        if irc.name in changehost_conf.get('enforced_nets', []):
            log.debug('(%s) Enforce for network is on, re-checking host for target %s/%s',
                      irc.name, target, irc.getFriendlyName(target))

            for ex in changehost_conf.get("enforce_exceptions", []):
                if irc.matchHost(ex, target):
                    log.debug('(%s) Skipping host change for target %s; they are exempted by mask %s',
                              irc.name, target, ex)
                    return

            userdata = irc.users.get(target)
            if userdata:
                _changehost(irc, target, userdata.__dict__)

utils.add_hook(handle_chghost, 'CHGHOST')

@utils.add_cmd
def applyhosts(irc, sender, args):
    """[<network>]

    Applies all configured hosts for users on the given network, or the current network if none is specified."""

    permissions.checkPermissions(irc, sender, ['changehost.applyhosts'])

    try:  # Try to get network from the command line.
        network = world.networkobjects[args[0]]
    except IndexError:  # No network was given
        network = irc
    except KeyError:  # Unknown network
        irc.error("Unknown network '%s'." % network)
        return

    for user, userdata in network.users.copy().items():
        _changehost(network, user, userdata.__dict__)

    irc.reply("Done.")
