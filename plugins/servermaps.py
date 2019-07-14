# servermaps.py: Maps out connected IRC servers.

import collections

from pylinkirc import utils, world
from pylinkirc.coremods import permissions
from pylinkirc.log import log

DEFAULT_PERMISSIONS = {"$ircop": ['servermaps.localmap']}

def main(irc=None):
    """Servermaps plugin main function, called on plugin load."""
    # Register our permissions.
    permissions.add_default_permissions(DEFAULT_PERMISSIONS)

def die(irc=None):
    """Servermaps plugin die function, called on plugin unload."""
    permissions.remove_default_permissions(DEFAULT_PERMISSIONS)

def _percent(num, total):
    return '%.1f' % (num/total*100)

def _map(irc, source, args, show_relay=True):
    """[<network>]

    Shows the network map for the given network, or the current network if not specified."""

    if show_relay:
        perm = 'servermaps.map'
    else:
        perm = 'servermaps.localmap'
    permissions.check_permissions(irc, source, [perm])

    try:
        netname = args[0]
    except IndexError:
        netname = irc.name

    try:
        ircobj = world.networkobjects[netname]
    except KeyError:
        irc.error('no such network %s' % netname)
        return

    servers = collections.defaultdict(set)
    hostsid = ircobj.sid
    usercount = len(ircobj.users)

    # Iterate over every connected server on every network.
    for remotenet, remoteirc in world.networkobjects.items():
        for sid, serverobj in remoteirc.servers.copy().items():
            if sid == remoteirc.sid:  # Don't re-add our own SID to the index
                continue

            # Save the server as UNDER its uplink.
            servers[(remotenet, serverobj.uplink or remoteirc.sid)].add(sid)

    log.debug('(%s) servermaps.map servers fetched for %s: %s', irc.name, netname, servers)

    reply = lambda text: irc.reply(text, private=True)

    def showall(ircobj, sid, hops=0, is_relay_server=False):
        log.debug('servermaps: got showall() for SID %s on network %s', sid, ircobj.name)
        serverlist = ircobj.servers.copy()
        netname = ircobj.name

        if hops == 0:
            # Show our root server once.
            rootusers = len(serverlist[sid].users)
            reply('\x02%s\x02[%s]: %s user(s) (%s%%) {hopcount: %d}' % (serverlist[sid].name, sid,
                  rootusers, _percent(rootusers, usercount), serverlist[sid].hopcount))

        log.debug('(%s) servermaps: servers under sid %s: %s', irc.name, sid, servers)

        # Every time we descend a server to process its map, raise the hopcount used in formatting.
        hops += 1
        leaves = servers[(netname, sid)]
        for leafcount, leaf in enumerate(leaves):
            if is_relay_server and hasattr(serverlist[leaf], 'remote'):
                # Don't show relay subservers more than once.
                continue

            serverusers = len(serverlist[leaf].users)
            if is_relay_server:
                # Skip showing user data for relay servers.
                reply("%s\x02%s\x02[%s] (via PyLink Relay)" %
                      ('    '*hops, serverlist[leaf].name, leaf))
            else:
                reply("%s\x02%s\x02[%s]: %s user(s) (%s%%) {hopcount: %d}" %
                      ('    '*hops, serverlist[leaf].name, leaf,
                       serverusers, _percent(serverusers, usercount), serverlist[leaf].hopcount))
            showall(ircobj, leaf, hops, is_relay_server=is_relay_server)

            if (not is_relay_server) and hasattr(serverlist[leaf], 'remote') and show_relay:
                # This is a relay server - display the remote map of the network it represents
                relay_server = serverlist[leaf].remote
                remoteirc = world.networkobjects[relay_server]
                if remoteirc.has_cap('can-track-servers'):
                    # Only ever show relay subservers once - this prevents infinite loops.
                    showall(remoteirc, remoteirc.sid, hops=hops, is_relay_server=True)
                else:
                    # For Clientbot links, show the server we're actually connected to.
                    reply("%s\x02%s\x02 (actual server name)" %
                          ('    '*(hops+1), remoteirc.uplink))

        else:
            # Afterwards, decrement the hopcount.
            hops -= 1

    # Start the map at our PyLink server
    firstserver = hostsid
    showall(ircobj, firstserver)
    serverlist = irc.servers
    reply('Total %s users on %s local servers - average of %1.f per server' % (usercount, len(serverlist),
          usercount/len(serverlist)))

utils.add_cmd(_map, 'map')

@utils.add_cmd
def localmap(irc, source, args):
    """[<network>]

    Shows the network map for the given network, or the current network if not specified.
    This command does not expand Relay subservers."""
    _map(irc, source, args, show_relay=False)
