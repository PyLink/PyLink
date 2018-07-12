# The Permissions API

Permissions were introduced in PyLink 1.0 as a way for plugins to manage command access, replacing the old `irc.checkAuthenticated()`. The permissions system in PyLink is fairly simple, globally assigning a list of permissions to each hostmask/exttarget.

Permissions conventionally take the format `pluginname.commandname.optional_extra_portion(s)`, and support globs† in matching. Permission nodes are case-insensitive and casemapping aware, but are defined as being all lowercase for consistency.

The permissions module is available as `pylinkirc.coremods.permissions`. Usually, plugins import it this format:

```python
from pylinkirc.coremods import permissions
```

† The globbing used by the permissions module is just generic IRC-style globbing. For example, anyone with `*`, `perm.*`, `perm.?`, `*.1`, etc. in their permissions list will be allowed to use a command checking for a permission named `perm.1`.

## Checking for permissions

Individual functions check for permissions using the `permissions.checkPermissions(irc, source, ['perm.1', 'perm.2'])` function, where the last argument is an OR'ed list of permissions matched against a list of permission string globs that a user may have. If the user has any of the permissions in the permission list, they will be allowed to call the command. This function returns `True` when a permission check passes, and raises `utils.NotAuthorizedError` when a check fails, automatically aborting the execution of the command function.

`utils.NotAuthorizedError` can be treated like any other exception, so it's possible to wrap it around `try:` / `except:` for more complex access checking ([example in the Automode plugin](https://github.com/jlu5/PyLink/blob/1.1.1/plugins/automode.py#L64-L68)).

## Assigning default permissions

Plugins are also allowed to assign default permissions to their commands, though this should be used sparingly to ensure maximum configurability (explicitly removing permissions isn't supported yet). Default permissions are specified as a `dict` mapping targets to permission lists.

Example of this in [Automode](https://github.com/jlu5/PyLink/blob/1.1-alpha1/plugins/automode.py#L38-L39):

```python
# The default set of Automode permissions.
default_permissions = {"$ircop": ['automode.manage.relay_owned', 'automode.sync.relay_owned',
                                  'automode.list']}
```

Default permissions are registered in a plugin's `main()` function via `permissions.addDefaultPermissions(default_permissions_dict)`, and should always be erased on `die()` through `permissions.removeDefaultPermissions(default_permissions_dict)`.
