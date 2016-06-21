"""Setup module for PyLink IRC Services."""

from setuptools import setup, find_packages
from codecs import open
from os import path

curdir = path.abspath(path.dirname(__file__))

# FIXME: Convert markdown to RST
with open(path.join(curdir, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='pylinkirc',
    version='0.9.0-dev1',

    description='PyLink IRC Services',
    long_description=long_description,

    url='https://github.com/GLolol/PyLink',

    # Author details
    author='James Lu',
    author_email='GLolol@overdrivenetworks.com',

    # Choose your license
    license='MPL 2.0',

    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 3 - Alpha',

        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Topic :: Communications :: Chat :: Internet Relay Chat',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)',

        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],

    keywords='IRC services chat',
    install_requires=['pyyaml'],

    # Folders (packages of code)
    packages=['pylinkirc', 'pylinkirc.protocols', 'pylinkirc.plugins'],

    # Single modules. TODO: consider organizing this into a pylink/ folder
    py_modules=["classes", "conf", "coreplugin", "log", "structures", "utils", "world"],

    # Data files
    package_data={
        '': ['example-conf.yml'],
    },

    package_dir = {'pylinkirc': '.'},

    # Executable scripts
    scripts=["pylink"],
)
