"""
coreplugin.py - Implements core PyLink functions as a plugin.
"""

import gc
import sys

import utils
from log import log
import world

def handle_kill(irc, source, command, args):
    """Handle KILLs to the main PyLink client, respawning it as needed."""
    if args['target'] == irc.pseudoclient.uid:
        irc.spawnMain()
utils.add_hook(handle_kill, 'KILL')

def handle_kick(irc, source, command, args):
    """Handle KICKs to the main PyLink client, rejoining channels as needed."""
    kicked = args['target']
    channel = args['channel']
    if kicked == irc.pseudoclient.uid:
        irc.proto.joinClient(irc.pseudoclient.uid, channel)
utils.add_hook(handle_kick, 'KICK')

def handle_commands(irc, source, command, args):
    """Handle commands sent to the PyLink client (PRIVMSG)."""
    if args['target'] == irc.pseudoclient.uid and not irc.isInternalClient(source):
        irc.called_by = source
        irc.callCommand(source, args['text'])

utils.add_hook(handle_commands, 'PRIVMSG')

def handle_whois(irc, source, command, args):
    """Handle WHOIS queries, for IRCds that send them across servers (charybdis, UnrealIRCd; NOT InspIRCd)."""
    target = args['target']
    user = irc.users.get(target)
    if user is None:
        log.warning('(%s) Got a WHOIS request for %r from %r, but the target '
                    'doesn\'t exist in irc.users!', irc.name, target, source)
        return
    f = irc.proto.numericServer
    server = irc.getServer(target) or irc.sid
    nick = user.nick
    sourceisOper = ('o', None) in irc.users[source].modes
    # https://www.alien.net.au/irc/irc2numerics.html

    # 311: sends nick!user@host information
    f(server, 311, source, "%s %s %s * :%s" % (nick, user.ident, user.host, user.realname))

    # 319: RPL_WHOISCHANNELS, shows public channel list of target
    public_chans = []
    for chan in user.channels:
        c = irc.channels[chan]
        # Here, we'll want to hide secret/private channels from non-opers
        # who are not in them.

        if ((irc.cmodes.get('secret'), None) in c.modes or \
            (irc.cmodes.get('private'), None) in c.modes) \
            and not (sourceisOper or source in c.users):
                continue
        # Show prefix modes like a regular IRCd does.
        for prefixmode, prefixchar in irc.prefixmodes.items():
            modename = [mname for mname, char in irc.cmodes.items() if char == prefixmode]
            if modename and target in c.prefixmodes[modename[0]+'s']:
                chan = prefixchar + chan
        public_chans.append(chan)
    if public_chans:  # Only send the line if the person is in any visible channels...
        f(server, 319, source, '%s :%s' % (nick, ' '.join(public_chans)))

    # 312: sends the server the target is on, and its server description.
    f(server, 312, source, "%s %s :%s" % (nick, irc.servers[server].name,
      irc.servers[server].desc))

    # 313: sends a string denoting the target's operator privilege,
    # only if they have umode +o.
    if ('o', None) in user.modes:
        if hasattr(user, 'opertype'):
            opertype = user.opertype
        else:  # If the IRCd OPERTYPE doesn't exist, just write "IRC Operator"
            opertype = "IRC Operator"

        # Let's be gramatically correct. (If the opertype starts with a vowel,
        # write "an Operator" instead of "a Operator")
        n = 'n' if opertype[0].lower() in 'aeiou' else ''

        f(server, 313, source, "%s :is a%s %s" % (nick, n, opertype))

    # 379: RPL_WHOISMODES, used by UnrealIRCd and InspIRCd to show user modes.
    # Only show this to opers!
    if sourceisOper:
        f(server, 378, source, "%s :is connecting from %s@%s %s" % (nick, user.ident, user.realhost, user.ip))
        f(server, 379, source, '%s :is using modes %s' % (nick, utils.joinModes(user.modes)))

    # 301: used to show away information if present
    away_text = user.away
    log.debug('(%s) coreplugin/handle_whois: away_text for %s is %r', irc.name, target, away_text)
    if away_text:
        f(server, 301, source, '%s :%s' % (nick, away_text))

    # 317: shows idle and signon time. However, we don't track the user's real
    # idle time, so we simply return 0.
    # <- 317 GL GL 15 1437632859 :seconds idle, signon time
    f(server, 317, source, "%s 0 %s :seconds idle, signon time" % (nick, user.ts))

    for func in world.whois_handlers:
    # Iterate over custom plugin WHOIS handlers. They return a tuple
    # or list with two arguments: the numeric, and the text to send.
        try:
            res = func(irc, target)
            if res:
                num, text = res
                f(server, num, source, text)
        except Exception as e:
            # Again, we wouldn't want this to crash our service, in case
            # something goes wrong!
            log.exception('(%s) Error caught in WHOIS handler: %s', irc.name, e)
    # 318: End of WHOIS.
    f(server, 318, source, "%s :End of /WHOIS list" % nick)
utils.add_hook(handle_whois, 'WHOIS')

def handle_mode(irc, source, command, args):
    """Protect against forced deoper attempts."""
    target = args['target']
    modes = args['modes']
    # If the sender is not a PyLink client, and the target IS a protected
    # client, revert any forced deoper attempts.
    if irc.isInternalClient(target) and not irc.isInternalClient(source):
        if ('-o', None) in modes and (target == irc.pseudoclient.uid or not utils.isManipulatableClient(irc, target)):
            irc.proto.modeServer(irc.sid, target, {('+o', None)})
utils.add_hook(handle_mode, 'MODE')

def handle_operup(irc, source, command, args):
    """Logs successful oper-ups on networks."""
    log.info("(%s) Successful oper-up (opertype %r) from %s", irc.name, args.get('text'), utils.getHostmask(irc, source))
utils.add_hook(handle_operup, 'CLIENT_OPERED')

# Essential, core commands go here so that the "commands" plugin with less-important,
# but still generic functions can be reloaded.

@utils.add_cmd
def identify(irc, source, args):
    """<username> <password>

    Logs in to PyLink using the configured administrator account."""
    if utils.isChannel(irc.called_by):
        irc.reply('Error: This command must be sent in private. '
                '(Would you really type a password inside a channel?)')
        return
    try:
        username, password = args[0], args[1]
    except IndexError:
        irc.msg(source, 'Error: Not enough arguments.')
        return
    # Usernames are case-insensitive, passwords are NOT.
    if username.lower() == irc.conf['login']['user'].lower() and password == irc.conf['login']['password']:
        realuser = irc.conf['login']['user']
        irc.users[source].identified = realuser
        irc.msg(source, 'Successfully logged in as %s.' % realuser)
        log.info("(%s) Successful login to %r by %s",
                 irc.name, username, utils.getHostmask(irc, source))
    else:
        irc.msg(source, 'Error: Incorrect credentials.')
        u = irc.users[source]
        log.warning("(%s) Failed login to %r from %s",
                    irc.name, username, utils.getHostmask(irc, source))

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

def load(irc, source, args):
    """<plugin name>.

    Loads a plugin from the plugin folder."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        name = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: plugin name.")
        return
    if name in world.plugins:
        irc.reply("Error: %r is already loaded." % name)
        return
    log.info('(%s) Loading plugin %r for %s', irc.name, name, utils.getHostmask(irc, source))
    try:
        world.plugins[name] = pl = utils.loadModuleFromFolder(name, world.plugins_folder)
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
    irc.reply("Loaded plugin %r." % name)
utils.add_cmd(load)

def unload(irc, source, args):
    """<plugin name>.

    Unloads a currently loaded plugin."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        name = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: plugin name.")
        return
    if name in world.plugins:
        log.info('(%s) Unloading plugin %r for %s', irc.name, name, utils.getHostmask(irc, source))
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

        irc.reply("Unloaded plugin %r." % name)
        return True  # We succeeded, make it clear (this status is used by reload() below)
    else:
        irc.reply("Unknown plugin %r." % name)
utils.add_cmd(unload)

@utils.add_cmd
def reload(irc, source, args):
    """<plugin name>.

    Loads a plugin from the plugin folder."""
    try:
        name = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: plugin name.")
        return
    if unload(irc, source, args):
        load(irc, source, args)

def main(irc=None):
    # This is a global sanity check, to make sure the protocol module is doing
    # its job.
    if irc and not irc.connected.wait(2):
        log.warning('(%s) IRC network %s (protocol %s) has not set '
                    'irc.connected state after 2 seconds - this may be a bug '
                    'in the protocol module, and will cause plugins like '
                    'relay to not work correctly!', irc.name, irc.name,
                    irc.protoname)
