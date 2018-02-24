import pytest
import sys

from pytest import hookspec
from _pytest.runner import (call_and_report,
                            call_runtest_hook, check_interactive_exception, show_test_item)
from _pytest import hookspec as _hookspec

from functools import wraps
from collections import deque


pytest_plugins = ['plugin']

def concurrent(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        res = func(*args, **kwargs)
        if not hasattr(res, 'next'):
            raise Exception('%s need to be generator' % func.__name__)
        return res

    wrapper.is_concurent = True
    wrapper.origin = func
    return wrapper


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items):
    for item in items:
        item.is_concurent = getattr(item.obj, 'is_concurent', False)
        if item.is_concurent:
            item.was_already_run = False
            item.was_finished = False
            fm = item.session._fixturemanager
            fi = fm.getfixtureinfo(item.parent, item.obj.origin, getattr(item, 'cls', None))
            item._fixtureinfo = fi


def pytest_runtestloop(session):
    if (session.testsfailed and
            not session.config.option.continue_on_collection_errors):
        raise session.Interrupted(
            "%d errors during collection" % session.testsfailed)

    if session.config.option.collectonly:
        return True
    has_items = len(session.items) > 0
    items = deque(session.items)
    if has_items:
        items[-1].last_in_round = True
    while has_items:
        try:
            item = items.popleft()
            nextitem = items[0] if len(items) > 0 else None
            item.config.hook.pytest_runtest_protocol(item=item, nextitem=nextitem)
            if session.shouldstop:
                raise session.Interrupted(session.shouldstop)
            if item.is_concurent and not item.was_finished:
                items.append(item)
            if getattr(item, 'last_in_round', False):
                item.config.hook.pytest_round_finished()
                delattr(item, 'last_in_round')
                if len(items) > 0:
                    items[-1].last_in_round = True
        except IndexError:
            has_items = False
    return True


@hookspec(firstresult=True)
def pytest_runtest_protocol(item, nextitem):
    if item.is_concurent:
        if not item.was_already_run:
            item.ihook.pytest_runtest_logstart(
                nodeid=item.nodeid, location=item.location,
            )
        result = yieldtestprotocol(item, nextitem=nextitem)
        try:
            if item.was_finished:
                item.ihook.pytest_runtest_logfinish(
                    nodeid=item.nodeid, location=item.location,
                )
        except AttributeError:  # compatibilyty with pytest==3.0
            pass
    else:
        item.ihook.pytest_runtest_logstart(
            nodeid=item.nodeid, location=item.location,
        )
        runtestprotocol(item, nextitem=nextitem)
        result = True
        try:
            item.ihook.pytest_runtest_logfinish(
                nodeid=item.nodeid, location=item.location,
            )
        except AttributeError:  # compatibilyty with pytest==3.0
            pass
    return result


def runtestprotocol(item, log=True, nextitem=None):
    hasrequest = hasattr(item, "_request")
    if hasrequest and not item._request:
        item._initrequest()
    rep = call_and_report(item, "setup", False)
    reports = [rep]
    if rep.passed:
        if item.config.option.setupshow:
            show_test_item(item)
        if not item.config.option.setuponly:
            reports.append(call_and_report(item, "call", log))
    reports.append(call_and_report(item, "teardown", False,
                                   nextitem=nextitem))
    # after all teardown hooks have been called
    # want funcargs and request info to go away
    if hasrequest:
        item._request = False
        item.funcargs = None
    return reports


def yieldtestprotocol(item, log=True, nextitem=None):
    hasrequest = hasattr(item, "_request")
    result = True
    if hasrequest and not item._request:
        item._initrequest()
    if not item.was_already_run:
        rep = call_and_report(item, "setup", False)
        if rep.passed and item.config.option.setupshow:
            show_test_item(item)
    if item.was_already_run or rep.passed:
        if not item.config.option.setuponly:
            result = yield_and_report(item, "call", log)
    if item.was_finished:
        call_and_report(item, "teardown", False, nextitem=nextitem)
        if hasrequest:
            item._request = False
            item.funcargs = None
    return result


def yield_and_report(item, when, log=True, **kwds):
    call = call_runtest_hook(item, when, **kwds)
    call.when = 'yield'
    hook = item.ihook
    report = hook.pytest_runtest_makereport(item=item, call=call)
    report.result = getattr(call, 'result', None)
    if not item.was_finished and not report.result:
        log = False
    if log:
        hook.pytest_runtest_logreport(report=report)
    if check_interactive_exception(call, report):
        hook.pytest_exception_interact(node=item, call=call, report=report)
    return report


@hookspec(firstresult=True)
def pytest_report_teststatus(report):
    if report.passed:
        letter = "."
    elif report.skipped:
        letter = "s"
    elif report.failed:
        letter = "F"
        if report.when != "call":
            letter = "f"
    if report.when == 'yield' and report.passed and len(report.result) > 0:
        letter = 'y'
        word = report.result[0] if isinstance(report.result[0], basestring) else ''
    else:
        word = report.outcome.upper()

    return report.outcome, letter, word


@hookspec(firstresult=True)
def pytest_runtest_call(item):
    try:
        if item.is_concurent:
            if not item.was_already_run:
                item.concurrent_test = item.ihook.pytest_pyfunc_call(pyfuncitem=item)
            try:
                res = item.concurrent_test.next()
                item.was_already_run = True
            except StopIteration:
                item.was_finished = True
                res = None
        else:
            item.runtest()
            res = None
        return res
    except Exception:
        item.was_finished = True
        # Store trace info to allow postmortem debugging
        type, value, tb = sys.exc_info()
        tb = tb.tb_next  # Skip *this* frame
        sys.last_type = type
        sys.last_value = value
        sys.last_traceback = tb
        del tb  # Get rid of it in this namespace
        raise


@hookspec(firstresult=True)
def pytest_pyfunc_call(pyfuncitem):
    testfunction = pyfuncitem.obj
    if pyfuncitem._isyieldedfunction():
        res = testfunction(*pyfuncitem._args)
    else:
        funcargs = pyfuncitem.funcargs
        testargs = {}
        for arg in pyfuncitem._fixtureinfo.argnames:
            testargs[arg] = funcargs[arg]
        res = testfunction(**testargs)
    return res

def pytest_round_finished():
    pass

@pytest.fixture(autouse=True)
def something():
    return 1