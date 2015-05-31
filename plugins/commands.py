# commands.py: base PyLink commands
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import proto
import utils
from conf import conf

@utils.add_cmd
def tell(irc, source, args):
    try:
        target, text = args[0], ' '.join(args[1:])
    except IndexError:
        utils.msg(irc, source, 'Error: not enough arguments.')
        return
    targetuid = proto._nicktoUid(irc, target)
    if targetuid is None:
        utils.msg(irc, source, 'Error: unknown user %r' % target)
        return
    if not text:
        utils.msg(irc, source, "Error: can't send an empty message!")
        return
    utils.msg(irc, target, text, notice=True)

@utils.add_cmd
def debug(irc, source, args):
    utils.msg(irc, source, 'Debug info printed to console.')
    print(irc.users)
    print(irc.servers)

@utils.add_cmd
def status(irc, source, args):
    identified = irc.users[source].identified
    if identified:
        utils.msg(irc, source, 'You are identified as %s.' % identified)
    else:
        utils.msg(irc, source, 'You are not identified as anyone.')

@utils.add_cmd
def identify(irc, source, args):
    try:
        username, password = args[0], args[1]
    except IndexError:
        utils.msg(irc, source, 'Error: not enough arguments.')
        return
    if username.lower() == conf['login']['user'].lower() and password == conf['login']['password']:
        realuser = conf['login']['user']
        irc.users[source].identified = realuser
        utils.msg(irc, source, 'Successfully logged in as %s.' % realuser)
    else:
        utils.msg(irc, source, 'Incorrect credentials.')

def listcommands(irc, source, args):
    cmds = list(utils.bot_commands.keys())
    cmds.sort()
    utils.msg(irc, source, 'Available commands include: %s' % ', '.join(cmds))
utils.add_cmd(listcommands, 'list')
