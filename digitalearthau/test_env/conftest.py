import pytest

from datacube.index import index_connect
from digitalearthau.test_env import TESTDB_CONF_FILE
from digitalearthau.test_env import load_config


@pytest.fixture
def test_config():
    return load_config(TESTDB_CONF_FILE)


@pytest.fixture
def test_index(test_config):
    return index_connect(test_config, application_name='NCI-test')
