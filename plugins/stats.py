"""
stats.py: Simple statistics for PyLink IRC Services.
"""
import time
import datetime

from pylinkirc import utils, world, conf
from pylinkirc.log import log
from pylinkirc.coremods import permissions

def timediff(before, now):
    """
    Returns the time difference between "before" and "now" as a formatted string.
    """
    td = datetime.timedelta(seconds=now-before)
    days = td.days

    hours, leftover = divmod(td.seconds, 3600)
    minutes, seconds = divmod(leftover, 60)

    # XXX: I would make this more configurable but it's a lot of work for little gain,
    # since there's no strftime for time differences.
    return '%d day%s, %02d:%02d:%02d' % (td.days, 's' if td.days != 1 else '',
                                         hours, minutes, seconds)

# From RFC 2822: https://tools.ietf.org/html/rfc2822.html#section-3.3
DEFAULT_TIME_FORMAT = "%a, %d %b %Y %H:%M:%S +0000"

@utils.add_cmd
def uptime(irc, source, args):
    """[<network> / --all]

    Returns the uptime for PyLink and the given network's connection (or the current network if not specified).
    The --all argument can also be given to show the uptime for all networks."""
    permissions.checkPermissions(irc, source, ['stats.uptime'])

    try:
        network = args[0]
    except IndexError:
        network = irc.name

    if network == '--all':  # XXX: we really need smart argument parsing some time
        # Filter by all connected networks.
        ircobjs = {k:v for k,v in world.networkobjects.items() if v.connected.is_set()}
    else:
        try:
            ircobjs = {network: world.networkobjects[network]}
        except KeyError:
            irc.error("No such network %r." % network)
            return
        if not world.networkobjects[network].connected.is_set():
            irc.error("Network %s is not connected." % network)
            return

    current_time = int(time.time())
    time_format = conf.conf.get('stats', {}).get('time_format', DEFAULT_TIME_FORMAT)

    irc.reply("PyLink uptime: \x02%s\x02 (started on %s)" %
              (timediff(world.start_ts, current_time),
               time.strftime(time_format, time.gmtime(world.start_ts))
              )
             )

    for network, ircobj in sorted(ircobjs.items()):
        irc.reply("Connected to %s: \x02%s\x02 (connected on %s)" %
                  (network,
                   timediff(ircobj.start_ts, current_time),
                   time.strftime(time_format, time.gmtime(ircobj.start_ts))
                  )
                 )


