# commands.py: base PyLink commands
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import proto
import utils

@proto.add_cmd
def tell(irc, source, args):
    try:
        target, text = args[0], ' '.join(args[1:])
    except IndexError:
        utils._msg(irc, source, 'Error: not enough arguments.', notice=False)
        return
    targetuid = proto._nicktoUid(irc, target)
    if targetuid is None:
        utils._msg(irc, source, 'Error: unknown user %r' % target, notice=False)
        return
    utils._msg(irc, target, text)

@proto.add_cmd
def debug(irc, source, args):
    utils._msg(irc, source, 'Debug info printed to console.')
    print(irc.users)
    print(irc.servers)
