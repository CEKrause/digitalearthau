import subprocess as sh
import configparser
from pathlib import Path

import click

TESTDB_CONF_FILE = Path(__file__).parent / "test_db.conf"
PRODDB_CONF_FILE = Path(__file__).parent / "prod_db.conf"

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

DELETE_DATABASE_TEMPLATE = """
DROP DATABASE IF EXISTS {db_database};
"""

CONFIG_TEMPLATE = """
[datacube]
db_hostname: {db_hostname}
db_port: {db_port}
db_database: {db_database}
"""


def datacube_config(config_file):
    """ Reads the ``datacube`` section of a configuration file. """
    parser = configparser.ConfigParser()
    with open(config_file) as fl:
        parser.read_file(fl)
    return dict(parser['datacube'])


def run_shell(*args, **kwargs):
    """ Subprocess with I/O done in the UTF-8 encoding. """
    return sh.check_output(*args, encoding='UTF-8', **kwargs)


def psql_command(command, config):
    """ Feed ``command`` to the PostgreSQL server specified in ``config``. """
    hostname, port = [str(config[key]) for key in ['db_hostname', 'db_port']]
    # this assumes there is a 'datacube' database running at the host
    # can this assumption be avoided by not specifying any database at first?
    return run_shell(["psql", "-h", hostname, "-p", port, "datacube"],
                     input=command)


@click.group()
@click.option('-C', '--config-file',
              default=TESTDB_CONF_FILE,
              type=click.Path(exists=True, dir_okay=False),
              help="Configuration file")
@click.pass_context
def cli(ctx, config_file):
    ctx.obj['config_file'] = config_file


@cli.command()
@click.pass_context
def setup(ctx):
    """Setup a test database environment."""
    config_file = ctx.obj['config_file']
    config = datacube_config(config_file)
    # should this go into a log?
    print(psql_command(CREATE_DATABASE_TEMPLATE.format(**config), config))
    # TODO: call dea_init directly
    print(run_shell(["dea-system", "--config_file", str(config_file), "init"]))

@cli.command()
@click.pass_context
def teardown(ctx):
    """Teardown a test database environment."""
    config_file = ctx.obj['config_file']
    config = datacube_config(config_file)
    # should this go into a log?
    print(psql_command(DELETE_DATABASE_TEMPLATE.format(**config), config))

# TODO: ../move.py contains code for moving files

if __name__ == '__main__':
    cli(obj={})