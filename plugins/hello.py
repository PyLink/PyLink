import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils

@utils.add_cmd
def hello(irc, source, args):
   utils.msg(irc, source, 'hello!')
