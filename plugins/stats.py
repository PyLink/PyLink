"""
stats.py: Simple statistics for PyLink IRC Services.
"""
import datetime
import time

from pylinkirc import conf, utils, world
from pylinkirc.coremods import permissions
from pylinkirc.log import log


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
    permissions.check_permissions(irc, source, ['stats.uptime'])

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

def handle_stats(irc, source, command, args):
    """/STATS handler. Currently supports the following:

    c - link blocks
    o - oper blocks (accounts)
    u - shows uptime
    """

    stats_type = args['stats_type'][0].lower()  # stats_type shouldn't be more than 1 char anyways

    perms = ['stats.%s' % stats_type]

    if stats_type == 'u':
        perms.append('stats.uptime')  # Consistency

    try:
        permissions.check_permissions(irc, source, perms)
    except utils.NotAuthorizedError as e:
        # Note, no irc.error() because this is not a command, but a handler
        irc.msg(source, 'Error: %s' % e, notice=True)
        return

    log.info('(%s) /STATS %s requested by %s', irc.name, stats_type, irc.get_hostmask(source))

    def _num(num, text):
        irc.numeric(args['target'], num, source, text)

    if stats_type == 'c':
        # 213/RPL_STATSCLINE: "C <host> * <name> <port> <class>"
        for netname, serverdata in sorted(conf.conf['servers'].items()):
            # We're cramming as much as we can into the class field...
            _num(213, "C %s * %s %s [%s:%s:%s]" %
                 (serverdata.get('ip', '0.0.0.0'),
                  netname,
                  serverdata.get('port', 0),
                  serverdata['protocol'],
                  'ssl' if serverdata.get('ssl') else 'no-ssl',
                  serverdata.get('encoding', 'utf-8'))
                 )
    elif stats_type == 'o':
        # 243/RPL_STATSOLINE: "O <hostmask> * <nick> [:<info>]"
        # New style accounts only!
        for accountname, accountdata in conf.conf['login'].get('accounts', {}).items():
            networks = accountdata.get('networks', [])
            if irc.name in networks or not networks:
                hosts = ' '.join(accountdata.get('hosts', ['*@*']))
                needoper = 'needoper' if accountdata.get('require_oper') else ''
                _num(243, "O %s * %s :%s" % (hosts, accountname, needoper))

    elif stats_type == 'u':
        # 242/RPL_STATSUPTIME: ":Server Up <days> days <hours>:<minutes>:<seconds>"
        _num(242, ':Server Up %s' % timediff(world.start_ts, int(time.time())))

    else:
        log.info('(%s) Unknown /STATS type %r requested by %s', irc.name, stats_type, irc.get_hostmask(source))
    _num(219, "%s :End of /STATS report" % stats_type)
utils.add_hook(handle_stats, 'STATS')
