import os
import sys
import pathlib
import argparse
import configparser
import numpy as np

from pathlib import Path

from collections import OrderedDict
from xfusion import log

__author__ = "Francesco De Carlo"
__copyright__ = "Copyright (c) 2024, UChicago Argonne, LLC."
__docformat__ = 'restructuredtext en'
__all__ = ['config_to_list',
           'get_config_name',
           'log_values',
           'parse_known_args',
           'write']

CONFIG_FILE_NAME = os.path.join(str(pathlib.Path.home()), 'xfusion.conf')
    
SECTIONS = OrderedDict()

SECTIONS['general'] = {
    'config': {
        'default': CONFIG_FILE_NAME,
        'type': str,
        'help': "File name of configuration",
        'metavar': 'FILE'},
    'verbose': {
        'default': True,
        'help': 'Verbose output',
        'action': 'store_true'}}


SECTIONS['convert'] = {
    'dir-lo': {
        'default': "./train/train_sharp_bicubic/X4/",
        'type': Path,
        'help': 'name of the directory with the low resolution images',
        'metavar': 'FILE'},
    'dir-hi': {
        'default': "./train/train_sharp/",
        'type': Path,
        'help': 'name of the directory with the high resolution images',
        'metavar': 'FILE'},
    'out-dir-lo': {
        'default': ".",
        'type': Path,
        'help': 'name of the output directory for the low resolution images',
        'metavar': 'FILE'},
    'out-dir-hi': {
        'default': ".",
        'type': Path,
        'help': 'name of the output directory for the high resolution images',
        'metavar': 'FILE'},
    }


SECTIONS['train'] = {
    'dir-lo': {
        'default': "./train/lo/",
        'type': Path,
        'help': 'name of the directory with the low resolution images',
        'metavar': 'FILE'},
    'dir-hi': {
        'default': "./train/hi/",
        'type': Path,
        'help': 'name of the directory with the high resolution images',
        'metavar': 'FILE'},
    'opt' : {
        'default' : '.',
        'type': str,
        'help': "Path to option YAML file."},
    'launcher' : {
        'default' : 'none',
        'choices' : ['none', 'pytorch', 'slurm'],
        'help': "Job launcher."},
    'auto-resume': {
        'default': True,
        'help': "When set auto-resume is True",
        'action': 'store_true'},
     'opt' : {
        'default' : '.',
        'type': str,
        'help': "Path to option YAML file."},
     'local-rank' : {
        'default' : 0,
        'type': int,
        'help': "Local rank."},
    'force-yml': {
        'default': None,
        'help': "When set used the yml config file"},
    'is-train': {
        'default': True,
        'help': "When set train is True",
        'action': 'store_true'},
  }


CONVERT_PARAMS   = ('convert', )
TRAIN_PARAMS     = ('train', )
XFUSION_PARAMS   = ('convert', 'train', )

NICE_NAMES = ('General', 'Convert', 'Train')


def get_config_name():
    """Get the command line --config option."""
    name = CONFIG_FILE_NAME
    for i, arg in enumerate(sys.argv):
        if arg.startswith('--config'):
            if arg == '--config':
                return sys.argv[i + 1]
            else:
                name = sys.argv[i].split('--config')[1]
                if name[0] == '=':
                    name = name[1:]
                return name

    return name


def parse_known_args(parser, subparser=False):
    """
    Parse arguments from file and then override by the ones specified on the
    command line. Use *parser* for parsing and is *subparser* is True take into
    account that there is a value on the command line specifying the subparser.
    """
    if len(sys.argv) > 1:
        subparser_value = [sys.argv[1]] if subparser else []
        config_values = config_to_list(config_name=get_config_name())
        values = subparser_value + config_values + sys.argv[1:]
        #print(subparser_value, config_values, values)
    else:
        values = ""

    return parser.parse_known_args(values)[0]


def config_to_list(config_name=CONFIG_FILE_NAME):
    """
    Read arguments from config file and convert them to a list of keys and
    values as sys.argv does when they are specified on the command line.
    *config_name* is the file name of the config file.
    """
    result = []
    config = configparser.ConfigParser()

    if not config.read([config_name]):
        return []

    for section in SECTIONS:
        for name, opts in ((n, o) for n, o in SECTIONS[section].items() if config.has_option(section, n)):
            value = config.get(section, name)

            if value != '' and value != 'None':
                action = opts.get('action', None)

                if action == 'store_true' and value == 'True':
                    # Only the key is on the command line for this action
                    result.append('--{}'.format(name))

                if not action == 'store_true':
                    if opts.get('nargs', None) == '+':
                        result.append('--{}'.format(name))
                        result.extend((v.strip() for v in value.split(',')))
                    else:
                        result.append('--{}={}'.format(name, value))

    return result


class Params(object):
    def __init__(self, sections=()):
        self.sections = sections + ('general',)

    def add_parser_args(self, parser):
        for section in self.sections:
            for name in sorted(SECTIONS[section]):
                opts = SECTIONS[section][name]
                parser.add_argument('--{}'.format(name), **opts)

    def add_arguments(self, parser):
        self.add_parser_args(parser)
        return parser

    def get_defaults(self):
        parser = argparse.ArgumentParser()
        self.add_arguments(parser)

        return parser.parse_args('')


def write(config_file, args=None, sections=None):
    """
    Write *config_file* with values from *args* if they are specified,
    otherwise use the defaults. If *sections* are specified, write values from
    *args* only to those sections, use the defaults on the remaining ones.
    """
    config = configparser.ConfigParser()

    for section in SECTIONS:
        config.add_section(section)
        for name, opts in SECTIONS[section].items():
            if args and sections and section in sections and hasattr(args, name.replace('-', '_')):
                value = getattr(args, name.replace('-', '_'))
                if isinstance(value, list):
                    print(type(value), value)
                    value = ', '.join(value)
            else:
                value = opts['default'] if opts['default'] is not None else ''

            prefix = '# ' if value == '' else ''

            if name != 'config':
                config.set(section, prefix + name, str(value))
    with open(config_file, 'w') as f:
        config.write(f)


def log_values(args):
    """Log all values set in the args namespace.

    Arguments are grouped according to their section and logged alphabetically
    using the DEBUG log level thus --verbose is required.
    """
    args = args.__dict__

    for section, name in zip(SECTIONS, NICE_NAMES):
        entries = sorted((k for k in args.keys() if k.replace('_', '-') in SECTIONS[section]))

        if entries:
            log.info(name)

            for entry in entries:
                value = args[entry] if args[entry] is not None else "-"
                log.info("  {:<16} {}".format(entry, value))
