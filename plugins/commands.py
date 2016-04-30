# commands.py: base PyLink commands
import sys
import os
from time import ctime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils
from log import log
import world

@utils.add_cmd
def status(irc, source, args):
    """takes no arguments.

    Returns your current PyLink login status."""
    identified = irc.users[source].identified
    if identified:
        irc.reply('You are identified as \x02%s\x02.' % identified)
    else:
        irc.reply('You are not identified as anyone.')
    irc.reply('Operator access: \x02%s\x02' % bool(irc.isOper(source)))

def listcommands(irc, source, args):
    """takes no arguments.

    Returns a list of available commands PyLink has to offer."""
    cmds = list(world.commands.keys())
    cmds.sort()
    for idx, cmd in enumerate(cmds):
        nfuncs = len(world.commands[cmd])
        if nfuncs > 1:
            cmds[idx] = '%s(x%s)' % (cmd, nfuncs)
    irc.reply('Available commands include: %s' % ', '.join(cmds))
    irc.reply('To see help on a specific command, type \x02help <command>\x02.')
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
            irc.reply('The following \x02%s\x02 plugins bind to the \x02%s\x02 command: %s'
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
                    irc.reply(line.strip())
            else:
                irc.msg(source, "Error: Command %r (from plugin %r) "
                                       "doesn't offer any help." % (command, mod))
                return

_none = '\x1D(none)\x1D'
@utils.add_cmd
def showuser(irc, source, args):
    """<user>

    Shows information about <user>."""
    try:
        target = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: nick.")
        return
    u = irc.nickToUid(target) or target
    # Only show private info if the person is calling 'showuser' on themselves,
    # or is an oper.
    verbose = irc.isOper(source) or u == source
    if u not in irc.users:
        irc.reply('Error: Unknown user %r.' % target)
        return

    f = lambda s: irc.msg(source, s)
    userobj = irc.users[u]
    f('Information on user \x02%s\x02 (%s@%s): %s' % (userobj.nick, userobj.ident,
      userobj.host, userobj.realname))

    sid = irc.getServer(u)
    serverobj = irc.servers[sid]
    ts = userobj.ts

    # Show connected server & signon time
    f('\x02Home server\x02: %s (%s); \x02Signon time:\x02 %s (%s)' % \
      (serverobj.name, sid, ctime(float(ts)), ts))

    if verbose:  # Oper only data: user modes, channels on, account info, etc.

        f('\x02User modes\x02: %s' % irc.joinModes(userobj.modes))
        f('\x02Protocol UID\x02: %s; \x02Real host\x02: %s; \x02IP\x02: %s' % \
          (u, userobj.realhost, userobj.ip))
        channels = sorted(userobj.channels)
        f('\x02Channels\x02: %s' % (' '.join(channels) or _none))
        f('\x02PyLink identification\x02: %s; \x02Services account\x02: %s; \x02Away status\x02: %s' % \
          ((userobj.identified or _none), (userobj.services_account or _none), userobj.away or _none))


@utils.add_cmd
def showchan(irc, source, args):
    """<channel>

    Shows information about <channel>."""
    try:
        channel = irc.toLower(args[0])
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: channel.")
        return
    if channel not in irc.channels:
        irc.reply('Error: Unknown channel %r.' % channel)
        return

    f = lambda s: irc.msg(source, s)
    c = irc.channels[channel]
    # Only show verbose info if caller is oper or is in the target channel.
    verbose = source in c.users or irc.isOper(source)
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
    modes = irc.joinModes([m for m in c.modes if m[0] not in irc.cmodes['*A']])
    f('\x02Channel modes\x02: %s' % modes)
    if verbose:
        nicklist = []
        # Iterate over the user list, sorted by nick.
        for user, nick in sorted(zip(c.users, nicks),
                                 key=lambda userpair: userpair[1].lower()):
            prefixmodes = [irc.prefixmodes.get(irc.cmodes.get(pmode, ''), '')
                           for pmode in pmodes if user in c.prefixmodes[pmode]]
            nicklist.append(''.join(prefixmodes) + nick)

        while nicklist[:20]:  # 20 nicks per line to prevent message cutoff.
            f('\x02User list\x02: %s' % ' '.join(nicklist[:20]))
            nicklist = nicklist[20:]

@utils.add_cmd
def version(irc, source, args):
    """takes no arguments.

    Returns the version of the currently running PyLink instance."""
    irc.reply("PyLink version \x02%s\x02, released under the Mozilla Public License version 2.0." % world.version)
    irc.reply("The source of this program is available at \x02%s\x02." % world.source)

@utils.add_cmd
def echo(irc, source, args):
    """<text>

    Echoes the text given."""
    irc.reply(' '.join(args))

loglevels = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40, 'CRITICAL': 50}
@utils.add_cmd
def loglevel(irc, source, args):
    """<level>

    Sets the log level to the given <level>. <level> must be either DEBUG, INFO, WARNING, ERROR, or CRITICAL.
    If no log level is given, shows the current one."""
    irc.checkAuthenticated(source, allowOper=False)
    try:
        level = args[0].upper()
        try:
            loglevel = loglevels[level]
        except KeyError:
            irc.reply('Error: Unknown log level "%s".' % level)
            return
        else:
            world.stdout_handler.setLevel(loglevel)
            irc.reply("Done.")
    except IndexError:
        irc.reply(world.stdout_handler.level)
