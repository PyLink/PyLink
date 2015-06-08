# admin.py: PyLink administrative commands
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import proto
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
    proto.spawnClient(irc, nick, ident, host)

@utils.add_cmd
def removeclient(irc, source, args):
    checkauthenticated(irc, source)
    try:
        nick = args[0].lower()
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 1: nick.")
        return
    u = _nicktoUid(nick)
    if u is None or u not in irc.server[irc.sid].users:
        utils.msg(irc, source, "Error: user %r not found." % nick)
        return
    _sendFromUser(irc, u, "QUIT :Client Quit")
    proto.removeClient(irc, nick, ident, host)

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
    u = _nicktoUid(nick)
    if u is None or u not in irc.server[irc.sid].users:
        utils.msg(irc, source, "Error: user %r not found." % nick)
        return
    for channel in clist:
        if not channel.startswith('#'):
            utils.msg(irc, source, "Error: channel names must start with #.")
            return
    joinClient(irc, ','.join(clist))
