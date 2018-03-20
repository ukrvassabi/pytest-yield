import pytest

pytestmark = pytest.mark.usefixtures('check_teardown_module')


@pytest.mark.skip(reason="Skip this test")
def test_skip_regular():
    assert 1 == 2


def test_regular(one):
    assert one == 1


@pytest.mark.parametrize('v', [1, 2])
def test_regular_with_param(one, v):
    assert one + v == 1 + v


@pytest.mark.xfail
def test_regular_xfail(two):
    assert two == 1