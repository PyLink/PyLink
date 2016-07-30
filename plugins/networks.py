"""Networks plugin - allows you to manipulate connections to various configured networks."""
import importlib

from pylinkirc import utils, world, conf, classes
from pylinkirc.log import log
from pylinkirc.coremods import control

@utils.add_cmd
def disconnect(irc, source, args):
    """<network>

    Disconnects the network <network>. When all networks are disconnected, PyLink will automatically exit.
    Note: This does not affect the autoreconnect settings of any network, so the network will likely just reconnect unless autoconnect is disabled (see the 'autoconnect' command)."""
    irc.checkAuthenticated(source, allowOper=False)
    try:
        netname = args[0]
        network = world.networkobjects[netname]
    except IndexError:  # No argument given.
        irc.reply('Error: Not enough arguments (needs 1: network name (case sensitive)).')
        return
    except KeyError:  # Unknown network.
        irc.reply('Error: No such network "%s" (case sensitive).' % netname)
        return
    irc.reply("Done. If you want to reconnect this network, use the 'rehash' command.")

    control.remove_network(network)

@utils.add_cmd
def autoconnect(irc, source, args):
    """<network> <seconds>

    Sets the autoconnect time for <network> to <seconds>.
    You can disable autoconnect for a network by setting <seconds> to a negative value."""
    irc.checkAuthenticated(source)
    try:
        netname = args[0]
        seconds = float(args[1])
        network = world.networkobjects[netname]
    except IndexError:  # Arguments not given.
        irc.reply('Error: Not enough arguments (needs 2: network name (case sensitive), autoconnect time (in seconds)).')
        return
    except KeyError:  # Unknown network.
        irc.reply('Error: No such network "%s" (case sensitive).' % netname)
        return
    except ValueError:
        irc.reply('Error: Invalid argument "%s" for <seconds>.' % seconds)
        return
    network.serverdata['autoconnect'] = seconds
    irc.reply("Done.")

@utils.add_cmd
def remote(irc, source, args):
    """<network> <command>

    Runs <command> on the remote network <network>. No replies are sent back due to protocol limitations."""
    irc.checkAuthenticated(source, allowOper=False)

    try:
        netname = args[0]
        cmd_args = ' '.join(args[1:]).strip()
        remoteirc = world.networkobjects[netname]
    except IndexError:  # Arguments not given.
        irc.reply('Error: Not enough arguments (needs 2 or more: network name (case sensitive), command name & arguments).')
        return
    except KeyError:  # Unknown network.
        irc.reply('Error: No such network "%s" (case sensitive).' % netname)
        return

    if not cmd_args:
        irc.reply('No text entered!')
        return

    # Force remoteirc.called_in to something private in order to prevent
    # accidental information leakage from replies.
    remoteirc.called_in = remoteirc.called_by = remoteirc.pseudoclient.uid

    # Set PyLink's identification to admin.
    remoteirc.pseudoclient.account = "<PyLink networks.remote override>"

    try:  # Remotely call the command (use the PyLink client as a dummy user).
        remoteirc.callCommand(remoteirc.pseudoclient.uid, cmd_args)
    finally:  # Remove the identification override after we finish.
        remoteirc.pseudoclient.account = ''

    irc.reply("Done.")

@utils.add_cmd
def reloadproto(irc, source, args):
    """<protocol module name>

    Reloads the given protocol module without restart. You will have to manually disconnect and reconnect any network using the module for changes to apply."""
    irc.checkAuthenticated(source)
    try:
        name = args[0]
    except IndexError:
        irc.reply('Error: Not enough arguments (needs 1: protocol module name)')
        return

    proto = utils.getProtocolModule(name)
    importlib.reload(proto)

    irc.reply("Done. You will have to manually disconnect and reconnect any network using the %r module for changes to apply." % name)
