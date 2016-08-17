# PyLink

PyLink is an extensible, plugin-based IRC services framework written in Python. It aims to be:

1) a replacement for the now-defunct Janus.

2) a versatile framework and gateway to IRC.

PyLink and any bundled software are licensed under the Mozilla Public License, version 2.0 ([LICENSE.MPL2](LICENSE.MPL2)). The corresponding documentation in the [docs/](docs/) folder is licensed under the Creative Attribution-ShareAlike 4.0 International License. ([LICENSE.CC-BY-SA-4.0](LICENSE.CC-BY-SA-4.0))

## Support

**First, MAKE SURE you've read the [FAQ](docs/faq.md)!**

**When upgrading between major versions, remember to read the [release notes](RELNOTES.md) for any breaking changes!**

Please report any bugs you find to the [issue tracker](https://github.com/GLolol/PyLink/issues). Pull requests are open if you'd like to contribute, though new stuff generally goes to the **devel** branch.

You can also find support via our IRC channels: `#PyLink @ irc.overdrivenetworks.com `([webchat](https://webchat.overdrivenetworks.com/?channels=PyLink,dev)) or `#PyLink @ chat.freenode.net`. Ask your questions and be patient for a response.

## Installation

### Installing from source (recommended)

First, make sure the following dependencies are met:

* Python 3.4+
* Setuptools (`pip3 install setuptools`)
* PyYAML (`pip3 install pyyaml`)
* [ircmatch](https://github.com/mammon-ircd/ircmatch) (`pip3 install ircmatch`)
* *For the servprotect plugin*: [expiringdict](https://github.com/mailgun/expiringdict) (install this from source; installation is broken in pip due to [mailgun/expiringdict#13](https://github.com/mailgun/expiringdict/issues/13))

1) Clone the repository: `git clone https://github.com/GLolol/PyLink && cd PyLink`

2) Install PyLink using `python3 setup.py install` (global install) or `python3 setup.py install --user` (local install)
    - Note: `--user` is a *literal* string; *do not* replace it with your username.

### Installing via PyPI
1) Make sure you're running the right pip command: on most distros, pip for Python3 uses the command `pip3`.

2) Run `pip3 install pylinkirc` to download and install PyLink. pip will automatically resolve dependencies.

3) Download or copy https://github.com/GLolol/PyLink/blob/master/example-conf.yml for an example configuration.

## Configuration

1) Rename `example-conf.yml` to `pylink.yml` (or a similarly named `.yml` file) and configure your instance there. Note that the configuration format isn't finalized yet - this means that your configuration may break in an update!

2) Run `pylink` from the command line. PyLink will load its configuration from `pylink.yml` by default, but you can override this by running `pylink` with a config argument (e.g. `pylink mynet.yml`).

## Supported IRCds

### Primary support

These IRCds (in alphabetical order) are frequently tested and well supported. If any issues occur, please file a bug on the issue tracker.

* [charybdis](http://charybdis.io/) (3.5+ / git master) - module `ts6`
* [InspIRCd](http://www.inspircd.org/) 2.0.x - module `inspircd`
* [UnrealIRCd](https://www.unrealircd.org/) 4.x - module `unreal`
    - Note: Support for mixed UnrealIRCd 3.2/4.0 networks is experimental, and requires you to enable a `mixed_link` option in the configuration. This may in turn void your support.

### Extended support

Support for these IRCds exist, but are not tested as frequently and thoroughly. Bugs should be filed if there are any issues, though they may not always be fixed in a timely fashion.

* [Elemental-IRCd](https://github.com/Elemental-IRCd/elemental-ircd) (6.6.x / git master) - module `ts6`
* InspIRCd 2.2 (git master) - module `inspircd`
* [IRCd-Hybrid](http://www.ircd-hybrid.org/) (8.2.x / svn trunk) - module `hybrid`
    - Note: for host changing support and optimal functionality, a `service{}` block / U-line should be added for PyLink on every IRCd across your network.
* [juno-ircd](https://github.com/cooper/yiria) (10.x / yiria) - module `ts6` (with elemental-ircd modes)
* [Nefarious IRCu](https://github.com/evilnet/nefarious2) (2.0.0+) - module `nefarious`
    - Note: Both account cloaks (user and oper) and hashed IP cloaks are optionally supported (HOST_HIDING_STYLE settings 0 to 3). Make sure you configure PyLink to match your IRCd settings.
    - For optimal functionality (mode overrides in relay, etc.), a `UWorld{}` block / U-line should be added for every server that PyLink spawns.

Other TS6 and P10 variations may work, but are not officially supported.
