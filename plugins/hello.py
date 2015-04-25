import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import proto

@proto.add_cmd
def hello(irc, source, args):
    proto._sendFromUser(irc, 'PRIVMSG %s :hello!' % source)
