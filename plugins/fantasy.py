# fantasy.py: Adds FANTASY command support, to allow calling commands in channels
from pylinkirc import utils, world
from pylinkirc.log import log

def handle_fantasy(irc, source, command, args):
    """Fantasy command handler."""

    if not irc.connected.is_set():
        # Break if the IRC network isn't ready.
        return

    respondtonick = irc.botdata.get("respondtonick")

    channel = args['target']
    orig_text = args['text']

    if utils.isChannel(channel) and not irc.isInternalClient(source):
        # The following conditions must be met for an incoming message for
        # fantasy to trigger:
        #   1) The message target is a channel.
        #   2) A PyLink service client exists in the channel.
        #   3) The message starts with one of our fantasy prefixes.
        #   4) The sender is NOT a PyLink client (this prevents infinite
        #      message loops).
        for botname, sbot in world.services.copy().items():
            if botname not in world.services:  # Bot was removed during iteration
                continue
            log.debug('(%s) fantasy: checking bot %s', irc.name, botname)
            servuid = sbot.uids.get(irc.name)
            if servuid in irc.channels[channel].users:

                # Try to look up a prefix specific for this bot in
                # bot: prefixes: <botname>, falling back to the default prefix if not
                # specified.
                prefixes = [irc.botdata.get('prefixes', {}).get(botname) or
                            irc.botdata.get('prefix')]

                # If responding to nick is enabled, add variations of the current nick
                # to the prefix list: "<nick>," and "<nick>:"
                nick = irc.users[servuid].nick

                if respondtonick:
                    prefixes += [nick+',', nick+':']

                if not any(prefixes):
                    # We finished with an empty prefixes list, meaning fantasy is misconfigured!
                    log.warning("(%s) Fantasy prefix for bot %s was not set in configuration - "
                                "fantasy commands will not work!", irc.name, botname)
                    continue

                for prefix in prefixes:  # Cycle through the prefixes list we finished with.
                     if prefix and orig_text.startswith(prefix):

                        # Cut off the length of the prefix from the text.
                        text = orig_text[len(prefix):]

                        # Finally, call the bot command and loop to the next bot.
                        sbot.call_cmd(irc, source, text, called_in=channel)
                        continue

utils.add_hook(handle_fantasy, 'PRIVMSG')
