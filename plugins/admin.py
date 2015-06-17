# admin.py: PyLink administrative commands
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils

class NotAuthenticatedError(Exception):
    pass

def checkauthenticated(irc, source):
    if not irc.users[source].identified:
        raise NotAuthenticatedError("You are not authenticated!")

@utils.add_cmd
def eval(irc, source, args):
    checkauthenticated(irc, source)
    args = ' '.join(args)
    if not args.strip():
        utils.msg(irc, source, 'No code entered!')
        return
    exec(args)

@utils.add_cmd
def spawnclient(irc, source, args):
    checkauthenticated(irc, source)
    try:
        nick, ident, host = args[:3]
    except ValueError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 3: nick, user, host.")
        return
    irc.proto.spawnClient(irc, nick, ident, host)

@utils.add_cmd
def quitclient(irc, source, args):
    checkauthenticated(irc, source)
    try:
        nick = args[0]
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 1: nick.")
        return
    if irc.pseudoclient.uid == utils.nickToUid(irc, nick):
        utils.msg(irc, source, "Error: cannot quit the main PyLink PseudoClient!")
        return
    u = utils.nickToUid(irc, nick)
    quitmsg =  ' '.join(args[1:]) or 'Client quit'
    irc.proto.quitClient(irc, u, quitmsg)

@utils.add_cmd
def joinclient(irc, source, args):
    checkauthenticated(irc, source)
    try:
        nick = args[0]
        clist = args[1].split(',')
        if not clist:
            raise IndexError
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 2: nick, comma separated list of channels.")
        return
    u = utils.nickToUid(irc, nick)
    for channel in clist:
        if not channel.startswith('#'):
            utils.msg(irc, source, "Error: channel names must start with #.")
            return
        irc.proto.joinClient(irc, u, channel)

@utils.add_cmd
def nickclient(irc, source, args):
    checkauthenticated(irc, source)
    try:
        nick = args[0]
        newnick = args[1]
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 2: nick, newnick.")
        return
    u = utils.nickToUid(irc, nick)
    irc.proto.nickClient(irc, u, newnick)

@utils.add_cmd
def partclient(irc, source, args):
    checkauthenticated(irc, source)
    try:
        nick = args[0]
        clist = args[1].split(',')
        reason = ' '.join(args[2:])
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 2: nick, comma separated list of channels.")
        return
    u = utils.nickToUid(irc, nick)
    for channel in clist:
        if not channel.startswith('#'):
            utils.msg(irc, source, "Error: channel names must start with #.")
            return
        irc.proto.partClient(irc, u, channel, reason)

@utils.add_cmd
def kickclient(irc, source, args):
    checkauthenticated(irc, source)
    try:
        nick = args[0]
        channel = args[1]
        target = args[2]
        reason = ' '.join(args[3:])
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 3-4: nick, channel, target, reason (optional).")
        return
    u = utils.nickToUid(irc, nick)
    targetu = utils.nickToUid(irc, target)
    if not channel.startswith('#'):
        utils.msg(irc, source, "Error: channel names must start with #.")
        return
    irc.proto.kickClient(irc, u, channel, targetu, reason)

@utils.add_cmd
def tell(irc, source, args):
    checkauthenticated(irc, source)
    try:
        source, target, text = args[0], args[1], ' '.join(args[2:])
    except IndexError:
        utils.msg(irc, source, 'Error: not enough arguments.')
        return
    targetuid = utils.nickToUid(irc, target)
    if targetuid is None:
        utils.msg(irc, source, 'Error: unknown user %r' % target)
        return
    if not text:
        utils.msg(irc, source, "Error: can't send an empty message!")
        return
    utils.msg(irc, target, text, notice=True)
