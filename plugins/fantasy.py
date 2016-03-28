# fantasy.py: Adds FANTASY command support, to allow calling commands in channels
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
from log import log

def handle_fantasy(irc, source, command, args):
    """Fantasy command handler."""

    if not irc.connected.is_set():
        # Break if the IRC network isn't ready.
        return

    try:  # First, try to fetch the config-defined prefix.
        prefixes = [irc.botdata["prefix"]]
    except KeyError:  # Config option is missing.
        prefixes = []

    if irc.botdata.get("respondtonick"):
        # If responding to nick is enabled, add variations of the current nick
        # to the prefix list: "<nick>," and "<nick>:"
        nick = irc.pseudoclient.nick
        prefixes += [nick+',', nick+':']

    if not prefixes:
        # We finished with an empty prefixes list, meaning fantasy is misconfigured!
        log.warning("(%s) Fantasy prefix was not set in configuration - "
                    "fantasy commands will not work!", irc.name)
        return

    channel = args['target']
    text = args['text']
    for prefix in prefixes:  # Cycle through the prefixes list we finished with.
        # The following conditions must be met for an incoming message for
        # fantasy to trigger:
        #   1) The message target is a channel.
        #   2) The message starts with one of our fantasy prefixes.
        #   3) The main PyLink client is in the channel where the command was
        #      called.
        #   4) The sender is NOT a PyLink client (this prevents infinite
        #      message loops).
        if utils.isChannel(channel) and text.startswith(prefix) and \
                irc.pseudoclient.uid in irc.channels[channel].users and not \
                irc.isInternalClient(source):

            # Cut off the length of the prefix from the text.
            text = text[len(prefix):]

            # Set the "place last command was called in" variable to the
            # channel in question, so that replies from fantasy-supporting
            # plugins get forwarded to it.
            irc.called_by = channel

            # Finally, call the bot command and break.
            irc.callCommand(source, text)
            break

utils.add_hook(handle_fantasy, 'PRIVMSG')
