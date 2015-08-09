# plugin_example.py: An example PyLink plugin.
# You can add copyright notices and license information here.

# These two lines add PyLink's root directory to the PATH, so that importing things like
# 'utils' and 'log' work.
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
from log import log

import random

# Example PRIVMSG hook that returns "hi there!" when PyLink's nick is mentioned
# in a channel.

# irc: The IRC object where the hook was called.
# source: The UID/numeric of the sender.
# command: The true command name where the hook originates. This may or may not be
#          the same as the name of the hook, depending on context.
# args: The hook data (a dict) associated with the command. The available data
#       keys differ by hook name (see the hooks reference for a list of which can
#       be used).
def hook_privmsg(irc, source, command, args):
    channel = args['target']
    text = args['text']
    if utils.isChannel(channel) and irc.pseudoclient.nick in text:
        utils.msg(irc, channel, 'hi there!')
        log.info('%s said my name on channel %s (PRIVMSG hook caught)' % (source, channel))
utils.add_hook(hook_privmsg, 'PRIVMSG')


# Example command function. @utils.add_cmd binds it to an IRC command of the same name,
# but you can also use a different name by specifying a second 'name' argument (see below).
@utils.add_cmd
# irc: The IRC object where the command was called.
# source: The UID/numeric of the calling user.
# args: A list of command args (excluding the command name) that the command was called with.
def randint(irc, source, args):
    """[<min>] [<max>]
    Returns a random number between <min> and <max>. <min> and <max> default
    to 1 and 10 respectively, if both aren't given."""
    try:
        rmin = args[0]
        rmax = args[1]
    except IndexError:
       rmin, rmax = 1, 10
    n = random.randint(rmin, rmax)
    utils.msg(irc, source, str(n))
# You can also bind a command function multiple times, to different command names via a
# second argument. Note that no checking is done at the moment to prevent multiple
# plugins from binding to the same command names (the older command just gets replaced
# by the new one!)
utils.add_cmd(randint, "random")
