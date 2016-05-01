"""
structures.py - PyLink data structures module.

This module contains custom data structures that may be useful in various situations.
"""

import collections
import json

class KeyedDefaultdict(collections.defaultdict):
    """
    Subclass of defaultdict allowing the key to be passed to the default factory.
    """
    def __missing__(self, key):
        if self.default_factory is None:
            # If there is no default factory, just let defaultdict handle it
            super().__missing__(self, key)
        else:
            value = self[key] = self.default_factory(key)
            return value

class DataStore:
    # will come into play with subclassing and db version upgrading
    initial_version = 1

    def __init__(self, name, filename, db_format='json', save_frequency={'seconds': 30}):
        self.name = name

        self._filename = os.path.abspath(os.path.expanduser(filename))
        self._tmp_filename = self._filename + '.tmp'
        log.debug('(db:{}) database path set to {}'.format(self.name, self._filename))

        self._format = db_format
        log.debug('(db:{}) format set to {}'.format(self.name, self._format))

        self._save_frequency = timedelta(**save_frequency).total_seconds()
        log.debug('(db:{}) saving every {} seconds'.format(self.name, self._save_frequency))

    def create_or_load(self):
        log.debug('(db:{}) creating/loading datastore using {}'.format(self.name, self._format))

        if self._format == 'json':
            self._store = {}
            self._store_lock = threading.Lock()

            log.debug('(db:{}) loading json data store from {}'.format(self.name, self._filename))
            try:
                self._store = json.loads(open(self._filename, 'r').read())
            except (ValueError, IOError, FileNotFoundError):
                log.exception('(db:{}) failed to load existing db, creating new one in memory'.format(self.name))
                self.put('db.version', self.initial_version)
        else:
            raise Exception('(db:{}) Data store format [{}] not recognised'.format(self.name, self._format))

    def save_callback(self, starting=False):
        """Start the DB save loop."""
        if self._format == 'json':
            # don't actually save the first time
            if not starting:
                self.save()

            # schedule saving in a loop.
            self.exportdb_timer = threading.Timer(self._save_frequency, self.save_callback)
            self.exportdb_timer.name = 'PyLink {} save_callback Loop'.format(self.name)
            self.exportdb_timer.start()
        else:
            raise Exception('(db:{}) Data store format [{}] not recognised'.format(self.name, self._format))

    def save(self):
        log.debug('(db:{}) saving datastore'.format(self.name))
        if self._format == 'json':
            with open(self._tmp_filename, 'w') as store_file:
                store_file.write(json.dumps(self._store))
            os.rename(self._tmp_filename, self._filename)

    # single keys
    def __contains__(self, key):
        if self._format == 'json':
            return key in self._store

    def get(self, key, default=None):
        if self._format == 'json':
            return self._store.get(key, default)

    def put(self, key, value):
        if self._format == 'json':
            # make sure we can serialize the given data
            # so we don't choke later on saving the db out
            json.dumps(value)

            self._store[key] = value

            return True

    def delete(self, key):
        if self._format == 'json':
            try:
                with self._store_lock:
                    del self._store[key]
            except KeyError:
                # key is already gone, nothing to do
                ...

            return True

    # multiple keys
    def list_keys(self, prefix=None):
        """Return all key names. If prefix given, return only keys that start with it."""
        if self._format == 'json':
            keys = []

            with self._store_lock:
                for key in self._store:
                    if prefix is None or key.startswith(prefix):
                        keys.append(key)

            return keys

    def delete_keys(self, prefix):
        """Delete all keys with the given prefix."""
        if self._format == 'json':
            with self._store_lock:
                for key in tuple(self._store):
                    if key.startswith(prefix):
                        del self._store[key]
