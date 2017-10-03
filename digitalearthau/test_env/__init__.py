"""
Set up and tear down test database environments at the NCI.
"""
import subprocess
import configparser
import pathlib

import click

from datacube.config import LocalConfig, DATACUBE_SECTION, _DEFAULT_CONF
from datacube.index import index_connect
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


@click.group()
@click.option('-C', '--config-file',
              default=TESTDB_CONF_FILE,
              type=click.Path(exists=True, dir_okay=False),
              help="Test database configuration file (default: test_db.conf)")
@click.pass_context
def cli(ctx, config_file):
    """ Set up and tear down test database environments at the NCI. """
    config = configparser.ConfigParser()
    config.read_string(_DEFAULT_CONF)

    with open(config_file) as fl:
        config.read_file(fl)

    ctx.obj['config_file'] = config_file
    ctx.obj['datacube_section'] = dict(config[DATACUBE_SECTION])
    ctx.obj['local_config'] = LocalConfig(config,
                                          files_loaded=[str(config_file)])


@cli.command()
@click.option('--init-users/--no-init-users',
              is_flag=True, default=True,
              help="Include user roles and grants (default: true)")
@click.pass_context
def setup(ctx, init_users):
    """ Setup a test database environment. """
    obj = ctx.obj

    # should these go into a log?
    command = CREATE_DATABASE_TEMPLATE.format(**obj['datacube_section'])
    click.echo(psql_command(command, obj['local_config']))

    # do not validate database (nothing there yet)
    index = index_connect(obj['local_config'],
                          application_name='setup-test-environment',
                          validate_connection=False)

    init_dea(index, init_users)


@cli.command()
@click.pass_context
def teardown(ctx):
    """ Teardown a test database environment. """
    obj = ctx.obj

    # should these go into a log?
    command = TERMINATE_BACKEND_TEMPLATE.format(**obj['datacube_section'])
    click.echo(psql_command(command, obj['local_config']))

    command = DROP_DATABASE_TEMPLATE.format(**obj['datacube_section'])
    click.echo(psql_command(command, obj['local_config']))

# TODO: ../move.py contains code for moving files

if __name__ == '__main__':
    #: pylint: disable=unexpected-keyword-arg
    cli(obj={})
