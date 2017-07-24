"""
opercmds.py: Provides a subset of network management commands.
"""
from pylinkirc import utils
from pylinkirc.log import log
from pylinkirc.coremods import permissions

checkban_parser = utils.IRCParser()
checkban_parser.add_argument('banmask')
checkban_parser.add_argument('-c', '--channel', action='store', default=False)
def checkban(irc, source, args):
    """<banmask (nick!user@host or user@host)> [<nick or hostmask to check> -c/--channel #channel] 

    Oper only. If a nick or hostmask is given, return whether the given banmask will match it. Otherwise, returns a list of connected users that would be affected by such a ban, up to 50 results."""
    permissions.checkPermissions(irc, source, ['opercmds.checkban'])
    
    options = checkban_parser.parse_args(args)
    try:
        banmask = args[0]
    except IndexError:
        irc.error("Not enough arguments. Needs 1-2: banmask, nick or hostmask to check (optional).")
        return

    try:
        targetmask = args[1]
    except IndexError:
        # No hostmask was given, return a list of affected users.

        irc.msg(source, "Checking for hosts that match \x02%s\x02:" % banmask, notice=True)

        results = 0
        if options.channel:
            if options.channel.startswith('#'):
                for uid, userobj in irc.channels[options.channel].items():
                    if irc.match_host(banmask, uid):
                        if results < 50:  # XXX rather arbitrary limit
                            s = "\x02%s\x02 (%s@%s) [%s] {\x02%s\x02}" % (userobj.nick, userobj.ident,
                                userobj.host, userobj.realname, irc.get_friendly_name(irc.get_server(uid)))
                            
                            # Always reply in private to prevent information leaks.
                            irc.reply(s, private=True)
                        results += 1
                    else:
                        if results:
                            irc.msg(source, "\x02%s\x02 out of \x02%s\x02 results shown for \x02%s\x02." %
                                    (min([results, 50]), results, options.channel), notice=True)
                        else:
                            irc.msg(source, "No results found via \x02%s\x02." % (options.channel), notice=True)
        else:
            for uid, userobj in irc.users.copy().items():
                if irc.match_host(banmask, uid):
                    if results < 50:  # XXX rather arbitrary limit
                        s = "\x02%s\x02 (%s@%s) [%s] {\x02%s\x02}" % (userobj.nick, userobj.ident,
                            userobj.host, userobj.realname, irc.get_friendly_name(irc.get_server(uid)))

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
        # Target can be both a nick (of an online user) or a hostmask. irc.match_host() handles this
        # automatically.
        if irc.match_host(banmask, targetmask):
            irc.reply('Yes, \x02%s\x02 matches \x02%s\x02.' % (targetmask, banmask))
        else:
            irc.reply('No, \x02%s\x02 does not match \x02%s\x02.' % (targetmask, banmask))
utils.add_cmd(checkban, "checkban")
            
@utils.add_cmd
def jupe(irc, source, args):
    """<server> [<reason>]

    Admin only, jupes the given server."""

    # Check that the caller is either opered or logged in as admin.
    permissions.checkPermissions(irc, source, ['opercmds.jupe'])

    try:
        servername = args[0]
        reason = ' '.join(args[1:]) or "No reason given"
        desc = "Juped by %s: [%s]" % (irc.get_hostmask(source), reason)
    except IndexError:
        irc.error('Not enough arguments. Needs 1-2: servername, reason (optional).')
        return

    if not utils.isServerName(servername):
        irc.error("Invalid server name '%s'." % servername)
        return

    sid = irc.spawn_server(servername, desc=desc)

    irc.call_hooks([irc.pseudoclient.uid, 'OPERCMDS_SPAWNSERVER',
                   {'name': servername, 'sid': sid, 'text': desc}])

    irc.reply("Done.")


@utils.add_cmd
def kick(irc, source, args):
    """<channel> <user> [<reason>]

    Admin only. Kicks <user> from the specified channel."""
    permissions.checkPermissions(irc, source, ['opercmds.kick'])
    try:
        channel = irc.to_lower(args[0])
        target = args[1]
        reason = ' '.join(args[2:])
    except IndexError:
        irc.error("Not enough arguments. Needs 2-3: channel, target, reason (optional).")
        return

    targetu = irc.nick_to_uid(target)

    if channel not in irc.channels:  # KICK only works on channels that exist.
        irc.error("Unknown channel %r." % channel)
        return

    if not targetu:
        # Whatever we were told to kick doesn't exist!
        irc.error("No such target nick '%s'." % target)
        return

    sender = irc.pseudoclient.uid
    irc.kick(sender, channel, targetu, reason)
    irc.reply("Done.")
    irc.call_hooks([sender, 'CHANCMDS_KICK', {'channel': channel, 'target': targetu,
                                        'text': reason, 'parse_as': 'KICK'}])

@utils.add_cmd
def kill(irc, source, args):
    """<target> [<reason>]

    Admin only. Kills the given target."""
    permissions.checkPermissions(irc, source, ['opercmds.kill'])
    try:
        target = args[0]
        reason = ' '.join(args[1:])
    except IndexError:
        irc.error("Not enough arguments. Needs 1-2: target, reason (optional).")
        return

    # Convert the source and target nicks to UIDs.
    sender = irc.pseudoclient.uid
    targetu = irc.nick_to_uid(target)
    userdata = irc.users.get(targetu)

    if targetu not in irc.users:
        # Whatever we were told to kick doesn't exist!
        irc.error("No such nick '%s'." % target)
        return

    irc.kill(sender, targetu, reason)

    # Format the kill reason properly in hooks.
    reason = "Killed (%s (%s))" % (irc.get_friendly_name(sender), reason)

    irc.reply("Done.")
    irc.call_hooks([sender, 'CHANCMDS_KILL', {'target': targetu, 'text': reason,
                                        'userdata': userdata, 'parse_as': 'KILL'}])

@utils.add_cmd
def mode(irc, source, args):
    """<channel> <modes>

    Oper-only, sets modes <modes> on the target channel."""

    # Check that the caller is either opered or logged in as admin.
    permissions.checkPermissions(irc, source, ['opercmds.mode'])

    try:
        target, modes = args[0], args[1:]
    except IndexError:
        irc.error('Not enough arguments. Needs 2: target, modes to set.')
        return

    if target not in irc.channels:
        irc.error("Unknown channel '%s'." % target)
        return
    elif not modes:
        # No modes were given before parsing (i.e. mode list was blank).
        irc.error("No valid modes were given.")
        return

    parsedmodes = irc.parse_modes(target, modes)

    if not parsedmodes:
        # Modes were given but they failed to parse into anything meaningful.
        # For example, "mode #somechan +o" would be erroneous because +o
        # requires an argument!
        irc.error("No valid modes were given.")
        return

    irc.mode(irc.pseudoclient.uid, target, parsedmodes)

    # Call the appropriate hooks for plugins like relay.
    irc.call_hooks([irc.pseudoclient.uid, 'OPERCMDS_MODEOVERRIDE',
                   {'target': target, 'modes': parsedmodes, 'parse_as': 'MODE'}])

    irc.reply("Done.")

@utils.add_cmd
def topic(irc, source, args):
    """<channel> <topic>

    Admin only. Updates the topic in a channel."""
    permissions.checkPermissions(irc, source, ['opercmds.topic'])
    try:
        channel = args[0]
        topic = ' '.join(args[1:])
    except IndexError:
        irc.error("Not enough arguments. Needs 2: channel, topic.")
        return

    if channel not in irc.channels:
        irc.error("Unknown channel %r." % channel)
        return

    irc.topic(irc.pseudoclient.uid, channel, topic)

    irc.reply("Done.")
    irc.call_hooks([irc.pseudoclient.uid, 'CHANCMDS_TOPIC',
                   {'channel': channel, 'text': topic, 'setter': source,
                    'parse_as': 'TOPIC'}])

@utils.add_cmd
def chghost(irc, source, args):
    """<user> <new host>

    Admin only. Changes the visible host of the target user."""
    chgfield(irc, source, args, 'host')

@utils.add_cmd
def chgident(irc, source, args):
    """<user> <new ident>

    Admin only. Changes the ident of the target user."""
    chgfield(irc, source, args, 'ident')
    
@utils.add_cmd
def chgname(irc, source, args):
    """<user> <new name>

    Admin only. Changes the GECOS (realname) of the target user."""
    chgfield(irc, source, args, 'name', 'GECOS')

def chgfield(irc, source, args, human_field, internal_field=None):
    permissions.checkPermissions(irc, source, ['opercmds.chg' + human_field])
    try:
        target = args[0]
        new = args[1]
    except IndexError:
        irc.error("Not enough arguments. Needs 2: target, new %s." % human_field)
        return
    
    # Find the user
    targetu = irc.nick_to_uid(target)
    if targetu not in irc.users:
        irc.error("No such nick %r." % target)
        return
        
    internal_field = internal_field or human_field.upper()
    irc.update_client(targetu, internal_field, new)
    irc.reply("Done.")
