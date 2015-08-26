# commands.py: base PyLink commands
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils
from conf import conf
from log import log

@utils.add_cmd
def status(irc, source, args):
    """takes no arguments.

    Returns your current PyLink login status."""
    identified = irc.users[source].identified
    if identified:
        utils.msg(irc, source, 'You are identified as \x02%s\x02.' % identified)
    else:
        utils.msg(irc, source, 'You are not identified as anyone.')
    utils.msg(irc, source, 'Operator access: \x02%s\x02' % bool(utils.isOper(irc, source)))

@utils.add_cmd
def identify(irc, source, args):
    """<username> <password>

    Logs in to PyLink using the configured administrator account."""
    try:
        username, password = args[0], args[1]
    except IndexError:
        utils.msg(irc, source, 'Error: Not enough arguments.')
        return
    # Usernames are case-insensitive, passwords are NOT.
    if username.lower() == conf['login']['user'].lower() and password == conf['login']['password']:
        realuser = conf['login']['user']
        irc.users[source].identified = realuser
        utils.msg(irc, source, 'Successfully logged in as %s.' % realuser)
        log.info("(%s) Successful login to %r by %s.",
                 irc.name, username, utils.getHostmask(irc, source))
    else:
        utils.msg(irc, source, 'Incorrect credentials.')
        u = irc.users[source]
        log.warning("(%s) Failed login to %r from %s.",
                    irc.name, username, utils.getHostmask(irc, source))

def listcommands(irc, source, args):
    """takes no arguments.

    Returns a list of available commands PyLink has to offer."""
    cmds = list(utils.bot_commands.keys())
    cmds.sort()
    utils.msg(irc, source, 'Available commands include: %s' % ', '.join(cmds))
    utils.msg(irc, source, 'To see help on a specific command, type \x02help <command>\x02.')
utils.add_cmd(listcommands, 'list')

@utils.add_cmd
def help(irc, source, args):
    """<command>

    Gives help for <command>, if it is available."""
    try:
        command = args[0].lower()
    except IndexError:  # No argument given, just return 'list' output
        listcommands(irc, source, args)
        return
    try:
        func = utils.bot_commands[command]
    except KeyError:
        utils.msg(irc, source, 'Error: Unknown command %r.' % command)
        return
    else:
        doc = func.__doc__
        if doc:
            lines = doc.split('\n')
            # Bold the first line, which usually just tells you what
            # arguments the command takes.
            lines[0] = '\x02%s %s\x02' % (command, lines[0])
            for line in lines:
                utils.msg(irc, source, line.strip())
        else:
            utils.msg(irc, source, 'Error: Command %r doesn\'t offer any help.' % command)
            return
