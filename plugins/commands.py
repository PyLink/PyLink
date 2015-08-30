# commands.py: base PyLink commands
import sys
import os
from time import ctime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils
from conf import conf
from log import log
import world

@utils.add_cmd
def status(irc, source, args):
    """takes no arguments.

    Returns your current PyLink login status."""
    identified = irc.users[source].identified
    if identified:
        utils.msg(irc, source, 'You are identified as \x02%s\x02.' % identified)
    else:
        utils.msg(irc, source, 'You are not identified as anyone.')
    utils.msg(irc, source, 'Operator access: \x02%s\x02' % bool(utils.isOper(irc, source)))

@utils.add_cmd
def identify(irc, source, args):
    """<username> <password>

    Logs in to PyLink using the configured administrator account."""
    try:
        username, password = args[0], args[1]
    except IndexError:
        utils.msg(irc, source, 'Error: Not enough arguments.')
        return
    # Usernames are case-insensitive, passwords are NOT.
    if username.lower() == conf['login']['user'].lower() and password == conf['login']['password']:
        realuser = conf['login']['user']
        irc.users[source].identified = realuser
        utils.msg(irc, source, 'Successfully logged in as %s.' % realuser)
        log.info("(%s) Successful login to %r by %s.",
                 irc.name, username, utils.getHostmask(irc, source))
    else:
        utils.msg(irc, source, 'Error: Incorrect credentials.')
        u = irc.users[source]
        log.warning("(%s) Failed login to %r from %s.",
                    irc.name, username, utils.getHostmask(irc, source))

def listcommands(irc, source, args):
    """takes no arguments.

    Returns a list of available commands PyLink has to offer."""
    cmds = list(world.bot_commands.keys())
    cmds.sort()
    utils.msg(irc, source, 'Available commands include: %s' % ', '.join(cmds))
    utils.msg(irc, source, 'To see help on a specific command, type \x02help <command>\x02.')
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
    if command not in world.bot_commands:
        utils.msg(irc, source, 'Error: Unknown command %r.' % command)
        return
    else:
        funcs = world.bot_commands[command]
        if len(funcs) > 1:
            utils.msg(irc, source, 'The following \x02%s\x02 plugins bind to the \x02%s\x02 command: %s'
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
                    utils.msg(irc, source, line.strip())
            else:
                utils.msg(irc, source, "Error: Command %r (from plugin %r) "
                                       "doesn't offer any help." % (command, mod))
                return

@utils.add_cmd
def showuser(irc, source, args):
    """<user>

    Shows information about <user>."""
    try:
        target = args[0]
    except IndexError:
        utils.msg(irc, source, "Error: Not enough arguments. Needs 1: nick.")
        return
    u = utils.nickToUid(irc, target) or target
    # Only show private info if the person is calling 'showuser' on themselves,
    # or is an oper.
    verbose = utils.isOper(irc, source) or u == source
    if u not in irc.users:
        utils.msg(irc, source, 'Error: Unknown user %r.' % target)
        return

    f = lambda s: utils.msg(irc, source, s)
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
