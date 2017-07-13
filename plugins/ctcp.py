# ctcp.py: Handles basic CTCP requests.
import random
import datetime

from pylinkirc import utils
from pylinkirc.log import log

@utils.add_ctcp
def version(irc, source, args):
    """
    Handles CTCP version requests.
    """
    irc.msg(source, '\x01VERSION %s\x01' % irc.version(), notice=True)

@utils.add_ctcp
def ping(irc, source, args):
    """
    Handles CTCP ping requests.
    """
    # CTCP PING 23152511
    pingarg = ' '.join(args)
    irc.msg(source, '\x01PING %s\x01' % pingarg, notice=True)

@utils.add_ctcp
def easter(irc, source, args):
    """
    Secret easter egg.
    """

    responses = ["Legends say the cord monster was born only %s years ago..." % \
                 (datetime.datetime.now().year - 2014),
                 "Hiss%s" % ('...' * random.randint(1, 5)),
                 "His%s%s" % ('s' * random.randint(1, 4), '...' * random.randint(1, 5)),
                 "It's Easter already? Where are the eggs?",
                 "Maybe later.",
                 "Janus? Never heard of it.",
                 irc.version(),
                 "Let me out of here, I'll give you cookies!",
                 "About as likely as pigs flying.",
                 "Request timed out.",
                 "No actual pie here, sorry.",
                 "Hey, no loitering!",
                 "Hey, can you keep a secret? \x031,1 %s" % " " * random.randint(1,20),
                ]

    irc.msg(source, '\x01EASTER %s\x01' % random.choice(responses), notice=True)
    
utils.add_ctcp(easter, 'about')
utils.add_ctcp(easter, 'pylink')
