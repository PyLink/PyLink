# commands.py: base PyLink commands
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import proto

@proto.add_cmd
def tell(irc, source, args):
    try:
        target, text = args[0], ' '.join(args[1:])
    except IndexError:
        proto._sendFromUser(irc, 'PRIVMSG %s :Error: not enough arguments' % source)
        return
    try:
        proto._sendFromUser(irc, 'NOTICE %s :%s' % (irc.users[target].uid, text))
    except KeyError:
        proto._sendFromUser(irc, 'PRIVMSG %s :unknown user %r' % (source, target))

@proto.add_cmd
def debug(irc, source, args):
    proto._sendFromUser(irc, 'NOTICE %s :Debug info printed to console.' % (source))
    print(irc.users)
