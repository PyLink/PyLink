"""
coreplugin.py - Implements core PyLink functions as a plugin.
"""

import gc
import sys
import signal
import os

import utils
import conf
import classes
from log import log
import world

def _shutdown(irc=None):
    """Shuts down the Pylink daemon."""
    for name, plugin in world.plugins.items():
        # Before closing connections, tell all plugins to shutdown cleanly first.
        if hasattr(plugin, 'die'):
            log.debug('coreplugin: Running die() on plugin %s due to shutdown.', name)
            try:
                plugin.die(irc)
            except:  # But don't allow it to crash the server.
                log.exception('coreplugin: Error occurred in die() of plugin %s, skipping...', name)

    for ircobj in world.networkobjects.values():
        # Disconnect all our networks. Disable auto-connect first by setting
        # the time to negative.
        ircobj.serverdata['autoconnect'] = -1
        ircobj.disconnect()

def sigterm_handler(_signo, _stack_frame):
    """Handles SIGTERM gracefully by shutting down the PyLink daemon."""
    log.info("Shutting down on SIGTERM.")
    _shutdown()

signal.signal(signal.SIGTERM, sigterm_handler)

def handle_kill(irc, source, command, args):
    """Handle KILLs to PyLink service bots, respawning them as needed."""
    target = args['target']

    if target == irc.pseudoclient.uid:
        irc.spawnMain()
        return

    for name, sbot in world.services.items():
        if target == sbot.uids.get(irc.name):
            spawn_service(irc, source, command, {'name': name})
            return
utils.add_hook(handle_kill, 'KILL')

def handle_kick(irc, source, command, args):
    """Handle KICKs to the PyLink service bots, rejoining channels as needed."""
    kicked = args['target']
    channel = args['channel']
    if kicked == irc.pseudoclient.uid or kicked in \
            [sbot.uids.get(irc.name) for sbot in world.services.values()]:
        irc.proto.join(kicked, channel)
utils.add_hook(handle_kick, 'KICK')

def handle_commands(irc, source, command, args):
    """Handle commands sent to the PyLink service bots (PRIVMSG)."""
    target = args['target']
    text = args['text']

    if target == irc.pseudoclient.uid and not irc.isInternalClient(source):
        irc.called_by = source
        irc.callCommand(source, text)
    else:
        for sbot in world.services.values():
            if target == sbot.uids.get(irc.name):
                sbot.call_cmd(irc, source, text)
                return

utils.add_hook(handle_commands, 'PRIVMSG')

def handle_whois(irc, source, command, args):
    """Handle WHOIS queries, for IRCds that send them across servers (charybdis, UnrealIRCd; NOT InspIRCd)."""
    target = args['target']
    user = irc.users.get(target)
    if user is None:
        log.warning('(%s) Got a WHOIS request for %r from %r, but the target '
                    'doesn\'t exist in irc.users!', irc.name, target, source)
        return
    f = irc.proto.numeric
    server = irc.getServer(target) or irc.sid
    nick = user.nick
    sourceisOper = ('o', None) in irc.users[source].modes

    # Get the full network name.
    netname = irc.serverdata.get('netname', irc.name)

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
        for prefixmode in c.getPrefixModes(target):
            modechar = irc.cmodes[prefixmode]
            chan = irc.prefixmodes[modechar] + chan

        public_chans.append(chan)

    if public_chans:  # Only send the line if the person is in any visible channels...
        f(server, 319, source, '%s :%s' % (nick, ' '.join(public_chans)))

    # 312: sends the server the target is on, and its server description.
    f(server, 312, source, "%s %s :%s" % (nick, irc.servers[server].name,
      irc.servers[server].desc))

    # 313: sends a string denoting the target's operator privilege,
    # only if they have umode +o.
    if ('o', None) in user.modes:
        # Let's be gramatically correct. (If the opertype starts with a vowel,
        # write "an Operator" instead of "a Operator")
        n = 'n' if user.opertype[0].lower() in 'aeiou' else ''

        # I want to normalize the syntax: PERSON is an OPERTYPE on NETWORKNAME.
        # This is the only syntax InspIRCd supports, but for others it doesn't
        # really matter since we're handling the WHOIS requests by ourselves.
        f(server, 313, source, "%s :is a%s %s on %s" % (nick, n, user.opertype, netname))

    # 379: RPL_WHOISMODES, used by UnrealIRCd and InspIRCd to show user modes.
    # Only show this to opers!
    if sourceisOper:
        f(server, 378, source, "%s :is connecting from %s@%s %s" % (nick, user.ident, user.realhost, user.ip))
        f(server, 379, source, '%s :is using modes %s' % (nick, irc.joinModes(user.modes)))

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
        if ('-o', None) in modes and (target == irc.pseudoclient.uid or not irc.isManipulatableClient(target)):
            irc.proto.mode(irc.sid, target, {('+o', None)})
utils.add_hook(handle_mode, 'MODE')

def handle_operup(irc, source, command, args):
    """Logs successful oper-ups on networks."""
    otype = args.get('text', 'IRC Operator')
    log.debug("(%s) Successful oper-up (opertype %r) from %s", irc.name, otype, irc.getHostmask(source))
    irc.users[source].opertype = otype

utils.add_hook(handle_operup, 'CLIENT_OPERED')

def handle_services_login(irc, source, command, args):
    """Sets services login status for users."""

    try:
        irc.users[source].services_account = args['text']
    except KeyError:  # User doesn't exist
        log.debug("(%s) Ignoring early account name setting for %s (UID hasn't been sent yet)", irc.name, source)

utils.add_hook(handle_services_login, 'CLIENT_SERVICES_LOGIN')

def handle_version(irc, source, command, args):
    """Handles requests for the PyLink server version."""
    # 351 syntax is usually "<server version>. <server hostname> :<anything else you want to add>
    fullversion = irc.version()
    irc.proto.numeric(irc.sid, 351, source, fullversion)
utils.add_hook(handle_version, 'VERSION')

def spawn_service(irc, source, command, args):
    """Handles new service bot introductions."""

    if not irc.connected.is_set():
        return

    name = args['name']
    # TODO: make this configurable?
    host = irc.serverdata["hostname"]

    # Prefer spawning service clients with umode +io, plus hideoper and
    # hidechans if supported.
    modes = []
    for mode in ('oper', 'hideoper', 'hidechans', 'invisible'):
        mode = irc.umodes.get(mode)
        if mode:
            modes.append((mode, None))

    # Track the service's UIDs on each network.
    sbot = world.services[name]
    sbot.uids[irc.name] = u = irc.proto.spawnClient(sbot.nick, sbot.ident,
        host, modes=modes, opertype="PyLink Service",
        manipulatable=sbot.manipulatable).uid

    # TODO: channels should be tracked in a central database, not hardcoded
    # in conf.
    for chan in irc.serverdata['channels']:
        irc.proto.join(u, chan)

utils.add_hook(spawn_service, 'PYLINK_NEW_SERVICE')

def handle_disconnect(irc, source, command, args):
    """Handles network disconnections."""
    for name, sbot in world.services.items():
        try:
            del sbot.uids[irc.name]
            log.debug("coreplugin: removing uids[%s] from service bot %s", irc.name, sbot.name)
        except KeyError:
            continue

utils.add_hook(handle_disconnect, 'PYLINK_DISCONNECT')

def handle_endburst(irc, source, command, args):
    """Handles network bursts."""
    if source == irc.uplink:
        log.debug('(%s): spawning service bots now.', irc.name)

        # We just connected. Burst all our registered services.
        for name, sbot in world.services.items():
            spawn_service(irc, source, command, {'name': name})

utils.add_hook(handle_endburst, 'ENDBURST')

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
                 irc.name, username, irc.getHostmask(source))
    else:
        irc.msg(source, 'Error: Incorrect credentials.')
        u = irc.users[source]
        log.warning("(%s) Failed login to %r from %s",
                    irc.name, username, irc.getHostmask(source))

@utils.add_cmd
def shutdown(irc, source, args):
    """takes no arguments.

    Exits PyLink by disconnecting all networks."""
    irc.checkAuthenticated(source, allowOper=False)
    u = irc.users[source]

    log.info('(%s) SHUTDOWN requested by "%s!%s@%s", exiting...', irc.name, u.nick,
             u.ident, u.host)

    _shutdown(irc)

def load(irc, source, args):
    """<plugin name>.

    Loads a plugin from the plugin folder."""
    irc.checkAuthenticated(source, allowOper=False)
    try:
        name = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: plugin name.")
        return
    if name in world.plugins:
        irc.reply("Error: %r is already loaded." % name)
        return
    log.info('(%s) Loading plugin %r for %s', irc.name, name, irc.getHostmask(source))
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
    irc.checkAuthenticated(source, allowOper=False)
    try:
        name = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: plugin name.")
        return
    if name in world.plugins:
        log.info('(%s) Unloading plugin %r for %s', irc.name, name, irc.getHostmask(source))
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

def _rehash():
    """Rehashes the PyLink daemon."""
    old_conf = conf.conf.copy()
    fname = conf.fname
    new_conf = conf.loadConf(fname, errors_fatal=False)
    new_conf = conf.validateConf(new_conf)
    conf.conf = new_conf
    for network, ircobj in world.networkobjects.copy().items():
        # Server was removed from the config file, disconnect them.
        log.debug('rehash: checking if %r is in new conf still.', network)
        if network not in new_conf['servers']:
            log.debug('rehash: removing connection to %r (removed from config).', network)
            # Disable autoconnect first.
            ircobj.serverdata['autoconnect'] = -1
            ircobj.disconnect()
            del world.networkobjects[network]
        else:
            ircobj.conf = new_conf
            ircobj.serverdata = new_conf['servers'][network]
            ircobj.botdata = new_conf['bot']

            # Clear the IRC object's channel loggers and replace them with
            # new ones by re-running logSetup().
            while ircobj.loghandlers:
                log.removeHandler(ircobj.loghandlers.pop())

            ircobj.logSetup()

            # TODO: update file loggers here too.

    for network, sdata in new_conf['servers'].items():
        # New server was added. Connect them if not already connected.
        if network not in world.networkobjects:
            proto = utils.getProtocolModule(sdata['protocol'])
            world.networkobjects[network] = classes.Irc(network, proto, new_conf)

if os.name == 'posix':
    # Only register SIGHUP on *nix.
    def sighup_handler(_signo, _stack_frame):
        """Handles SIGHUP by rehashing the PyLink daemon."""
        log.info("SIGHUP received, reloading config.")
        _rehash()

    signal.signal(signal.SIGHUP, sighup_handler)

@utils.add_cmd
def rehash(irc, source, args):
    """takes no arguments.

    Reloads the configuration file for PyLink, (dis)connecting added/removed networks.
    Plugins must be manually reloaded."""
    irc.checkAuthenticated(source, allowOper=False)
    try:
        _rehash()
    except Exception as e:  # Something went wrong, abort.
        log.exception("Error REHASHing config: ")
        irc.reply("Error loading configuration file: %s: %s" % (type(e).__name__, e))
        return
    else:
        irc.reply("Done.")

