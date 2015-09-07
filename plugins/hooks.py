# hooks.py: test of PyLink hooks
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils
from log import log

def hook_join(irc, source, command, args):
    channel = args['channel']
    users = args['users']
    log.info('%s joined channel %s (JOIN hook caught)' % (users, channel))
utils.add_hook(hook_join, 'JOIN')

def hook_privmsg(irc, source, command, args):
    channel = args['target']
    text = args['text']
    if utils.isChannel(channel) and irc.pseudoclient.nick in text:
        irc.msg(channel, 'hi there!')
        log.info('%s said my name on channel %s (PRIVMSG hook caught)' % (source, channel))
utils.add_hook(hook_privmsg, 'PRIVMSG')
