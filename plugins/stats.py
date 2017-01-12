"""
stats.py: Simple statistics for PyLink IRC Services.
"""
import time
import datetime

from pylinkirc import utils, world
from pylinkirc.log import log
from pylinkirc.coremods import permissions

def _timesince(before, now):
    return str(datetime.timedelta(seconds=now-before))

@utils.add_cmd
def uptime(irc, source, args):
    """[<network>]

    Returns the uptime for PyLink and the given network's connection (or the current network if not specified)."""
    permissions.checkPermissions(irc, source, ['stats.uptime'])

    try:
        network = args[0]
    except IndexError:
        network = irc.name

    try:
        ircobj = world.networkobjects[network]
    except KeyError:
        irc.error("No such network %r." % network)
        return

    current_time = int(time.time())

    irc.reply("PyLink uptime: \x02%s\x02, Connected to %s: \x02%s\x02" % \
              (_timesince(world.start_ts, current_time), network, _timesince(irc.start_ts, current_time)))

