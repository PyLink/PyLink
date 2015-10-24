# commands.py: base PyLink commands
import sys
import os
from time import ctime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils
import conf
from log import log
import world
import classes

@utils.add_cmd
def status(irc, source, args):
    """takes no arguments.

    Returns your current PyLink login status."""
    identified = irc.users[source].identified
    if identified:
        irc.msg(irc.called_by, 'You are identified as \x02%s\x02.' % identified)
    else:
        irc.msg(irc.called_by, 'You are not identified as anyone.')
    irc.msg(irc.called_by, 'Operator access: \x02%s\x02' % bool(utils.isOper(irc, source)))

def listcommands(irc, source, args):
    """takes no arguments.

    Returns a list of available commands PyLink has to offer."""
    cmds = list(world.commands.keys())
    cmds.sort()
    for idx, cmd in enumerate(cmds):
        nfuncs = len(world.commands[cmd])
        if nfuncs > 1:
            cmds[idx] = '%s(x%s)' % (cmd, nfuncs)
    irc.msg(irc.called_by, 'Available commands include: %s' % ', '.join(cmds))
    irc.msg(irc.called_by, 'To see help on a specific command, type \x02help <command>\x02.')
utils.add_cmd(listcommands, 'list')

@utils.add_cmd
def help(irc, source, args):
    """<command>

    Gives help for <command>, if it is available."""
    try:
        command = args[0].lower()
    except IndexError:  # No argument given, just return 'list' output
        listcommands(irc, source, args)
        return
    if command not in world.commands:
        irc.msg(source, 'Error: Unknown command %r.' % command)
        return
    else:
        funcs = world.commands[command]
        if len(funcs) > 1:
            irc.msg(irc.called_by, 'The following \x02%s\x02 plugins bind to the \x02%s\x02 command: %s'
                      % (len(funcs), command, ', '.join([func.__module__ for func in funcs])))
        for func in funcs:
            doc = func.__doc__
            mod = func.__module__
            if doc:
                lines = doc.split('\n')
                # Bold the first line, which usually just tells you what
                # arguments the command takes.
                lines[0] = '\x02%s %s\x02 (plugin: %r)' % (command, lines[0], mod)
                for line in lines:
                    irc.msg(irc.called_by, line.strip())
            else:
                irc.msg(source, "Error: Command %r (from plugin %r) "
                                       "doesn't offer any help." % (command, mod))
                return

@utils.add_cmd
def showuser(irc, source, args):
    """<user>

    Shows information about <user>."""
    try:
        target = args[0]
    except IndexError:
        irc.msg(irc.called_by, "Error: Not enough arguments. Needs 1: nick.")
        return
    u = utils.nickToUid(irc, target) or target
    # Only show private info if the person is calling 'showuser' on themselves,
    # or is an oper.
    verbose = utils.isOper(irc, source) or u == source
    if u not in irc.users:
        irc.msg(irc.called_by, 'Error: Unknown user %r.' % target)
        return

    f = lambda s: irc.msg(source, s)
    userobj = irc.users[u]
    f('Information on user \x02%s\x02 (%s@%s): %s' % (userobj.nick, userobj.ident,
      userobj.host, userobj.realname))
    sid = utils.clientToServer(irc, u)
    serverobj = irc.servers[sid]
    ts = userobj.ts
    f('\x02Home server\x02: %s (%s); \x02Signon time:\x02 %s (%s)' % \
      (serverobj.name, sid, ctime(float(ts)), ts))
    if verbose:
        f('\x02Protocol UID\x02: %s; \x02PyLink identification\x02: %s' % \
          (u, userobj.identified))
        f('\x02User modes\x02: %s' % utils.joinModes(userobj.modes))
        f('\x02Real host\x02: %s; \x02IP\x02: %s; \x02Away status\x02: %s' % \
          (userobj.realhost, userobj.ip, userobj.away or '\x1D(not set)\x1D'))
        f('\x02Channels\x02: %s' % (' '.join(userobj.channels).strip() or '\x1D(none)\x1D'))

@utils.add_cmd
def showchan(irc, source, args):
    """<channel>

    Shows information about <channel>."""
    try:
        channel = utils.toLower(irc, args[0])
    except IndexError:
        irc.msg(irc.called_by, "Error: Not enough arguments. Needs 1: channel.")
        return
    if channel not in irc.channels:
        irc.msg(irc.called_by, 'Error: Unknown channel %r.' % channel)
        return

    f = lambda s: irc.msg(source, s)
    c = irc.channels[channel]
    # Only show verbose info if caller is oper or is in the target channel.
    verbose = source in c.users or utils.isOper(irc, source)
    secret = ('s', None) in c.modes
    if secret and not verbose:
        # Hide secret channels from normal users.
        irc.msg(source, 'Error: Unknown channel %r.' % channel)
        return

    nicks = [irc.users[u].nick for u in c.users]
    pmodes = ('owner', 'admin', 'op', 'halfop', 'voice')

    f('Information on channel \x02%s\x02:' % channel)
    f('\x02Channel topic\x02: %s' % c.topic)
    f('\x02Channel creation time\x02: %s (%s)' % (ctime(c.ts), c.ts))
    # Show only modes that aren't list-style modes.
    modes = utils.joinModes([m for m in c.modes if m[0] not in irc.cmodes['*A']])
    f('\x02Channel modes\x02: %s' % modes)
    if verbose:
        nicklist = []
        # Iterate over the user list, sorted by nick.
        for user, nick in sorted(zip(c.users, nicks),
                                 key=lambda userpair: userpair[1].lower()):
            prefixmodes = [irc.prefixmodes.get(irc.cmodes.get(pmode, ''), '')
                           for pmode in pmodes if user in c.prefixmodes[pmode+'s']]
            nicklist.append(''.join(prefixmodes) + nick)

        while nicklist[:20]:  # 20 nicks per line to prevent message cutoff.
            f('\x02User list\x02: %s' % ' '.join(nicklist[:20]))
            nicklist = nicklist[20:]

@utils.add_cmd
def version(irc, source, args):
    """takes no arguments.

    Returns the version of the currently running PyLink instance."""
    irc.msg(irc.called_by, "PyLink version \x02%s\x02, released under the Mozilla Public License version 2.0." % world.version)
    irc.msg(irc.called_by, "The source of this program is available at \x02%s\x02." % world.source)

@utils.add_cmd
def echo(irc, source, args):
    """<text>

    Echoes the text given."""
    irc.msg(irc.called_by, ' '.join(args))

@utils.add_cmd
def rehash(irc, source, args):
    """takes no arguments.

    Reloads the configuration file for PyLink, (dis)connecting added/removed networks.
    Plugins must be manually reloaded."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    old_conf = conf.conf.copy()
    fname = conf.fname
    try:
        new_conf = conf.validateConf(conf.loadConf(fname))
    except Exception as e:  # Something went wrong, abort.
        log.exception("Error REHASH'ing config: ")
        irc.msg(irc.called_by, "Error loading configuration file: %s: %s", type(e).__name__, e)
        return
    conf.conf = new_conf
    for network, ircobj in world.networkobjects.copy().items():
        # Server was removed from the config file, disconnect them.
        log.debug('(%s) rehash: checking if %r is in new conf still.', irc.name, network)
        if network not in new_conf['servers']:
            # Disable autoconnect first.
            log.debug('(%s) rehash: removing connection to %r (removed from config).', irc.name, network)
            ircobj.serverdata['autoconnect'] = -1
            ircobj.aborted.set()
            del world.networkobjects[network]
        else:
            ircobj.conf = new_conf
            ircobj.serverdata = new_conf['servers'][network]
    for network, sdata in new_conf['servers'].items():
        # New server was added. Connect them if not already connected.
        if network not in world.networkobjects:
            proto = utils.getProtoModule(sdata['protocol'])
            world.networkobjects[network] = classes.Irc(network, proto, new_conf)
    irc.msg(irc.called_by, "Done.")
