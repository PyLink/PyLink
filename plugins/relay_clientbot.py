# relay_clientbot.py: Clientbot extensions for Relay

from pylinkirc import utils
from pylinkirc.log import log

def handle_cbmessages(irc, source, command, args):
    target = args['target']
    text = args['text']
    if irc.pseudoclient:
        # TODO: configurable format
        irc.proto.message(irc.pseudoclient.uid, target,
                          '<%s> %s' % (irc.getFriendlyName(source), text))

utils.add_hook(handle_cbmessages, 'CLIENTBOT_MESSAGE')
