"""Networks plugin - allows you to manipulate connections to various configured networks."""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading

import conf
import utils
import world
from log import log

@utils.add_cmd
def disconnect(irc, source, args):
    """<network>

    Disconnects the network <network>. When all networks are disconnected, PyLink will automatically exit.
    Note: This does not affect the autoreconnect settings of any network, so the network will likely just reconnect unless autoconnect is disabled (see the 'autoconnect' command)."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        netname = args[0]
        network = world.networkobjects[netname]
    except IndexError:  # No argument given.
        utils.msg(irc, source, 'Error: Not enough arguments (needs 1: network name (case sensitive)).')
        return
    except KeyError:  # Unknown network.
        utils.msg(irc, source, 'Error: No such network "%s" (case sensitive).' % netname)
        return
    utils.msg(irc, source, "Done.")
    # Abort the connection! Simple as that.
    network.aborted.set()

@utils.add_cmd
def connect(irc, source, args):
    """<network>

    Initiates a connection to the network <network>."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        netname = args[0]
        network = world.networkobjects[netname]
    except IndexError:  # No argument given.
        utils.msg(irc, source, 'Error: Not enough arguments (needs 1: network name (case sensitive)).')
        return
    except KeyError:  # Unknown network.
        utils.msg(irc, source, 'Error: No such network "%s" (case sensitive).' % netname)
        return
    if network.connection_thread.is_alive():
        utils.msg(irc, source, 'Error: Network "%s" seems to be already connected.' % netname)
    else:  # Reconnect the network!
        network.initVars()
        network.connection_thread = threading.Thread(target=network.connect)
        network.connection_thread.start()
        utils.msg(irc, source, "Done.")

@utils.add_cmd
def autoconnect(irc, source, args):
    """<network> <seconds>

    Sets the autoconnect time for <network> to <seconds>.
    You can disable autoconnect for a network by setting <seconds> to a negative value."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        netname = args[0]
        seconds = float(args[1])
        network = world.networkobjects[netname]
    except IndexError:  # Arguments not given.
        utils.msg(irc, source, 'Error: Not enough arguments (needs 2: network name (case sensitive), autoconnect time (in seconds)).')
        return
    except KeyError:  # Unknown network.
        utils.msg(irc, source, 'Error: No such network "%s" (case sensitive).' % netname)
        return
    except ValueError:
        utils.msg(irc, source, 'Error: Invalid argument "%s" for <seconds>.' % seconds)
        return
    network.serverdata['autoconnect'] = seconds
    utils.msg(irc, source, "Done.")
