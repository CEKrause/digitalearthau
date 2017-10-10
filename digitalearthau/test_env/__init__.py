"""
Set up and tear down test database environments at the NCI.
"""
import subprocess
import configparser
import pathlib
import sys
import logging

import click

from datacube.config import LocalConfig, DATACUBE_SECTION, _DEFAULT_CONF
from datacube.index import index_connect
from datacube.api.query import Query
from datacube.utils import intersects
from datacube.scripts.dataset import load_rules_from_types
from datacube.scripts.dataset import index_dataset_paths
from datacube.ui.expression import parse_expressions
from digitalearthau.system import init_dea

TESTDB_CONF_FILE = pathlib.Path(__file__).parent / "test_db.conf"
PRODDB_CONF_FILE = pathlib.Path(__file__).parent / "prod_db.conf"

CREATE_DATABASE_TEMPLATE = """
CREATE DATABASE {db_database}
WITH
OWNER = agdc_admin
ENCODING = 'UTF8'
LC_COLLATE = 'en_AU.UTF-8'
LC_CTYPE = 'en_AU.UTF-8'
TABLESPACE = pg_default
CONNECTION LIMIT = -1;

GRANT ALL ON DATABASE {db_database} TO agdc_admin;
GRANT CONNECT, TEMPORARY ON DATABASE {db_database} TO PUBLIC;
GRANT ALL ON DATABASE {db_database} TO test;
ALTER DATABASE {db_database} SET search_path TO "$user", public, agdc;
"""

TERMINATE_BACKEND_TEMPLATE = """
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '{db_database}';
"""

DROP_DATABASE_TEMPLATE = """
DROP DATABASE IF EXISTS {db_database};
"""

# for this exercise, prevent DuplicateRecordError warnings from showing up
_LOG = logging.getLogger('datacube')
_LOG.setLevel(logging.ERROR)
_OUT = logging.StreamHandler()
_OUT.setLevel(logging.ERROR)
_LOG.addHandler(_OUT)


def run_shell(*args, **kwargs):
    """ Subprocess with I/O done in the UTF-8 encoding. """
    return subprocess.check_output(*args, encoding='UTF-8', **kwargs)


def psql_command(command, local_config, maintenance_db='postgres'):
    """
    Feed ``command`` to the PostgreSQL server specified in ``local_config``.
    """
    hostname = local_config.db_hostname
    port = local_config.db_port

    # seems like you have to connect to a database
    # and that the maintenance database is usually called postgres
    return run_shell(["psql", "-h", hostname, "-p", port, maintenance_db],
                     input=command)


def read_config(config_file):
    """ Store relevant data from ``config_file`` into a ``dict`` object. """
    config = configparser.ConfigParser()
    config.read_string(_DEFAULT_CONF)

    with open(config_file) as fl:
        config.read_file(fl)

    datacube_section = dict(config[DATACUBE_SECTION])
    local_config = LocalConfig(config,
                               files_loaded=[str(config_file)])

    return {'config_file': config_file,
            'datacube_section': datacube_section,
            'local_config': local_config}


@click.group()
@click.option('-C', '--config-file',
              default=TESTDB_CONF_FILE,
              type=click.Path(exists=True, dir_okay=False),
              help="Test database configuration file (default: test_db.conf).")
@click.pass_context
def cli(ctx, config_file):
    """ Set up and tear down test database environments at the NCI. """
    if ctx.obj is None:
        ctx.obj = {}
    ctx.obj['test_db'] = read_config(config_file)


@cli.command()
@click.option('--init-users/--no-init-users',
              is_flag=True, default=True,
              help="Include user roles and grants (default: true).")
@click.pass_context
def setup(ctx, init_users):
    """ Setup a test database environment. """
    test_db = ctx.obj['test_db']

    # should these go into a log?
    command = CREATE_DATABASE_TEMPLATE.format(**test_db['datacube_section'])
    click.echo(psql_command(command, test_db['local_config']))

    # do not validate database (nothing there yet)
    index = index_connect(test_db['local_config'],
                          application_name='setup-test-environment',
                          validate_connection=False)

    init_dea(index, init_users)


@cli.command()
@click.pass_context
def teardown(ctx):
    """ Teardown a test database environment. """
    test_db = ctx.obj['test_db']

    # should these go into a log?
    command = TERMINATE_BACKEND_TEMPLATE.format(**test_db['datacube_section'])
    click.echo(psql_command(command, test_db['local_config']))

    command = DROP_DATABASE_TEMPLATE.format(**test_db['datacube_section'])
    click.echo(psql_command(command, test_db['local_config']))


def expression_parser(ctx, param, value):
    """ Parse query expressions like ``datacube-core``. """
    return parse_expressions(*list(value))


def find_datasets_lazy(index, **kwargs):
    """
    Find datasets matching query. An unfortunate replica
    of ``datacube.Datacube.find_datasets`` that searches
    lazily. Could be moved to ``datacube.Datacube``.
    """
    query = Query(index, **kwargs)
    if not query.product:
        # no idea why it is a `RuntimeError` in the original
        raise ValueError("must specify a product")

    # does search exists and is lazy?
    datasets = index.datasets.search(**query.search_terms)

    polygon = query.geopolygon
    if polygon:
        for dataset in datasets:
            if intersects(polygon.to_crs(dataset.crs), dataset.extent):
                yield dataset
    else:
        yield from datasets


def normalize_uri(uri):
    """ Remove the 'file://' prefix from URIs. """
    prefix = 'file://'
    if uri.startswith(prefix):
        return uri[len(prefix):]
    else:
        return uri


@cli.command(short_help="Migrate datasets.")
@click.option('-S', '--source-config',
              default=PRODDB_CONF_FILE,
              type=click.Path(exists=True, dir_okay=False),
              help="Configuration file for database to \
                    retrieve datasets from (default: prod_db.conf).")
@click.option('-p', '--product',
              type=str, multiple=True,
              help="Product(s) to retrieve.")
@click.argument('expressions', callback=expression_parser, nargs=-1)
@click.pass_context
def migrate(ctx, source_config, product, expressions):
    """
    Migrate datasets from source database to target database.
    Supports query expressions like ``datacube``.
    Additionally, multiple products may be specified with
    multiple ``--product`` options.
    """
    # merge two different ways of specifying products
    products = list(product)
    if 'product' in expressions:
        products.append(expressions.pop('product'))

    test_db = ctx.obj['test_db']
    prod_db = read_config(source_config)

    # connect to the source database
    prod_index = index_connect(prod_db['local_config'],
                               application_name='source_db')

    # collect the URIs that match query
    uris = set()
    datasets = set()
    for prod in products:
        for dataset in find_datasets_lazy(prod_index,
                                          product=prod, **expressions):
            datasets.add(dataset)
            for uri in dataset.uris:
                uris.add(normalize_uri(uri))

    rules = load_rules_from_types(prod_index)

    # connect to the target database
    test_index = index_connect(test_db['local_config'],
                               application_name='target_db')

    # TODO copy the files on disk
    # for the URIs collected, copy them to a local file system
    # and change the URIs accordingly before indexing in the next section
    # the digitalearthau.move module seems relevant
    # it would be great if the user can provide a mapping of file systems
    # perhaps a .yaml file with multiple entries like
    # - source: /g/data/rs0/datacube/
    #   target: /g/data/u46/users/ia1511/data/datacube/
    # or something similar

    # there are too many DuplicateRecordError warnings
    # can they be prevented?
    if sys.stdout.isatty():
        with click.progressbar(uris, label='Indexing datasets') as uri:
            index_dataset_paths('verify', False, test_index, rules, uri)
    else:
        index_dataset_paths('verify', False, test_index, rules, uris)


if __name__ == '__main__':
    #: pylint: disable=unexpected-keyword-arg
    cli()
