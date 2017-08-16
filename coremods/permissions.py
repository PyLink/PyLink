"""
permissions.py - Permissions Abstraction for PyLink IRC Services.
"""

from collections import defaultdict
import threading

# Global variables: these store mappings of hostmasks/exttargets to lists of permissions each target has.
default_permissions = defaultdict(set)
permissions = defaultdict(set)

# Only allow one thread to change the permissions index at once.
permissions_lock = threading.Lock()

from pylinkirc import conf, utils
from pylinkirc.log import log

def reset_permissions():
    """
    Loads the permissions specified in the permissions: block of the PyLink configuration,
    if such a block exists. Otherwise, fallback to the default permissions specified by plugins.
    """
    with permissions_lock:
        global permissions
        log.debug('permissions.reset_permissions: old perm list: %s', permissions)

        new_permissions = default_permissions.copy()
        log.debug('permissions.reset_permissions: new_permissions %s', new_permissions)
        if not conf.conf.get('permissions_merge_defaults', True):
            log.debug('permissions.reset_permissions: clearing perm list due to permissions_merge_defaults set False.')
            new_permissions.clear()

        # Convert all perm lists to sets.
        for k, v in conf.conf.get('permissions', {}).items():
            new_permissions[k] |= set(v)

        log.debug('permissions.reset_permissions: new_permissions %s', new_permissions)
        permissions.clear()
        permissions.update(new_permissions)
        log.debug('permissions.reset_permissions: new perm list: %s', permissions)
resetPermissions = reset_permissions

def add_default_permissions(perms):
    """Adds default permissions to the index."""
    with permissions_lock:
        global default_permissions
        for target, permlist in perms.items():
            default_permissions[target] |= set(permlist)
addDefaultPermissions = add_default_permissions

def remove_default_permissions(perms):
    """Remove default permissions from the index."""
    with permissions_lock:
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
    if irc.match_host('$pylinkacc', uid) and conf.conf['login'].get('user'):
        log.debug('permissions: overriding permissions check for old-style admin user %s',
                  irc.get_hostmask(uid))
        return True

    # Iterate over all hostmask->permission list mappings.
    for host, permlist in permissions.copy().items():
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

# Reset our permissions list on startup.
reset_permissions()
