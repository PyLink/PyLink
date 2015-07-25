# PyLink

PyLink is an extensible, plugin-based IRC PseudoService written in Python. It aims to be a replacement for the now-defunct Janus.

## Usage

**PyLink is a work in progress and thus may be very unstable**! No warranty is provided if this completely wrecks your network and causes widespread rioting throughout your user base!

That said, please report any bugs you find to the [issue tracker](https://github.com/GLolol/PyLink/issues). Pull requests are open if you'd like to contribute.

### Dependencies

Dependencies currently include:

* Python 3.4+
* PyYAML (`pip install pyyaml` or `apt-get install python3-yaml`)

#### Supported IRCds

* InspIRCd 2.0.x - module: `inspircd`
* charybdis (3.5.x / git master) - module: `ts6` (**experimental**)

### Installation

1) Rename `config.yml.example` to `config.yml` and configure your instance there. Not all options are properly implemented yet, and the configuration schema isn't finalized yet - this means your configuration may break in an update!

2) Run `main.py` from the command line.

3) Profit???
