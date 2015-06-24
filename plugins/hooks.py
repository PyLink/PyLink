# hooks.py: test of PyLink hooks
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils

def hook_join(irc, source, command, args):
    print('%s joined channel %s (join hook caught)' % (source, args[0]))
utils.add_hook(hook_join, 'join')

def hook_msg(irc, source, command, args):
    if utils.isChannel(args[0]) and irc.pseudoclient.nick in args[1]:
        utils.msg(irc, args[0], 'hi there!')
        print('%s said my name on channel %s (msg hook caught)' % (source, args[0]))
utils.add_hook(hook_msg, 'msg')
