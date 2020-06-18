"""
permissions.py - Permissions Abstraction for PyLink IRC Services.
"""

from collections import defaultdict

from pylinkirc import conf, utils
from pylinkirc.log import log

__all__ = ['default_permissions', 'add_default_permissions',
           'remove_default_permissions', 'check_permissions']

# Global variables: these store mappings of hostmasks/exttargets to lists of permissions each target has.
default_permissions = defaultdict(set)


def add_default_permissions(perms):
    """Adds default permissions to the index."""
    global default_permissions
    for target, permlist in perms.items():
        default_permissions[target] |= set(permlist)
addDefaultPermissions = add_default_permissions

def remove_default_permissions(perms):
    """Remove default permissions from the index."""
    global default_permissions
    for target, permlist in perms.items():
        default_permissions[target] -= set(permlist)
removeDefaultPermissions = remove_default_permissions

def check_permissions(irc, uid, perms, also_show=[]):
    """
    Checks permissions of the caller. If the caller has any of the permissions listed in perms,
    this function returns True. Otherwise, NotAuthorizedError is raised.
    """
    # For old (< 1.1 login blocks):
    # If the user is logged in, they automatically have all permissions.
    olduser = conf.conf['login'].get('user')
    if olduser and irc.match_host('$pylinkacc:%s' % olduser, uid):
        log.debug('permissions: overriding permissions check for old-style admin user %s',
                  irc.get_hostmask(uid))
        return True

    permissions = defaultdict(set)
    # Enumerate the configured permissions list.
    for k, v in (conf.conf.get('permissions') or {}).items():
        permissions[k] |= set(v)

    # Merge in default permissions if enabled.
    if conf.conf.get('permissions_merge_defaults', True):
        for k, v in default_permissions.items():
            permissions[k] |= v

    for host, permlist in permissions.items():
        log.debug('permissions: permlist for %s: %s', host, permlist)
        if irc.match_host(host, uid):
            # Now, iterate over all the perms we are looking for.
            for perm in permlist:
                # Use irc.match_host to expand globs in an IRC-case insensitive and wildcard
                # friendly way. e.g. 'xyz.*.#Channel\' will match 'xyz.manage.#channel|' on IRCds
                # using the RFC1459 casemapping.
                log.debug('permissions: checking if %s glob matches anything in %s', perm, permlist)
                if any(irc.match_host(perm, p) for p in perms):
                    return True
    raise utils.NotAuthorizedError("You are missing one of the following permissions: %s" %
                                   (', '.join(perms+also_show)))
checkPermissions = check_permissions
