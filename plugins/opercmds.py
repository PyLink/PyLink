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


@utils.add_cmd
def kick(irc, source, args):
    """<source> <channel> <user> [<reason>]

    Admin only. Kicks <user> from <channel> via <source>, where <source> is either the nick of a PyLink client or the SID of a PyLink server."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        sourcenick = args[0]
        channel = args[1]
        target = args[2]
        reason = ' '.join(args[3:])
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 3-4: source nick, channel, target, reason (optional).")
        return

    # Convert the source and target nicks to UIDs.
    u = irc.nickToUid(sourcenick) or sourcenick
    targetu = irc.nickToUid(target)

    if channel not in irc.channels:  # KICK only works on channels that exist.
        irc.reply("Error: Unknown channel %r." % channel)
        return

    if irc.isInternalServer(u):
        # Send kick from server if the given kicker is a SID
        irc.proto.kickServer(u, channel, targetu, reason)
    elif u not in irc.users:
        # Whatever we were told to send the kick from wasn't valid; try to be
        # somewhat user friendly in the error. message
        irc.reply("Error: No such PyLink client '%s'. The first argument to "
                  "KICK should be the name of a PyLink client (e.g. '%s'; see "
                  "'help kick' for details." % (sourcenick,
                  irc.pseudoclient.nick))
        return
    elif targetu not in irc.users:
        # Whatever we were told to kick doesn't exist!
        irc.reply("Error: No such nick '%s'." % target)
        return
    else:
        irc.proto.kickClient(u, channel, targetu, reason)

    irc.callHooks([u, 'CHANCMDS_KICK', {'channel': channel, 'target': targetu,
                                        'text': reason, 'parse_as': 'KICK'}])

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
def topic(irc, source, args):
    """<channel> <topic>

    Admin only. Updates the topic in a channel."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        channel = args[0]
        topic = ' '.join(args[1:])
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 2: channel, topic.")
        return

    if channel not in irc.channels:
        irc.reply("Error: Unknown channel %r." % channel)
        return

    irc.proto.topicClient(irc.pseudoclient.uid, channel, topic)

    irc.callHooks([irc.pseudoclient.uid, 'CHANCMDS_TOPIC',
                   {'channel': channel, 'text': topic, 'setter': source,
                    'parse_as': 'TOPIC'}])
