# commands.py: base PyLink commands
import sys
import os
from time import ctime
import itertools
import gc

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
        irc.msg(irc.called_by, 'You are identified as \x02%s\x02.' % identified)
    else:
        irc.msg(irc.called_by, 'You are not identified as anyone.')
    irc.msg(irc.called_by, 'Operator access: \x02%s\x02' % bool(utils.isOper(irc, source)))

@utils.add_cmd
def identify(irc, source, args):
    """<username> <password>

    Logs in to PyLink using the configured administrator account."""
    if utils.isChannel(irc.called_by):
        irc.msg(irc.called_by, 'Error: This command must be sent in private. '
                '(Would you really type a password inside a public channel?)')
    try:
        username, password = args[0], args[1]
    except IndexError:
        irc.msg(source, 'Error: Not enough arguments.')
        return
    # Usernames are case-insensitive, passwords are NOT.
    if username.lower() == conf['login']['user'].lower() and password == conf['login']['password']:
        realuser = conf['login']['user']
        irc.users[source].identified = realuser
        irc.msg(source, 'Successfully logged in as %s.' % realuser)
        log.info("(%s) Successful login to %r by %s.",
                 irc.name, username, utils.getHostmask(irc, source))
    else:
        irc.msg(source, 'Error: Incorrect credentials.')
        u = irc.users[source]
        log.warning("(%s) Failed login to %r from %s.",
                    irc.name, username, utils.getHostmask(irc, source))

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
def shutdown(irc, source, args):
    """takes no arguments.

    Exits PyLink by disconnecting all networks."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    u = irc.users[source]
    log.info('(%s) SHUTDOWN requested by "%s!%s@%s", exiting...', irc.name, u.nick,
             u.ident, u.host)
    for ircobj in world.networkobjects.values():
        # Disable auto-connect first by setting the time to negative.
        ircobj.serverdata['autoconnect'] = -1
        ircobj.aborted.set()

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

def load(irc, source, args):
    """<plugin name>.

    Loads a plugin from the plugin folder."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        name = args[0]
    except IndexError:
        irc.msg(irc.called_by, "Error: Not enough arguments. Needs 1: plugin name.")
        return
    if name in world.plugins:
        irc.msg(irc.called_by, "Error: %r is already loaded." % name)
        return
    try:
        world.plugins[name] = pl = __import__(name)
    except ImportError as e:
        if str(e) == ('No module named %r' % name):
            log.exception('Failed to load plugin %r: The plugin could not be found.', name)
        else:
            log.exception('Failed to load plugin %r: ImportError.', name)
        raise
    else:
        if hasattr(pl, 'main'):
            log.debug('Calling main() function of plugin %r', pl)
            pl.main(irc)
    irc.msg(irc.called_by, "Loaded plugin %r." % name)
utils.add_cmd(load)

def unload(irc, source, args):
    """<plugin name>.

    Unloads a currently loaded plugin."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        name = args[0]
    except IndexError:
        irc.msg(irc.called_by, "Error: Not enough arguments. Needs 1: plugin name.")
        return
    if name == 'commands':
        irc.msg(irc.called_by, "Error: Cannot unload the commands plugin!")
        return
    elif name in world.plugins:
        pl = world.plugins[name]
        log.debug('sys.getrefcount of plugin %s is %s', pl, sys.getrefcount(pl))
        # Remove any command functions set by the plugin.
        for cmdname, cmdfuncs in world.commands.copy().items():
            log.debug('cmdname=%s, cmdfuncs=%s', cmdname, cmdfuncs)
            for cmdfunc in cmdfuncs:
                log.debug('__module__ of cmdfunc %s is %s', cmdfunc, cmdfunc.__module__)
                if cmdfunc.__module__ == name:
                    log.debug('Removing %s from world.commands[%s]', cmdfunc, cmdname)
                    world.commands[cmdname].remove(cmdfunc)
                    # If the cmdfunc list is empty, remove it.
                    if not cmdfuncs:
                        log.debug("Removing world.commands[%s] (it's empty now)", cmdname)
                        del world.commands[cmdname]

        # Remove any command hooks set by the plugin.
        for hookname, hookfuncs in world.hooks.copy().items():
            for hookfunc in hookfuncs:
                if hookfunc.__module__ == name:
                    world.hooks[hookname].remove(hookfunc)
                    # If the hookfuncs list is empty, remove it.
                    if not hookfuncs:
                        del world.hooks[hookname]

        # Remove whois handlers too.
        for f in world.whois_handlers:
            if f.__module__ == name:
                world.whois_handlers.remove(f)

        # Call the die() function in the plugin, if present.
        if hasattr(pl, 'die'):
            try:
                pl.die(irc)
            except:  # But don't allow it to crash the server.
                log.exception('(%s) Error occurred in die() of plugin %s, skipping...', irc.name, pl)

        # Delete it from memory (hopefully).
        del world.plugins[name]
        if name in sys.modules:
            del sys.modules[name]
        if name in globals():
            del globals()[name]

        # Garbage collect.
        gc.collect()

        irc.msg(irc.called_by, "Unloaded plugin %r." % name)
        return True  # We succeeded, make it clear (this status is used by reload() below)
    else:
        irc.msg(irc.called_by, "Unknown plugin %r." % name)
utils.add_cmd(unload)

@utils.add_cmd
def reload(irc, source, args):
    """<plugin name>.

    Loads a plugin from the plugin folder."""
    try:
        name = args[0]
    except IndexError:
        irc.msg(irc.called_by, "Error: Not enough arguments. Needs 1: plugin name.")
        return
    if unload(irc, source, args):
        load(irc, source, args)
