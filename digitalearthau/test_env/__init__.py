"""
Set up and tear down test database environments at the NCI.
"""
import subprocess
import pathlib
import sys
import logging

import click

from datacube.config import LocalConfig
from datacube.config import DEFAULT_CONF_PATHS, DATACUBE_SECTION
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


def load_config(config_file):
    """ Load configuration from file. """
    paths = DEFAULT_CONF_PATHS + (str(config_file.absolute()),)
    return LocalConfig.find(paths=paths)


def as_dict(local_config, env=None):
    """ Convert the default environment of the configuration into a `dict`. """
    return dict(local_config._config[env or DATACUBE_SECTION])


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

    ctx.obj['test_db'] = load_config(config_file)


def setup(config, init_users):
    """ Setup a test database environment. """
    # should these go into a log?
    command = CREATE_DATABASE_TEMPLATE.format(**as_dict(config))
    click.echo(psql_command(command, config))

    # do not validate database (nothing there yet)
    index = index_connect(config, application_name='test-env',
                          validate_connection=False)

    return init_dea(index, init_users)


@cli.command('setup', help=setup.__doc__)
@click.option('--init-users/--no-init-users',
              is_flag=True, default=True,
              help="Include user roles and grants (default: true).")
@click.pass_context
def setup_cmd(ctx, init_users):
    setup(ctx.obj['test_db'], init_users)


def teardown(config):
    """ Teardown a test database environment. """
    # should these go into a log?
    command = TERMINATE_BACKEND_TEMPLATE.format(**as_dict(config))
    click.echo(psql_command(command, config))

    command = DROP_DATABASE_TEMPLATE.format(**as_dict(config))
    click.echo(psql_command(command, config))


@cli.command('teardown', help=teardown.__doc__)
@click.pass_context
def teardown_cmd(ctx):
    teardown(ctx.obj['test_db'])


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


def collect_uris(prod_index, products, expressions):
    """
    Collect all URIs of datasets from products
    matching search expressions.
    """
    uris = set()
    datasets = set()
    for prod in products:
        for dataset in find_datasets_lazy(prod_index,
                                          product=prod, **expressions):
            datasets.add(dataset)
            for uri in dataset.uris:
                uris.add(normalize_uri(uri))

    return (datasets, uris)


def index_uris(test_index, uris, rules):
    """ Index the URIs into the test database. """
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


def migrate(test_db, prod_db, products, expressions):
    """
    Migrate datasets from source database to target database.
    Supports query expressions like ``datacube``.
    Additionally, multiple products may be specified with
    multiple ``--product`` options.
    """
    # connect to the source database
    prod_index = index_connect(prod_db, application_name='test-env')

    (datasets, uris) = collect_uris(prod_index, products, expressions)
    rules = load_rules_from_types(prod_index)

    # connect to the target database
    test_index = index_connect(test_db, application_name='test-env')
    index_uris(test_index, uris, rules)


@cli.command('migrate', help=migrate.__doc__,
             short_help="Migrate datasets.")
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
def migrate_cmd(ctx, source_config, product, expressions):
    # merge two different ways of specifying products
    products = list(product)
    if 'product' in expressions:
        products.append(expressions.pop('product'))

    test_db = ctx.obj['test_db']
    prod_db = load_config(source_config)

    migrate(test_db, prod_db, products, expressions)


if __name__ == '__main__':
    #: pylint: disable=unexpected-keyword-arg
    cli()
