import os
import subprocess as sh
from pathlib import Path

TESTDB_NAME = 'test_db'
TESTDB_CONF_FILE = Path(__file__).parent / "test_db.conf"
PRODDB_CONF_FILE = Path(__file__).parent / "prod_db.conf"

CREATE_DATABASE_TEMPLATE = """
CREATE DATABASE {db_name}
WITH
OWNER = agdc_admin
ENCODING = 'UTF8'
LC_COLLATE = 'en_AU.UTF-8'
LC_CTYPE = 'en_AU.UTF-8'
TABLESPACE = pg_default
CONNECTION LIMIT = -1;

GRANT ALL ON DATABASE {db_name} TO agdc_admin;
GRANT CONNECT, TEMPORARY ON DATABASE {db_name} TO PUBLIC;
GRANT ALL ON DATABASE {db_name} TO test;
ALTER DATABASE {db_name} SET search_path TO "$user", public, agdc;
"""

DELETE_DATABASE_TEMPLATE = """
DROP DATABASE IF EXISTS {db_name};
"""

DEV_CONFIG = """
[datacube]
db_hostname: {hostname}
db_port: {port}
db_database: {db_name}
"""


def run_shell(*args, **kwargs):
    """ Subprocess with I/O done in the UTF-8 encoding. """
    return sh.check_output(*args, encoding='UTF-8', **kwargs)


def psql_shell_command(psql_command,
                       hostname='agdcdev-db.nci.org.au',
                       port=6432):
    """ Feed `psql_command` to the PostgreSQL server. """
    return run_shell(["psql", "-h", hostname, "-p", str(port), "datacube"],
                     input=psql_command)


def create_test_database(db_name=TESTDB_NAME, **kwargs):
    """ Create an empty database. """
    psql_command = CREATE_DATABASE_TEMPLATE.format(db_name=db_name)
    out = psql_shell_command(psql_command, **kwargs)
    # what do I do with the output?
    return out


def delete_test_database(db_name=TESTDB_NAME, **kwargs):
    """ Delete a database if it exists. """
    psql_command = DELETE_DATABASE_TEMPLATE.format(db_name=db_name)
    out = psql_shell_command(psql_command, **kwargs)
    # what do I do with the output?
    return out


def create_config(config_file=TESTDB_CONF_FILE,
                  db_name=TESTDB_NAME,
                  hostname='agdcdev-db.nci.org.au',
                  port=6432):
    """ Returns the contents of a .conf file for the given parameters. """
    with open(config_file, 'w') as fl:
        fl.write(DEV_CONFIG.format(db_name=db_name, hostname=hostname,
                                   port=port))


def dea_system_init(config_file=TESTDB_CONF_FILE):
    """ Call `dea-system init` on the datacube in the configuration file. """
    # TODO call digitalearthau.system.init_dea directly
    sh_command = ["dea-system", "--config_file", str(config_file), "init"]
    out = run_shell(sh_command)
    # what do I do with the output?
    return out


if __name__ == '__main__':
    pass
