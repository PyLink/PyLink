# commands.py: base PyLink commands
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils
from conf import conf
from log import log

@utils.add_cmd
def debug(irc, source, args):
    log.debug('user index: %s' % irc.users)
    log.debug('server index: %s' % irc.servers)
    log.debug('channels index: %s' % irc.channels)
    utils.msg(irc, source, 'Debug info printed to console.')

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
        u = irc.users[source]
        log.warning("(%s) Failed login to %r from user '%s!%s@%s' (UID %r).",
                    irc.name, username, u.nick, u.ident, u.host, u.uid)

def listcommands(irc, source, args):
    cmds = list(utils.bot_commands.keys())
    cmds.sort()
    utils.msg(irc, source, 'Available commands include: %s' % ', '.join(cmds))
utils.add_cmd(listcommands, 'list')
