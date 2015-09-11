# plugin_example.py: An example PyLink plugin.

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
    # irc.pseudoclient stores the IrcUser object of the main PyLink client.
    # (i.e. the user defined in the bot: section of the config)
    if utils.isChannel(channel) and irc.pseudoclient.nick in text:
        irc.msg(channel, 'hi there!')
        log.info('%s said my name on channel %s (PRIVMSG hook caught)' % (source, channel))
utils.add_hook(hook_privmsg, 'PRIVMSG')


# Example command function. @utils.add_cmd binds it to an IRC command of the same name,
# but you can also use a different name by specifying a second 'name' argument (see below).
@utils.add_cmd
# irc: The IRC object where the command was called.
# source: The UID/numeric of the calling user.
# args: A list of command args (excluding the command name) that the command was called with.
def randint(irc, source, args):
    # The docstring here is used as command help by the 'help' command, and formatted using the
    # same line breaks as the raw string. You shouldn't make this text or any one line too long,
    # to prevent flooding users or getting long lines cut off.
    """[<min>] [<max>]
    Returns a random number between <min> and <max>. <min> and <max> default
    to 1 and 10 respectively, if both aren't given."""
    try:
        rmin = args[0]
        rmax = args[1]
    except IndexError:
       rmin, rmax = 1, 10
    n = random.randint(rmin, rmax)
    irc.msg(source, str(n))
# You can also bind a command function multiple times, and/or to different command names via a
# second argument.
# Note: no checking is done at the moment to prevent multiple plugins from binding to the same
# command name. The older command just gets replaced by the new one!
utils.add_cmd(randint, "random")
