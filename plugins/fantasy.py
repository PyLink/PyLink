# fantasy.py: Adds FANTASY command support, to allow calling commands in channels
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
from log import log

def handle_fantasy(irc, source, command, args):
    """Fantasy command handler."""
    try:
        prefix = irc.botdata["prefix"]
    except KeyError:
        log.warning("(%s) Fantasy prefix was not set in configuration - "
                    "fantasy commands will not work!", irc.name)
        return
    channel = args['target']
    text = args['text']
    # Conditions:
    # 1) Message target is a channel,
    # 2) Message starts with our fantasy prefix,
    # 3) The main PyLink client is in the channel.
    # 4) The sender is NOT a PyLink client (prevents message loops).
    if utils.isChannel(channel) and text.startswith(prefix) and \
            irc.pseudoclient.uid in irc.channels[channel].users and not \
            utils.isInternalClient(irc, source):
        # Cut off the length of the prefix from the text.
        text = text[len(prefix):]
        # Set the last called in variable to the channel, so replies (from
        # supporting plugins) get forwarded to it.
        irc.called_by = channel
        irc.callCommand(source, text)
utils.add_hook(handle_fantasy, 'PRIVMSG')
