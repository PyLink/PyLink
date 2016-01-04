# PyLink

PyLink is an extensible, plugin-based IRC services framework written in Python. It aims to be:

1) a replacement for the now-defunct Janus.

2) a versatile framework and gateway to IRC.

## Support

**PyLink is a work in progress and thus may be very unstable**! No warranty is provided if this completely wrecks your network and causes widespread rioting amongst your users!

That said, please report any bugs you find to the [issue tracker](https://github.com/GLolol/PyLink/issues). Pull requests are open if you'd like to contribute, though new stuff generally goes to the **devel** branch.

You can also find support via our IRC channel: `#PyLink at irc.overdrivenetworks.com` ([webchat](https://webchat.overdrivenetworks.com/?channels=PyLink,dev)). Ask your questions and be patient for a response.

## Dependencies

* Python 3.4+
* PyYAML (`pip install pyyaml`)
* *For the relay plugin*: expiringdict (`pip install expiringdict`)
* *For the changehost and opercmds plugins*: ircmatch (`pip install ircmatch`)

### Supported IRCds

* InspIRCd 2.0.x - module `inspircd`
* charybdis (3.5.x / git master) - module `ts6`
* Elemental-IRCd (6.6.x / git master) - module `ts6`
* UnrealIRCd 4.x (**experimental**) - module `unreal` (*NOT* Unreal 3.2 or lower)

## Setup

1) Rename `example-conf.yml` to `config.yml` and configure your instance there. Note that the configuration format isn't finalized yet - this means that your configuration may break in an update!

2) Run `./pylink` from the command line.

3) Profit???
