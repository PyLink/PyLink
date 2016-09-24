# servermaps.py: Maps out connected IRC servers.

from pylinkirc import utils, world
from pylinkirc.log import log
from pylinkirc.coremods import permissions

import collections

def _percent(num, total):
    return '%.1f' % (num/total*100)

def _map(irc, source, args):
    """[<network>]

    Shows the network map for the given network, or the current network if not specified."""

    permissions.checkPermissions(irc, source, ['servermap.map', 'servermap.*'])

    try:
        netname = args[0]
    except IndexError:
        netname = irc.name

    try:
        ircobj = world.networkobjects[netname]
    except KeyError:
        irc.reply('Error: no such network %s' % netname)
        return

    servers = collections.defaultdict(set)
    hostsid = ircobj.sid
    usercount = len(ircobj.users)

    # Iterate over every connected server.
    serverlist = ircobj.servers.copy()
    for sid, serverobj in serverlist.items():
        # Save the server as UNDER its uplink.
        if sid == hostsid:
            continue
        servers[(netname, serverobj.uplink or ircobj.sid)].add(sid)

    log.debug('(%s) servermaps.map servers fetched for %s: %s', irc.name, netname, servers)

    reply = lambda text: irc.reply(text, private=True)

    def showall(sid, hops=0):
        if hops == 0:
            # Show our root server once.
            rootusers = len(serverlist[sid].users)
            reply('%s[%s]: %s user(s) (%s%%)' % (serverlist[sid].name, sid,
                  rootusers, _percent(rootusers, usercount)))

        log.debug('(%s) servermaps: servers under sid %s: %s', irc.name, sid, servers)

        # Every time we descend a server to process its map, raise the hopcount used in formatting.
        hops += 1
        leaves = servers[(netname, sid)]
        for leafcount, leaf in enumerate(leaves):

            # If we reach the end of a server's map, display `- instead of |- for prettier output.
            linechar = '`-' if leafcount == len(leaves)-1 else '|-'

            serverusers = len(serverlist[leaf].users)
            reply("%s%s%s[%s]: %s user(s) (%s%%)" % (' '*hops, linechar, serverlist[leaf].name, leaf,
                                                      serverusers, _percent(serverusers, usercount)))
            showall(leaf, hops)
        else:
            # Afterwards, decrement the hopcount.
            hops -= 1

    # Start the map at our PyLink server
    firstserver = hostsid
    showall(firstserver)
    reply('Total %s users on %s servers - average of %1.f per server' % (usercount, len(serverlist),
          usercount/len(serverlist)))

utils.add_cmd(_map, 'map')
