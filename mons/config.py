import configparser
import os

from click import get_app_dir, edit
from contextlib import AbstractContextManager

config_dir = get_app_dir('mons', roaming=False)

CONFIG_FILE = 'config.ini'
INSTALLS_FILE = 'installs.ini'
CACHE_FILE = 'cache.ini'

#Config, Installs, Cache
Config_DEFAULT = {}
Installs_DEFAULT = {
    'PreferredBranch': 'stable',
}
Cache_DEFAULT = {}

def loadConfig(file, default):
    config = configparser.ConfigParser()
    config_file = os.path.join(config_dir, file)
    if os.path.isfile(config_file):
        config.read(config_file)
    else:
        config['DEFAULT'] = default
        os.makedirs(config_dir, exist_ok=True)
        with open(config_file, 'x') as f:
            config.write(f)
    return config

def saveConfig(config, file):
    with open(os.path.join(config_dir, file), 'w') as f:
        config.write(f)

def editConfig(config: configparser.ConfigParser, file):
    saveConfig(config, file)
    edit(
        filename=os.path.join(config_dir, file), 
        editor=config.get('user', 'editor', fallback=None)
    )
    return loadConfig(file, config['DEFAULT'])


class UserInfo(AbstractContextManager):
    def __enter__(self):
        self.config = loadConfig(CONFIG_FILE, Config_DEFAULT)
        self.installs = loadConfig(INSTALLS_FILE, Installs_DEFAULT)
        self.cache = loadConfig(CACHE_FILE, Cache_DEFAULT)
        if not self.config.has_section('user'):
            self.config['user'] = {}
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        saveConfig(self.config, CONFIG_FILE)
        saveConfig(self.installs, INSTALLS_FILE)
        saveConfig(self.cache, CACHE_FILE)
