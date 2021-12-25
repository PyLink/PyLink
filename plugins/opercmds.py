"""
opercmds.py: Provides a subset of network management commands.
"""
import argparse

from pylinkirc import utils, world
from pylinkirc.coremods import permissions
from pylinkirc.log import log

# Having a hard limit here is sensible because otherwise it can flood the client or server off.
CHECKBAN_MAX_RESULTS = 200

def _checkban_positiveint(value):
    value = int(value)
    if value <= 0 or value > CHECKBAN_MAX_RESULTS:
         raise argparse.ArgumentTypeError("%s is not a positive integer between 1 and %s." % (value, CHECKBAN_MAX_RESULTS))
    return value

checkban_parser = utils.IRCParser()
checkban_parser.add_argument('banmask')
checkban_parser.add_argument('target', nargs='?', default='')
checkban_parser.add_argument('--channel', default='')
checkban_parser.add_argument('--maxresults', type=_checkban_positiveint, default=50)

def checkban(irc, source, args, use_regex=False):
    """<banmask> [<target nick or hostmask>] [--channel #channel] [--maxresults <num>]

    CHECKBAN provides a ban checker command based on nick!user@host masks, user@host masks, and
    PyLink extended targets.

    If a target nick or hostmask is given, this command returns whether the given banmask will match it.
    Otherwise, it will display a list of connected users matching the banmask.

    If the --channel argument is given without a target mask, the returned results will only
    include users in the given channel.

    The --maxresults option configures how many responses will be shown."""
    permissions.check_permissions(irc, source, ['opercmds.checkban'])

    args = checkban_parser.parse_args(args)
    if not args.target:
        # No hostmask was given, return a list of matched users.
        results = 0

        userlist_func = irc.match_all_re if use_regex else irc.match_all
        irc.reply("Checking for hosts that match \x02%s\x02:" % args.banmask, private=True)
        for uid in userlist_func(args.banmask, channel=args.channel):
            if results < args.maxresults:
                userobj = irc.users[uid]
                s = "\x02%s\x02 (%s@%s) [%s] {\x02%s\x02}" % (userobj.nick, userobj.ident,
                    userobj.host, userobj.realname, irc.get_friendly_name(irc.get_server(uid)))

                # Always reply in private to prevent information leaks.
                irc.reply(s, private=True)
            results += 1
        else:
            if results:
                irc.reply("\x02%s\x02 out of \x02%s\x02 results shown." %
                          (min([results, args.maxresults]), results), private=True)
            else:
                irc.reply("No results found.", private=True)
    else:
        # Target can be both a nick (of an online user) or a hostmask. irc.match_host() handles this
        # automatically.
        if irc.match_host(args.banmask, args.target):
            irc.reply('Yes, \x02%s\x02 matches \x02%s\x02.' % (args.target, args.banmask))
        else:
            irc.reply('No, \x02%s\x02 does not match \x02%s\x02.' % (args.target, args.banmask))
utils.add_cmd(checkban, aliases=('cban', 'trace'))

def checkbanre(irc, source, args):
    """<regular expression> [<target nick or hostmask>] [--channel #channel] [--maxresults <num>]

    CHECKBANRE provides a ban checker command based on regular expressions matched against
    users' "nick!user@host [gecos]" mask.

    If a target nick or hostmask is given, this command returns whether the given banmask will match it.
    Otherwise, it will display a list of connected users matching the banmask.

    If the --channel argument is given without a target mask, the returned results will only
    include users in the given channel.

    The --maxresults option configures how many responses will be shown."""
    permissions.check_permissions(irc, source, ['opercmds.checkban.re'])
    return checkban(irc, source, args, use_regex=True)

utils.add_cmd(checkbanre, aliases=('crban',))

massban_parser = utils.IRCParser()
massban_parser.add_argument('channel')
massban_parser.add_argument('banmask')
# Regarding default ban reason: it's a good idea not to leave in the caller to prevent retaliation...
massban_parser.add_argument('reason', nargs='*', default=["User banned"])
massban_parser.add_argument('--quiet', '-q', action='store_true')
massban_parser.add_argument('--force', '-f', action='store_true')
massban_parser.add_argument('--include-opers', '-o', action='store_true')

def massban(irc, source, args, use_regex=False):
    """<channel> <banmask / exttarget> [<kick reason>] [--quiet/-q] [--force/-f] [--include-opers/-o]

    Applies (i.e. kicks affected users) the given PyLink banmask on the specified channel.

    The --quiet option can also be given to mass-mute the given user on networks where this is supported
    (currently ts6, unreal, and inspircd). No kicks will be sent in this case.

    By default, this command will ignore opers. This behaviour can be suppressed using the --include-opers option.

    Relay CLAIM checking is used on Relay channels if it is enabled; use the --force option
    to override this if needed."""
    permissions.check_permissions(irc, source, ['opercmds.massban'])

    args = massban_parser.parse_args(args)
    reason = ' '.join(args.reason)

    if args.force:
        permissions.check_permissions(irc, source, ['opercmds.massban.force'])

    if args.channel not in irc.channels:
        irc.error("Unknown channel %r." % args.channel)
        return
    elif 'relay' in world.plugins and (not world.plugins['relay'].check_claim(irc, args.channel, source)) and (not args.force):
        irc.error("You do not have access to set bans in %s. Ask someone to op you or use the --force option." % args.channel)
        return

    results = 0

    userlist_func = irc.match_all_re if use_regex else irc.match_all
    for uid in userlist_func(args.banmask, channel=args.channel):

        if irc.is_oper(uid) and not args.include_opers:
            irc.reply('Skipping banning \x02%s\x02 because they are opered.' % irc.users[uid].nick)
            continue
        elif irc.get_service_bot(uid):
            irc.reply('Skipping banning \x02%s\x02 because it is a service client.' % irc.users[uid].nick)
            continue

        # Remove the target's access before banning them.
        bans = [('-%s' % irc.cmodes[prefix], uid) for prefix in irc.channels[args.channel].get_prefix_modes(uid) if prefix in irc.cmodes]

        # Then, add the actual ban.
        bans += [irc.make_channel_ban(uid, ban_type='quiet' if args.quiet else 'ban')]
        irc.mode(irc.pseudoclient.uid, args.channel, bans)

        try:
            irc.call_hooks([irc.pseudoclient.uid, 'OPERCMDS_MASSBAN',
                            {'target': args.channel, 'modes': bans, 'parse_as': 'MODE'}])
        except:
            log.exception('(%s) Failed to send process massban hook; some bans may have not '
                          'been sent to plugins / relay networks!', irc.name)

        if not args.quiet:
            irc.kick(irc.pseudoclient.uid, args.channel, uid, reason)

            # XXX: this better not be blocking...
            try:
                irc.call_hooks([irc.pseudoclient.uid, 'OPERCMDS_MASSKICK',
                                {'channel': args.channel, 'target': uid, 'text': reason, 'parse_as': 'KICK'}])

            except:
                log.exception('(%s) Failed to send process massban hook; some kicks may have not '
                              'been sent to plugins / relay networks!', irc.name)

        results += 1
    else:
        irc.reply('Banned %s users on %r.' % (results, args.channel))
        log.info('(%s) Ran massban%s for %s on %s (%s user(s) removed)', irc.name, 're' if use_regex else '',
                 irc.get_hostmask(source), args.channel, results)
utils.add_cmd(massban, aliases=('mban',))

def massbanre(irc, source, args):
    """<channel> <regular expression> [<kick reason>] [--quiet/-q] [--include-opers/-o]

    Bans users on the specified channel whose "nick!user@host [gecos]" mask matches the given Python-style regular expression.
    (https://docs.python.org/3/library/re.html#regular-expression-syntax describes supported syntax)

    The --quiet option can also be given to mass-mute the given user on networks where this is supported
    (currently ts6, unreal, and inspircd). No kicks will be sent in this case.

    By default, this command will ignore opers. This behaviour can be suppressed using the --include-opers option.

    \x02Be careful when using this command, as it is easy to make mistakes with regex. Use 'checkbanre'
    to check your bans first!\x02
    """
    permissions.check_permissions(irc, source, ['opercmds.massban.re'])
    return massban(irc, source, args, use_regex=True)

utils.add_cmd(massbanre, aliases=('rban',))

masskill_parser = utils.IRCParser()
masskill_parser.add_argument('banmask')
# Regarding default ban reason: it's a good idea not to leave in the caller to prevent retaliation...
masskill_parser.add_argument('reason', nargs='*', default=["User banned"], type=str)
masskill_parser.add_argument('--akill', '-ak', action='store_true')
masskill_parser.add_argument('--force-kb', '-f', action='store_true')
masskill_parser.add_argument('--include-opers', '-o', action='store_true')

def masskill(irc, source, args, use_regex=False):
    """<banmask / exttarget> [<kill/ban reason>] [--akill/ak] [--force-kb/-f] [--include-opers/-o]

    Kills all users matching the given PyLink banmask.

    The --akill option can also be given to convert kills to akills, which expire after 7 days.

    For relay users, attempts to kill are forwarded as a kickban to every channel where the calling user
    meets claim requirements to set a ban (i.e. this is true if you are opped, if your network is in claim list, etc.;
    see "help CLAIM" for more specific rules). This can also be extended to all shared channels
    the user is in using the --force-kb option (we hope this feature is only used for good).

    By default, this command will ignore opers. This behaviour can be suppressed using the --include-opers option.

    To properly kill abusers on another network, combine this command with the 'remote' command in the
    'networks' plugin and adjust your banmasks accordingly."""
    permissions.check_permissions(irc, source, ['opercmds.masskill'])

    args = masskill_parser.parse_args(args)

    if args.force_kb:
        permissions.check_permissions(irc, source, ['opercmds.masskill.force'])

    reason = ' '.join(args.reason)

    results = killed = 0

    userlist_func = irc.match_all_re if use_regex else irc.match_all

    seen_users = set()
    for uid in userlist_func(args.banmask):
        userobj = irc.users[uid]

        if irc.is_oper(uid) and not args.include_opers:
            irc.reply('Skipping killing \x02%s\x02 because they are opered.' % userobj.nick)
            continue
        elif irc.get_service_bot(uid):
            irc.reply('Skipping killing \x02%s\x02 because it is a service client.' % userobj.nick)
            continue

        relay = world.plugins.get('relay')
        if relay and hasattr(userobj, 'remote'):
            # For relay users, forward kill attempts as kickban because we don't want networks k-lining each others' users.
            bans = [irc.make_channel_ban(uid)]
            for channel in userobj.channels.copy():  # Look in which channels the user appears to be in locally

                if (args.force_kb or relay.check_claim(irc, channel, source)):
                    irc.mode(irc.pseudoclient.uid, channel, bans)
                    irc.kick(irc.pseudoclient.uid, channel, uid, reason)

                    # XXX: code duplication with massban.
                    try:
                        irc.call_hooks([irc.pseudoclient.uid, 'OPERCMDS_MASSKILL_BAN',
                                        {'target': channel, 'modes': bans, 'parse_as': 'MODE'}])
                        irc.call_hooks([irc.pseudoclient.uid, 'OPERCMDS_MASSKILL_KICK',
                                        {'channel': channel, 'target': uid, 'text': reason, 'parse_as': 'KICK'}])
                    except:
                        log.exception('(%s) Failed to send process massban hook; some kickbans may have not '
                                      'been sent to plugins / relay networks!', irc.name)

                    if uid not in seen_users:  # Don't count users multiple times on different channels
                        killed += 1
                else:
                    irc.reply("Not kicking \x02%s\x02 from \x02%s\x02 because you don't have CLAIM access. If this is "
                              "another network's channel, ask someone to op you or use the --force-kb option." % (userobj.nick, channel))
        else:
            if args.akill:  # TODO: configurable length via strings such as "2w3d5h6m3s" - though month and minute clash this way?
                if not (userobj.realhost or userobj.ip):
                    irc.reply("Skipping akill on %s because PyLink doesn't know the real host." % irc.get_hostmask(uid))
                    continue
                irc.set_server_ban(irc.pseudoclient.uid, 604800, host=userobj.realhost or userobj.ip or userobj.host, reason=reason)
            else:
                irc.kill(irc.pseudoclient.uid, uid, reason)
                try:
                    irc.call_hooks([irc.pseudoclient.uid, 'OPERCMDS_MASSKILL',
                                    {'target': uid, 'parse_as': 'KILL', 'userdata': userobj, 'text': reason}])
                except:
                    log.exception('(%s) Failed to send process massban hook; some kickbans may have not '
                                  'been sent to plugins / relay networks!', irc.name)
            killed += 1
        results += 1
        seen_users.add(uid)
    else:
        log.info('(%s) Ran masskill%s for %s (%s/%s user(s) removed)', irc.name, 're' if use_regex else '',
                 irc.get_hostmask(source), killed, results)
        irc.reply('Masskilled %s/%s users.' % (killed, results))
utils.add_cmd(masskill, aliases=('mkill',))

def masskillre(irc, source, args):
    """<regular expression> [<kill/ban reason>] [--akill/ak] [--force-kb/-f] [--include-opers/-o]

    Kills all users whose "nick!user@host [gecos]" mask matches the given Python-style regular expression.
    (https://docs.python.org/3/library/re.html#regular-expression-syntax describes supported syntax)

    The --akill option can also be given to convert kills to akills that expire after 7 days.

    For relay users, attempts to kill are forwarded as a kickban to every channel where the calling user
    meets claim requirements to set a ban (i.e. this is true if you are opped, if your network is in claim list, etc.;
    see "help CLAIM" for more specific rules). This can also be extended to all shared channels
    the user is in using the --force-kb option (we hope this feature is only used for good).

    By default, this command will ignore opers. This behaviour can be suppressed using the --include-opers option.

    \x02Be careful when using this command, as it is easy to make mistakes with regex. Use 'checkbanre'
    to check your bans first!\x02

    """
    permissions.check_permissions(irc, source, ['opercmds.masskill.re'])
    return masskill(irc, source, args, use_regex=True)

utils.add_cmd(masskillre, aliases=('rkill',))

@utils.add_cmd
def jupe(irc, source, args):
    """<server> [<reason>]

    Jupes the given server."""

    permissions.check_permissions(irc, source, ['opercmds.jupe'])

    try:
        servername = args[0]
        reason = ' '.join(args[1:]) or "No reason given"
        desc = "Juped by %s: [%s]" % (irc.get_hostmask(source), reason)
    except IndexError:
        irc.error('Not enough arguments. Needs 1-2: servername, reason (optional).')
        return

    if not irc.is_server_name(servername):
        irc.error("Invalid server name %r." % servername)
        return

    sid = irc.spawn_server(servername, desc=desc)

    irc.call_hooks([irc.pseudoclient.uid, 'OPERCMDS_SPAWNSERVER',
                   {'name': servername, 'sid': sid, 'text': desc}])

    irc.reply("Done.")

def _try_find_target(irc, nick):
    """
    Tries to find the target UID for the given nick, raising LookupError if it doesn't exist or is ambiguous.
    """
    try:
        int_u = int(nick)
    except:
        int_u = None

    if int_u and int_u in irc.users:
        return int_u  # Some protocols use numeric UIDs
    elif nick in irc.users:
        return nick

    potential_targets = irc.nick_to_uid(nick, multi=True)
    if not potential_targets:
        # Whatever we were told to kick doesn't exist!
        raise LookupError("No such target %r." % nick)
    elif len(potential_targets) > 1:
        raise LookupError("Multiple users with the nick %r found: please select the right UID: %s" % (nick, str(potential_targets)))
    else:
        return potential_targets[0]

@utils.add_cmd
def kick(irc, source, args):
    """<channel> <user> [<reason>]

    Kicks <user> from the specified channel."""
    permissions.check_permissions(irc, source, ['opercmds.kick'])
    try:
        channel = args[0]
        target = args[1]
        reason = ' '.join(args[2:])
    except IndexError:
        irc.error("Not enough arguments. Needs 2-3: channel, target, reason (optional).")
        return

    if channel not in irc.channels:  # KICK only works on channels that exist.
        irc.error("Unknown channel %r." % channel)
        return

    targetu = _try_find_target(irc, target)

    sender = irc.pseudoclient.uid
    irc.kick(sender, channel, targetu, reason)
    irc.reply("Done.")
    irc.call_hooks([sender, 'OPERCMDS_KICK', {'channel': channel, 'target': targetu,
                                              'text': reason, 'parse_as': 'KICK'}])

@utils.add_cmd
def kill(irc, source, args):
    """<target> [<reason>]

    Kills the given target."""
    permissions.check_permissions(irc, source, ['opercmds.kill'])
    try:
        target = args[0]
        reason = ' '.join(args[1:])
    except IndexError:
        irc.error("Not enough arguments. Needs 1-2: target, reason (optional).")
        return

    # Convert the source and target nicks to UIDs.
    sender = irc.pseudoclient.uid

    targetu = _try_find_target(irc, target)

    if irc.pseudoclient.uid == targetu:
        irc.error("Cannot kill the main PyLink client!")
        return

    userdata = irc.users.get(targetu)

    reason = "Requested by %s: %s" % (irc.get_friendly_name(source), reason)

    irc.kill(sender, targetu, reason)

    irc.reply("Done.")
    irc.call_hooks([source, 'OPERCMDS_KILL', {'target': targetu, 'text': reason,
                                              'userdata': userdata, 'parse_as': 'KILL'}])

@utils.add_cmd
def mode(irc, source, args):
    """<channel> <modes>

    Sets the given modes on the target channel."""

    permissions.check_permissions(irc, source, ['opercmds.mode'])

    try:
        target, modes = args[0], args[1:]
    except IndexError:
        irc.error('Not enough arguments. Needs 2: target, modes to set.')
        return

    if target not in irc.channels:
        irc.error("Unknown channel %r." % target)
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
    irc.call_hooks([irc.pseudoclient.uid, 'OPERCMDS_MODE',
                   {'target': target, 'modes': parsedmodes, 'parse_as': 'MODE'}])

    irc.reply("Done.")

@utils.add_cmd
def topic(irc, source, args):
    """<channel> <topic>

    Changes the topic in a channel."""
    permissions.check_permissions(irc, source, ['opercmds.topic'])
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
    irc.call_hooks([irc.pseudoclient.uid, 'OPERCMDS_TOPIC',
                   {'channel': channel, 'text': topic, 'setter': source,
                    'parse_as': 'TOPIC'}])

@utils.add_cmd
def chghost(irc, source, args):
    """<user> <new host>

    Changes the visible host of the target user."""
    _chgfield(irc, source, args, 'host')

@utils.add_cmd
def chgident(irc, source, args):
    """<user> <new ident>

    Changes the ident of the target user."""
    _chgfield(irc, source, args, 'ident')

@utils.add_cmd
def chgname(irc, source, args):
    """<user> <new name>

    Changes the GECOS (realname) of the target user."""
    _chgfield(irc, source, args, 'name', 'GECOS')

def _chgfield(irc, source, args, human_field, internal_field=None):
    """Helper function for chghost/chgident/chgname."""
    permissions.check_permissions(irc, source, ['opercmds.chg' + human_field])
    try:
        target = args[0]
        new = args[1]
    except IndexError:
        irc.error("Not enough arguments. Needs 2: target, new %s." % human_field)
        return

    # Find the user
    targetu = _try_find_target(irc, target)

    internal_field = internal_field or human_field.upper()
    irc.update_client(targetu, internal_field, new)
    irc.reply("Done.")
