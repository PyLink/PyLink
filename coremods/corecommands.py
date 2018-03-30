"""
corecommands.py - Implements core PyLink commands.
"""

import gc
import sys
import importlib

from . import control, login, permissions
from pylinkirc import utils, world, conf
from pylinkirc.log import log

# Essential, core commands go here so that the "commands" plugin with less-important,
# but still generic functions can be reloaded.

def _login(irc, source, username):
    """Internal function to process logins."""
    # Mangle case before we start checking for login data.
    accounts = {k.lower(): v for k, v in conf.conf['login'].get('accounts', {}).items()}

    logindata = accounts.get(username.lower(), {})
    network_filter = logindata.get('networks')
    require_oper = logindata.get('require_oper', False)
    hosts_filter = logindata.get('hosts', [])

    if network_filter and irc.name not in network_filter:
        irc.error("You are not authorized to log in to %r on this network." % username)
        log.warning("(%s) Failed login to %r from %s (wrong network: networks filter says %r but we got %r)", irc.name, username, irc.getHostmask(source), ', '.join(network_filter), irc.name)
        return

    elif require_oper and not irc.isOper(source, allowAuthed=False):
        irc.error("You must be opered to log in to %r." % username)
        log.warning("(%s) Failed login to %r from %s (needs oper)", irc.name, username, irc.getHostmask(source))
        return

    elif hosts_filter and not any(irc.matchHost(host, source) for host in hosts_filter):
        irc.error("Failed to log in to %r: hostname mismatch." % username)
        log.warning("(%s) Failed login to %r from %s (hostname mismatch)", irc.name, username, irc.getHostmask(source))
        return

    irc.users[source].account = username
    irc.reply('Successfully logged in as %s.' % username)
    log.info("(%s) Successful login to %r by %s",
             irc.name, username, irc.getHostmask(source))

def _loginfail(irc, source, username):
    """Internal function to process login failures."""
    irc.error('Incorrect credentials.')
    log.warning("(%s) Failed login to %r from %s", irc.name, username, irc.getHostmask(source))

@utils.add_cmd
def identify(irc, source, args):
    """<username> <password>

    Logs in to PyLink using the configured administrator account."""
    if utils.isChannel(irc.called_in):
        irc.reply('Error: This command must be sent in private. '
                '(Would you really type a password inside a channel?)')
        return
    try:
        username, password = args[0], args[1]
    except IndexError:
        irc.reply('Error: Not enough arguments.')
        return

    # Process new-style accounts.
    if login.checkLogin(username, password):
        _login(irc, source, username)
        return

    # Process legacy logins (login:user).
    if username.lower() == conf.conf['login'].get('user', '').lower() and password == conf.conf['login'].get('password'):
        realuser = conf.conf['login']['user']
        _login(irc, source, realuser)
    else:
        # Username not found.
        _loginfail(irc, source, username)


@utils.add_cmd
def shutdown(irc, source, args):
    """takes no arguments.

    Exits PyLink by disconnecting all networks."""

    permissions.checkPermissions(irc, source, ['core.shutdown'])

    u = irc.users[source]

    log.info('(%s) SHUTDOWN requested by "%s!%s@%s", exiting...', irc.name, u.nick,
             u.ident, u.host)

    control._shutdown(irc)

@utils.add_cmd
def load(irc, source, args):
    """<plugin name>.

    Loads a plugin from the plugin folder."""
    # Note: reload capability is acceptable here, because all it actually does is call
    # load after unload.
    permissions.checkPermissions(irc, source, ['core.load', 'core.reload'])

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
        world.plugins[name] = pl = utils.loadPlugin(name)
    except ImportError as e:
        if str(e) == ('No module named %r' % name):
            log.exception('Failed to load plugin %r: The plugin could not be found.', name)
        else:
            log.exception('Failed to load plugin %r: ImportError.', name)
        raise
    else:
        if hasattr(pl, 'main'):
            log.debug('Calling main() function of plugin %r', pl)
            pl.main(irc=irc)
    irc.reply("Loaded plugin %r." % name)

@utils.add_cmd
def unload(irc, source, args):
    """<plugin name>.

    Unloads a currently loaded plugin."""
    permissions.checkPermissions(irc, source, ['core.unload', 'core.reload'])

    try:
        name = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: plugin name.")
        return

    # Since we're using absolute imports in 0.9.x+, the module name differs from the actual plugin
    # name.
    modulename = utils.PLUGIN_PREFIX + name

    if name in world.plugins:
        log.info('(%s) Unloading plugin %r for %s', irc.name, name, irc.getHostmask(source))
        pl = world.plugins[name]
        log.debug('sys.getrefcount of plugin %s is %s', pl, sys.getrefcount(pl))

        # Remove any command functions defined by the plugin.
        for cmdname, cmdfuncs in world.services['pylink'].commands.copy().items():
            log.debug('cmdname=%s, cmdfuncs=%s', cmdname, cmdfuncs)

            for cmdfunc in cmdfuncs:
                log.debug('__module__ of cmdfunc %s is %s', cmdfunc, cmdfunc.__module__)
                if cmdfunc.__module__ == modulename:
                    log.debug("Removing %s from world.services['pylink'].commands[%s]", cmdfunc, cmdname)
                    world.services['pylink'].commands[cmdname].remove(cmdfunc)

                    # If the cmdfunc list is empty, remove it.
                    if not cmdfuncs:
                        log.debug("Removing world.services['pylink'].commands[%s] (it's empty now)", cmdname)
                        del world.services['pylink'].commands[cmdname]

        # Remove any command hooks set by the plugin.
        for hookname, hookfuncs in world.hooks.copy().items():
            for hookfunc in hookfuncs:
                if hookfunc.__module__ == modulename:
                    world.hooks[hookname].remove(hookfunc)
                    # If the hookfuncs list is empty, remove it.
                    if not hookfuncs:
                        del world.hooks[hookname]

        # Call the die() function in the plugin, if present.
        if hasattr(pl, 'die'):
            try:
                pl.die(irc=irc)
            except:  # But don't allow it to crash the server.
                log.exception('(%s) Error occurred in die() of plugin %s, skipping...', irc.name, pl)

        # Delete it from memory (hopefully).
        del world.plugins[name]
        for n in (name, modulename):
            if n in sys.modules:
                del sys.modules[n]
            if n in globals():
                del globals()[n]

        # Garbage collect.
        gc.collect()

        irc.reply("Unloaded plugin %r." % name)
        return True  # We succeeded, make it clear (this status is used by reload() below)
    else:
        irc.reply("Unknown plugin %r." % name)

@utils.add_cmd
def reload(irc, source, args):
    """<plugin name>.

    Loads a plugin from the plugin folder."""
    try:
        name = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: plugin name.")
        return

    # Note: these functions do permission checks, so there are none needed here.
    if unload(irc, source, args):
        load(irc, source, args)

@utils.add_cmd
def rehash(irc, source, args):
    """takes no arguments.

    Reloads the configuration file for PyLink, (dis)connecting added/removed networks.

    Note: plugins must be manually reloaded."""
    permissions.checkPermissions(irc, source, ['core.rehash'])
    try:
        control._rehash()
    except Exception as e:  # Something went wrong, abort.
        log.exception("Error REHASHing config: ")
        irc.reply("Error loading configuration file: %s: %s" % (type(e).__name__, e))
        return
    else:
        irc.reply("Done.")

@utils.add_cmd
def clearqueue(irc, source, args):
    """takes no arguments.

    Clears the outgoing text queue for the current connection."""
    permissions.checkPermissions(irc, source, ['core.clearqueue'])
    irc.queue.queue.clear()
