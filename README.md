# PyLink IRC Services

[webchatlink]: https://webchat.overdrivenetworks.com/?channels=PyLink

[![PyPI version](https://img.shields.io/pypi/v/pylinkirc.svg?maxAge=2592000)](https://pypi.python.org/pypi/pylinkirc/)
[![PyPI supported Python versions](https://img.shields.io/pypi/pyversions/pylinkirc.svg?maxAge=2592000)](https://www.python.org/downloads/)
[![PyPi license](https://img.shields.io/pypi/l/pylinkirc.svg?maxAge=2592000)](LICENSE.MPL2)
[![Live chat](https://img.shields.io/badge/IRC-live%20chat%20%C2%BB-green.svg)][webchatlink]

PyLink is an extensible, plugin-based IRC services framework written in Python. It aims to be:

1) a replacement for the now-defunct Janus.

2) a versatile framework for developing IRC services.

PyLink and any bundled software are licensed under the Mozilla Public License, version 2.0 ([LICENSE.MPL2](LICENSE.MPL2)). The corresponding documentation in the [docs/](docs/) folder is licensed under the Creative Attribution-ShareAlike 4.0 International License. ([LICENSE.CC-BY-SA-4.0](LICENSE.CC-BY-SA-4.0))

## Support

**First, MAKE SURE you've read the [FAQ](docs/faq.md)!**

**When upgrading between major versions, remember to read the [release notes](RELNOTES.md) for any breaking changes!**

Please report any bugs you find to the [issue tracker](https://github.com/GLolol/PyLink/issues). Pull requests are open if you'd like to contribute, though new stuff generally goes to the **devel** branch.

You can also find support via our IRC channel at `#PyLink @ irc.overdrivenetworks.com `([webchat][webchatlink]). Ask your questions and be patient for a response.

## Installation

### Installing from source

1) First, make sure the following dependencies are met:

    * Python 3.4+
    * Setuptools (`pip3 install setuptools`)
    * PyYAML (`pip3 install pyyaml`)
    * ircmatch (`pip3 install ircmatch`)
    * *For password encryption*: Passlib (`pip3 install passlib`)
    * *For the servprotect plugin*: expiringdict (`pip3 install expiringdict`)

2) Clone the repository: `git clone https://github.com/GLolol/PyLink && cd PyLink`

3) Pick your branch.
    * By default you'll be on the **master** branch, which contains the latest stable code. This branch is recommended for production networks that don't require new features or intensive bug fixes as they are developed.
    * The **devel** branch is where active development goes, and it can be accessed by running `git checkout devel` in your Git tree.

4) Install PyLink using `python3 setup.py install` (global install) or `python3 setup.py install --user` (local install)
    * Note: `--user` is a *literal* string; *do not* replace it with your username.
    *  **Whenever you switch branches or update PyLink's sources via `git pull`, you will need to re-run this command for changes to apply!**

### Installing via PyPI (stable branch only)
1) Make sure you're running the right pip command: on most distros, pip for Python 3 uses the command `pip3`.

2) Run `pip3 install pylinkirc` to download and install PyLink. pip will automatically resolve dependencies.

3) Download or copy https://github.com/GLolol/PyLink/blob/master/example-conf.yml for an example configuration.

### Installing via Ubuntu PPA (14.04/Trusty and above)

Unofficial Ubuntu packages for PyLink are available via two PPAs for Ubuntu 14.04 LTS (trusty) and above.

Upon installing the `pylink` package, example configuration and docs will be in `/usr/share/doc/pylink/examples` and `/usr/share/doc/pylink/docs` respectively. You can also install a local copy of the [PyLink API reference](https://pylink.github.io/) through the `pylink-doc` package.

- Stable releases: [PyLink Stable PPA](https://launchpad.net/~tacocat/+archive/ubuntu/pylink)
- Nightly builds (devel branch): [PyLink Nightly Builds PPA](https://launchpad.net/~tacocat/+archive/ubuntu/pylink-nightly)

## Configuration

1) Rename `example-conf.yml` to `pylink.yml` (or a similarly named `.yml` file) and configure your instance there. Note that the configuration format isn't finalized yet - this means that your configuration may break in an update!

2) Run `pylink` from the command line. PyLink will load its configuration from `pylink.yml` by default, but you can override this by running `pylink` with a config argument (e.g. `pylink mynet.yml`).

## Supported IRCds

### Primary support

These IRCds (in alphabetical order) are frequently tested and well supported. If any issues occur, please file a bug on the issue tracker.

* [charybdis](https://github.com/charybdis-ircd/charybdis) (3.5+) - module `ts6`
* [InspIRCd](http://www.inspircd.org/) 2.0.x - module `inspircd`
    - For vHost setting to work, `m_chghost.so` must be loaded.
    - Supported channel, user, and prefix modes are negotiated on connect, but hotloading modules that change these is not supported. After changing module configuration, it is recommended to SQUIT PyLink to force a protocol renegotiation.
* [Nefarious IRCu](https://github.com/evilnet/nefarious2) (2.0.0+) - module `p10`
    - Note: Both account cloaks (user and oper) and hashed IP cloaks are optionally supported (HOST_HIDING_STYLE settings 0 to 3). Make sure you configure PyLink to match your IRCd settings.
* [UnrealIRCd](https://www.unrealircd.org/) 4.x (4.0.12+) - module `unreal`
    - UnrealIRCd 4.x before version 4.0.12 suffers from [bug #4890](https://bugs.unrealircd.org/view.php?id=4890) which causes hostname desyncs on servers not directly linked to PyLink (e.g. `pylink<->serverA<->serverB` creates desynced hostnames on server B). This problem is fixed by upgrading your IRCds.
    - Linking to UnrealIRCd 3.2 servers is only possible when using an UnrealIRCd 4.x server as a hub, with topology such as `pylink<->unreal4<->unreal3.2`. We nevertheless encourage you to upgrade so all your IRCds are running the same version.

### Extended support

Support for these IRCds exist, but are not tested as frequently and thoroughly. Bugs should be filed if there are any issues, though they may not always be fixed in a timely fashion.

* [Elemental-IRCd](https://github.com/Elemental-IRCd/elemental-ircd) (6.6.x / git master) - module `ts6`
* [InspIRCd](http://www.inspircd.org/) 3.0.x (git master) - module `inspircd`
* [IRCd-Hybrid](http://www.ircd-hybrid.org/) (8.2.x / svn trunk) - module `hybrid`
    - Note: for host changing support and optimal functionality, a `service{}` block / U-line should be added for PyLink on every IRCd across your network.
* [ircd-ratbox](http://www.ratbox.org/) (3.x) - module `ratbox`
    - Host changing is not supported on ircd-ratbox.
    - On ircd-ratbox, all known IPs of users will be shown in `/whois`, even if the client is a cloaked relay client: if you're paranoid about this, turn off Relay IP forwarding by setting the `relay_no_ips` option in the ratbox network's `server:` block.
* [IRCu](http://coder-com.undernet.org/) (u2.10.12.16+) - module `p10`
    - Host changing is not supported.
* [juno-ircd](https://github.com/cooper/yiria) (11.x / janet) - module `ts6` (see [configuration example](https://github.com/cooper/juno/blob/master/doc/ts6.md#pylink))
* [snircd](https://development.quakenet.org/) (1.3.x+) - module `p10`
    - Outbound host changing (i.e. for the `changehost` plugin) is not supported on P10 variants other than Nefarious.

Other TS6 and P10 variations may work, but are not officially supported.

### Clientbot

Since v1.0, PyLink supports connecting to IRCds as a relay bot and forwarding users back, similar to Janus' Clientbot. This can be useful if the IRCd a network used isn't supported, or if you want to relay certain channels without fully linking with a network.

For Relay to work properly with Clientbot, be sure to load the `relay_clientbot` plugin in conjunction with `relay`.
