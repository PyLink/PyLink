"""
bots.py: Spawn virtual users/bots on a PyLink server and make them interact
with things.
"""
from pylinkirc import utils
from pylinkirc.log import log

@utils.add_cmd
def spawnclient(irc, source, args):
    """<nick> <ident> <host>

    Admin-only. Spawns the specified PseudoClient on the PyLink server.
    Note: this doesn't check the validity of any fields you give it!"""
    irc.checkAuthenticated(source, allowOper=False)
    try:
        nick, ident, host = args[:3]
    except ValueError:
        irc.reply("Error: Not enough arguments. Needs 3: nick, user, host.")
        return
    irc.proto.spawnClient(nick, ident, host, manipulatable=True)

@utils.add_cmd
def quit(irc, source, args):
    """<target> [<reason>]

    Admin-only. Quits the PyLink client with nick <target>, if one exists."""
    irc.checkAuthenticated(source, allowOper=False)

    try:
        nick = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1-2: nick, reason (optional).")
        return
    if irc.pseudoclient.uid == irc.nickToUid(nick):
        irc.reply("Error: Cannot quit the main PyLink PseudoClient!")
        return

    u = irc.nickToUid(nick)

    quitmsg =  ' '.join(args[1:]) or 'Client Quit'

    if not irc.isManipulatableClient(u):
        irc.reply("Error: Cannot force quit a protected PyLink services client.")
        return

    irc.proto.quit(u, quitmsg)
    irc.callHooks([u, 'PYLINK_BOTSPLUGIN_QUIT', {'text': quitmsg, 'parse_as': 'QUIT'}])

def joinclient(irc, source, args):
    """[<target>] <channel1>,[<channel2>], etc.

    Admin-only. Joins <target>, the nick of a PyLink client, to a comma-separated list of channels. If <target> is not given, it defaults to the main PyLink client."""
    irc.checkAuthenticated(source, allowOper=False)

    try:
        # Check if the first argument is an existing PyLink client. If it is not,
        # then assume that the first argument was actually the channels being joined.
        u = irc.nickToUid(args[0])

        if not irc.isInternalClient(u):  # First argument isn't one of our clients
            raise IndexError

        clist = args[1]
    except IndexError:  # No nick was given; shift arguments one to the left.
        u = irc.pseudoclient.uid
        try:
            clist = args[0]
        except IndexError:
            irc.reply("Error: Not enough arguments. Needs 1-2: nick (optional), comma separated list of channels.")
            return

    clist = clist.split(',')
    if not clist:
        irc.reply("Error: No valid channels given.")
        return

    if not (irc.isManipulatableClient(u) or irc.isServiceBot(u)):
        irc.reply("Error: Cannot force join a protected PyLink services client.")
        return

    for channel in clist:
        if not utils.isChannel(channel):
            irc.reply("Error: Invalid channel name %r." % channel)
            return
        irc.proto.join(u, channel)

        # Call a join hook manually so other plugins like relay can understand it.
        irc.callHooks([u, 'PYLINK_BOTSPLUGIN_JOIN', {'channel': channel, 'users': [u],
                                                'modes': irc.channels[channel].modes,
                                                'parse_as': 'JOIN'}])
utils.add_cmd(joinclient, name='join')

@utils.add_cmd
def nick(irc, source, args):
    """[<target>] <newnick>

    Admin-only. Changes the nick of <target>, a PyLink client, to <newnick>. If <target> is not given, it defaults to the main PyLink client."""
    irc.checkAuthenticated(source, allowOper=False)

    try:
        nick = args[0]
        newnick = args[1]
    except IndexError:
        try:
            nick = irc.pseudoclient.nick
            newnick = args[0]
        except IndexError:
            irc.reply("Error: Not enough arguments. Needs 1-2: nick (optional), newnick.")
            return
    u = irc.nickToUid(nick)

    if newnick in ('0', u):  # Allow /nick 0 to work
        newnick = u

    elif not utils.isNick(newnick):
        irc.reply('Error: Invalid nickname %r.' % newnick)
        return

    elif not (irc.isManipulatableClient(u) or irc.isServiceBot(u)):
        irc.reply("Error: Cannot force nick changes for a protected PyLink services client.")
        return

    irc.proto.nick(u, newnick)
    # Ditto above: manually send a NICK change hook payload to other plugins.
    irc.callHooks([u, 'PYLINK_BOTSPLUGIN_NICK', {'newnick': newnick, 'oldnick': nick, 'parse_as': 'NICK'}])

@utils.add_cmd
def part(irc, source, args):
    """[<target>] <channel1>,[<channel2>],... [<reason>]

    Admin-only. Parts <target>, the nick of a PyLink client, from a comma-separated list of channels. If <target> is not given, it defaults to the main PyLink client."""
    irc.checkAuthenticated(source, allowOper=False)

    try:
        nick = args[0]
        clist = args[1]
        # For the part message, join all remaining arguments into one text string
        reason = ' '.join(args[2:])

        # First, check if the first argument is an existing PyLink client. If it is not,
        # then assume that the first argument was actually the channels being parted.
        u = irc.nickToUid(nick)
        if not irc.isInternalClient(u):  # First argument isn't one of our clients
            raise IndexError

    except IndexError:  # No nick was given; shift arguments one to the left.
        u = irc.pseudoclient.uid

        try:
            clist = args[0]
        except IndexError:
            irc.reply("Error: Not enough arguments. Needs 1-2: nick (optional), comma separated list of channels.")
            return
        reason = ' '.join(args[1:])

    clist = clist.split(',')
    if not clist:
        irc.reply("Error: No valid channels given.")
        return

    if not (irc.isManipulatableClient(u) or irc.isServiceBot(u)):
        irc.reply("Error: Cannot force part a protected PyLink services client.")
        return

    for channel in clist:
        if not utils.isChannel(channel):
            irc.reply("Error: Invalid channel name %r." % channel)
            return
        irc.proto.part(u, channel, reason)

    irc.callHooks([u, 'PYLINK_BOTSPLUGIN_PART', {'channels': clist, 'text': reason, 'parse_as': 'PART'}])

@utils.add_cmd
def msg(irc, source, args):
    """[<source>] <target> <text>

    Admin-only. Sends message <text> from <source>, where <source> is the nick of a PyLink client. If <source> is not given, it defaults to the main PyLink client."""
    irc.checkAuthenticated(source, allowOper=False)

    # Because we want the source nick to be optional, this argument parsing gets a bit tricky.
    try:
        msgsource = args[0]
        target = args[1]
        text = ' '.join(args[2:])

        # First, check if the first argument is an existing PyLink client. If it is not,
        # then assume that the first argument was actually the message TARGET.
        sourceuid = irc.nickToUid(msgsource)
        if not irc.isInternalClient(sourceuid):  # First argument isn't one of our clients
            raise IndexError

        if not text:
            raise IndexError
    except IndexError:
        try:
            sourceuid = irc.pseudoclient.uid
            target = args[0]
            text = ' '.join(args[1:])
        except IndexError:
            irc.reply('Error: Not enough arguments. Needs 2-3: source nick (optional), target, text.')
            return

    if not text:
        irc.reply('Error: No text given.')
        return

    if not utils.isChannel(target):
        # Convert nick of the message target to a UID, if the target isn't a channel
        real_target = irc.nickToUid(target)
        if real_target is None:  # Unknown target user, if target isn't a valid channel name
            irc.reply('Error: Unknown user %r.' % target)
            return
    else:
        real_target = target

    irc.proto.message(sourceuid, real_target, text)
    irc.callHooks([sourceuid, 'PYLINK_BOTSPLUGIN_MSG', {'target': real_target, 'text': text, 'parse_as': 'PRIVMSG'}])
utils.add_cmd(msg, 'say')
