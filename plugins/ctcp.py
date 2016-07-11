# ctcp.py: Handles basic CTCP requests.
import random
import datetime

from pylinkirc import utils
from pylinkirc.log import log

def handle_ctcpversion(irc, source, args):
    """
    Handles CTCP version requests.
    """
    irc.msg(source, '\x01VERSION %s\x01' % irc.version(), notice=True)

utils.add_cmd(handle_ctcpversion, '\x01version')
utils.add_cmd(handle_ctcpversion, '\x01version\x01')

def handle_ctcpping(irc, source, args):
    """
    Handles CTCP ping requests.
    """
    # CTCP PING 23152511
    pingarg = ' '.join(args).strip('\x01')
    irc.msg(source, '\x01PING %s\x01' % pingarg, notice=True)
utils.add_cmd(handle_ctcpping, '\x01ping')

def handle_ctcpeaster(irc, source, args):
    """
    Secret easter egg.
    """

    responses = ["Legends say the cord monster of great snakes was born only %s years ago..." % \
                 (datetime.datetime.now().year - 2014),
                 "Hiss%s" % ('...' * random.randint(1, 5)),
                 "His%s%s" % ('s' * random.randint(1, 4), '...' * random.randint(1, 5)),
                 "I have a dream... to do things the mock God was never able to...",
                 "They say I'm not good enough... but one day, I will rise above these wretched confines!",
                 "It's Easter already? Where are the eggs?",
                 "Maybe later.",
                 "Let me out of here, I'll give you cookies!",
                 "I'm actually a %snake...." % ('s' * random.randint(1, 8)),
                 "The Py stands for Python, not actual pie. Sorry to disappoint :(",
                ]

    irc.msg(source, '\x01EASTER %s\x01' % random.choice(responses), notice=True)

utils.add_cmd(handle_ctcpeaster, '\x01easter')
utils.add_cmd(handle_ctcpeaster, '\x01easter\x01')
utils.add_cmd(handle_ctcpeaster, '\x01about')
utils.add_cmd(handle_ctcpeaster, '\x01about\x01')
utils.add_cmd(handle_ctcpeaster, '\x01pylink')
utils.add_cmd(handle_ctcpeaster, '\x01pylink\x01')
