"""
opercmds.py: Provides a subset of network management commands.
"""

import sys
import os
# Add the base PyLink folder to path, so we can import utils and log.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
from log import log

@utils.add_cmd
def mode(irc, source, args):
    """<channel> <modes>

    Oper-only, sets modes <modes> on the target channel."""

    # Check that the caller is either opered or logged in as admin.
    utils.checkAuthenticated(irc, source)

    try:
        target, modes = args[0], args[1:]
    except IndexError:
        irc.reply('Error: Not enough arguments. Needs 2: target, modes to set.')
        return

    if target not in irc.channels:
        irc.reply("Error: Unknown channel '%s'." % target)
        return
    elif not modes:
        # No modes were given before parsing (i.e. mode list was blank).
        irc.reply("Error: No valid modes were given.")
        return

    parsedmodes = utils.parseModes(irc, target, modes)

    if not parsedmodes:
        # Modes were given but they failed to parse into anything meaningful.
        # For example, "mode #somechan +o" would be erroneous because +o
        # requires an argument!
        irc.reply("Error: No valid modes were given.")
        return

    irc.proto.modeClient(irc.pseudoclient.uid, target, parsedmodes)

    # Call the appropriate hooks for plugins like relay.
    irc.callHooks([irc.pseudoclient.uid, 'OPERCMDS_MODEOVERRIDE',
                   {'target': target, 'modes': parsedmodes, 'parse_as': 'MODE'}])

    irc.reply("Done.")

@utils.add_cmd
def jupe(irc, source, args):
    """<server> [<reason>]

    Oper-only, jupes the given server."""

    # Check that the caller is either opered or logged in as admin.
    utils.checkAuthenticated(irc, source)

    try:
        servername = args[0]
        reason = ' '.join(args[1:]) or "No reason given"
        desc = "Juped by %s: [%s]" % (utils.getHostmask(irc, source), reason)
    except IndexError:
        irc.reply('Error: Not enough arguments. Needs 1-2: servername, reason (optional).')
        return

    if not utils.isServerName(servername):
        irc.reply("Error: Invalid server name '%s'." % servername)
        return

    sid = irc.proto.spawnServer(servername, desc=desc)

    irc.callHooks([irc.pseudoclient.uid, 'OPERCMDS_SPAWNSERVER',
                   {'name': servername, 'sid': sid, 'text': desc}])

    irc.reply("Done.")
