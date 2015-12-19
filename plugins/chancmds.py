"""
chancmds.py: Provides a subset of channel management commands.
"""

import sys
import os
# Add the base PyLink folder to path, so we can import utils and log.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
from log import log

@utils.add_cmd
def kick(irc, source, args):
    """<source> <channel> <user> [<reason>]

    Oper only. Kicks <user> from <channel> via <source>, where <source> is either the nick of a PyLink client or the SID of a PyLink server."""
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
    u = utils.nickToUid(irc, sourcenick) or sourcenick
    targetu = utils.nickToUid(irc, target)

    if channel not in irc.channels:  # KICK only works on channels that exist.
        irc.reply("Error: Unknown channel %r." % channel)
        return

    if utils.isInternalServer(irc, u):
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
