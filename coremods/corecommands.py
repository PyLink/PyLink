"""
corecommands.py - Implements core PyLink commands.
"""

import gc
import sys

from pylinkirc import utils, world
from pylinkirc.log import log

from . import control, permissions

__all__ = []

# Essential, core commands go here so that the "commands" plugin with less-important,
# but still generic functions can be reloaded.

@utils.add_cmd
def shutdown(irc, source, args):
    """takes no arguments.

    Exits PyLink by disconnecting all networks."""
    permissions.check_permissions(irc, source, ['core.shutdown'])
    log.info('(%s) SHUTDOWN requested by %s, exiting...', irc.name, irc.get_hostmask(source))
    control.shutdown(irc=irc)

@utils.add_cmd
def load(irc, source, args):
    """<plugin name>.

    Loads a plugin from the plugin folder."""
    # Note: reload capability is acceptable here, because all it actually does is call
    # load after unload.
    permissions.check_permissions(irc, source, ['core.load', 'core.reload'])

    try:
        name = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: plugin name.")
        return
    if name in world.plugins:
        irc.reply("Error: %r is already loaded." % name)
        return
    log.info('(%s) Loading plugin %r for %s', irc.name, name, irc.get_hostmask(source))
    try:
        world.plugins[name] = pl = utils._load_plugin(name)
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
    permissions.check_permissions(irc, source, ['core.unload', 'core.reload'])

    try:
        name = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1: plugin name.")
        return

    # Since we're using absolute imports in 0.9.x+, the module name differs from the actual plugin
    # name.
    modulename = utils.PLUGIN_PREFIX + name

    if name in world.plugins:
        log.info('(%s) Unloading plugin %r for %s', irc.name, name, irc.get_hostmask(source))
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
        for hookname, hookpairs in world.hooks.copy().items():
            for hookpair in hookpairs:
                hookfunc = hookpair[1]
                if hookfunc.__module__ == modulename:
                    log.debug('Trying to remove hook func %s (%s) from plugin %s', hookfunc, hookname, modulename)
                    world.hooks[hookname].remove(hookpair)
                    # If the hookfuncs list is empty, remove it.
                    if not hookpairs:
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
    permissions.check_permissions(irc, source, ['core.rehash'])
    try:
        control.rehash()
    except Exception as e:  # Something went wrong, abort.
        irc.reply("Error loading configuration file: %s: %s" % (type(e).__name__, e))
        return
    else:
        irc.reply("Done.")

@utils.add_cmd
def clearqueue(irc, source, args):
    """takes no arguments.

    Clears the outgoing text queue for the current connection."""
    permissions.check_permissions(irc, source, ['core.clearqueue'])
    irc._queue.queue.clear()
