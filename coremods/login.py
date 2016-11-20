"""
login.py - Implement login method
"""

from pylinkirc import conf, utils, world
from pylinkirc.log import log
from passlib.apps import custom_app_context as pwd_context

@utils.add_cmd
def login(user, password):
    # synonymous to identify()
    """<user> <password>
    login to PyLink Services"""
    # XXX: First see if the user exists in the config
    try:
        passhash = conf.conf['login']['accounts'][user]
    except KeyError:
        return False
        log.error("Account '%s' not found" % user)
    # XXX: if so then see if the user provided username and password
    # matches the one in the config.
    if verifyhash(password, passhash):
        return True
    else:
        return False

@utils.add_cmd
def mkpasswd(irc, source, args):
    # synonymous to /mkpasswd so prospective admins
    # can give their password without actually
    # showing it outright.
    """<password>
    hashes a password for use in pylink.yml"""
    # TODO: restrict to only certain users?
    # XXX: do we allow this to be public or restrict it
    # to a certain group of people.
    password=None
    try:
        password = args[0]
    except IndexError:
        irc.error("Not enough arguments. (Needs 1, password)")
    if password == None or password == "None":
        # technically we shouldn't end up with this running
        irc.error("password can not be empty")
        
    hashed_pass = pwd_context.encrypt("%s" % password)
    if verifyhash(password, hashed_pass):
        irc.reply(hashed_pass)

def verifyhash(password, passhash):
    if password:
        # ... good we have a password inputted
        # XXX: the greatest thing here is that the hash
        # is just a string either way, not a object with
        # a method to output the hash
        return pwd_context.verify(password, passhash)        

