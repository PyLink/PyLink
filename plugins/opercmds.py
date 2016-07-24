"""
opercmds.py: Provides a subset of network management commands.
"""
from pylinkirc import utils
from pylinkirc.log import log

@utils.add_cmd
def checkban(irc, source, args):
    """<banmask (nick!user@host or user@host)> [<nick or hostmask to check>]

    Oper only. If a nick or hostmask is given, return whether the given banmask will match it. Otherwise, returns a list of connected users that would be affected by such a ban, up to 50 results."""
    irc.checkAuthenticated(source)

    try:
        banmask = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1-2: banmask, nick or hostmask to check (optional).")
        return

    try:
        targetmask = args[1]
    except IndexError:
        # No hostmask was given, return a list of affected users.

        irc.msg(source, "Checking for hosts that match \x02%s\x02:" % banmask, notice=True)

        results = 0
        for uid, userobj in irc.users.copy().items():
            if irc.matchHost(banmask, uid):
                if results < 50:  # XXX rather arbitrary limit
                    s = "\x02%s\x02 (%s@%s) [%s] {\x02%s\x02}" % (userobj.nick, userobj.ident,
                        userobj.host, userobj.realname, irc.getFriendlyName(irc.getServer(uid)))

                    # Always reply in private to prevent information leaks.
                    irc.reply(s, private=True)
                results += 1
        else:
            if results:
                irc.msg(source, "\x02%s\x02 out of \x02%s\x02 results shown." %
                        (min([results, 50]), results), notice=True)
            else:
                irc.msg(source, "No results found.", notice=True)
    else:
        # Target can be both a nick (of an online user) or a hostmask. irc.matchHost() handles this
        # automatically.
        if irc.matchHost(banmask, targetmask):
            irc.reply('Yes, \x02%s\x02 matches \x02%s\x02.' % (targetmask, banmask))
        else:
            irc.reply('No, \x02%s\x02 does not match \x02%s\x02.' % (targetmask, banmask))

@utils.add_cmd
def jupe(irc, source, args):
    """<server> [<reason>]

    Admin only, jupes the given server."""

    # Check that the caller is either opered or logged in as admin.
    irc.checkAuthenticated(source, allowOper=False)

    try:
        servername = args[0]
        reason = ' '.join(args[1:]) or "No reason given"
        desc = "Juped by %s: [%s]" % (irc.getHostmask(source), reason)
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
    irc.checkAuthenticated(source, allowOper=False)
    try:
        sourcenick = args[0]
        channel = irc.toLower(args[1])
        target = args[2]
        reason = ' '.join(args[3:])
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 3-4: source nick, channel, target, reason (optional).")
        return

    # Convert the source and target nicks to UIDs.
    sender = irc.nickToUid(sourcenick) or sourcenick
    targetu = irc.nickToUid(target)

    if channel not in irc.channels:  # KICK only works on channels that exist.
        irc.reply("Error: Unknown channel %r." % channel)
        return

    if (not irc.isInternalClient(sender)) and \
            (not irc.isInternalServer(sender)):
        # Whatever we were told to send the kick from wasn't valid; try to be
        # somewhat user friendly in the error message
        irc.reply("Error: No such PyLink client '%s'. The first argument to "
                  "KICK should be the name of a PyLink client (e.g. '%s'; see "
                  "'help kick' for details." % (sourcenick,
                  irc.pseudoclient.nick))
        return
    elif not targetu:
        # Whatever we were told to kick doesn't exist!
        irc.reply("Error: No such target nick '%s'." % target)
        return

    irc.proto.kick(sender, channel, targetu, reason)
    irc.callHooks([sender, 'CHANCMDS_KICK', {'channel': channel, 'target': targetu,
                                        'text': reason, 'parse_as': 'KICK'}])

@utils.add_cmd
def kill(irc, source, args):
    """<source> <target> [<reason>]

    Admin only. Kills <target> via <source>, where <source> is either the nick of a PyLink client or the SID of a PyLink server."""
    irc.checkAuthenticated(source, allowOper=False)
    try:
        sourcenick = args[0]
        target = args[1]
        reason = ' '.join(args[2:])
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 3-4: source nick, target, reason (optional).")
        return

    # Convert the source and target nicks to UIDs.
    sender = irc.nickToUid(sourcenick) or sourcenick
    targetu = irc.nickToUid(target)
    userdata = irc.users.get(targetu)

    if (not irc.isInternalClient(sender)) and \
            (not irc.isInternalServer(sender)):
        # Whatever we were told to send the kick from wasn't valid; try to be
        # somewhat user friendly in the error message
        irc.reply("Error: No such PyLink client '%s'. The first argument to "
                  "KILL should be the name of a PyLink client (e.g. '%s'; see "
                  "'help kill' for details." % (sourcenick,
                  irc.pseudoclient.nick))
        return
    elif targetu not in irc.users:
        # Whatever we were told to kick doesn't exist!
        irc.reply("Error: No such nick '%s'." % target)
        return

    irc.proto.kill(sender, targetu, reason)

    # Format the kill reason properly in hooks.
    reason = "Killed (%s (%s))" % (irc.getFriendlyName(sender), reason)

    irc.callHooks([sender, 'CHANCMDS_KILL', {'target': targetu, 'text': reason,
                                        'userdata': userdata, 'parse_as': 'KILL'}])

@utils.add_cmd
def mode(irc, source, args):
    """<channel> <modes>

    Oper-only, sets modes <modes> on the target channel."""

    # Check that the caller is either opered or logged in as admin.
    irc.checkAuthenticated(source)

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

    parsedmodes = irc.parseModes(target, modes)

    if not parsedmodes:
        # Modes were given but they failed to parse into anything meaningful.
        # For example, "mode #somechan +o" would be erroneous because +o
        # requires an argument!
        irc.reply("Error: No valid modes were given.")
        return

    irc.proto.mode(irc.pseudoclient.uid, target, parsedmodes)

    # Call the appropriate hooks for plugins like relay.
    irc.callHooks([irc.pseudoclient.uid, 'OPERCMDS_MODEOVERRIDE',
                   {'target': target, 'modes': parsedmodes, 'parse_as': 'MODE'}])

    irc.reply("Done.")

@utils.add_cmd
def topic(irc, source, args):
    """<channel> <topic>

    Admin only. Updates the topic in a channel."""
    irc.checkAuthenticated(source, allowOper=False)
    try:
        channel = args[0]
        topic = ' '.join(args[1:])
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 2: channel, topic.")
        return

    if channel not in irc.channels:
        irc.reply("Error: Unknown channel %r." % channel)
        return

    irc.proto.topic(irc.pseudoclient.uid, channel, topic)

    irc.callHooks([irc.pseudoclient.uid, 'CHANCMDS_TOPIC',
                   {'channel': channel, 'text': topic, 'setter': source,
                    'parse_as': 'TOPIC'}])
