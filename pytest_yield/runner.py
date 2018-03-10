import sys
import py

from _pytest.outcomes import TEST_OUTCOME
from _pytest.runner import SetupState


def merge_stack(stack, needed_collectors):
    new_stack = []
    added_to_stack = []
    for idx, col_el in enumerate(needed_collectors):
        try:
            stack_el = stack[idx]
            stack_el_array = stack_el if isinstance(stack_el, list) else \
                [stack_el]
        except IndexError:
            stack_el_array = []

        if col_el not in stack_el_array:
            stack_el_array.append(col_el)
            added_to_stack.append(col_el)
        stack_el = stack_el_array if len(stack_el_array) > 1 else \
            stack_el_array[0]
        new_stack.append(stack_el)
    return new_stack, added_to_stack


class TreeStack(dict):

    def __missing__(self, key):
        value = self[key] = type(self)()
        return value

    def __contains__(self, item):
        contains = dict.__contains__(self, item)
        if not contains:
            for val in self.values():
                contains = item in val
                if contains:
                    break
        return contains

    def merge(self, keys):
        d = self
        added = []
        for key in keys:
            if not dict.__contains__(d, key):
                added.append(key)
            d = d[key]
        return added

    def pop(self, key):
        contains = dict.__contains__(self, key)
        if contains:
            return dict.pop(self, key)
        else:
            for val in self.values():
                res = val.pop(key)
                if res is not None:
                    return res

    def popitem(self):
        for val in self.values():
            if val:
                return val.popitem()
        return dict.popitem(self)



class YieldSetupState(SetupState):

    def __init__(self):
        super(YieldSetupState, self).__init__()
        self.stack = TreeStack()

    def _teardown_towards(self, needed_collectors):
        return
        if needed_collectors and \
                getattr(needed_collectors[-1], 'is_concurrent', False):
            return
        while self.stack:
            if self.stack == needed_collectors[:len(self.stack)]:
                break
            self._pop_and_teardown()

    def _pop_and_teardown(self):
        colitem, _ = self.stack.popitem()
        self._teardown_with_finalization(colitem)

    def teardown_exact(self, item, nextitem):
        self._teardown_with_finalization(item)
        c = self.stack.pop(item)
        pass

    def prepare(self, colitem):
        """ setup objects along the collector chain to the test-method
            and teardown previously setup objects."""
        needed_collectors = colitem.listchain()
        # self._teardown_towards(needed_collectors)

        # check if the last collection node has raised an error
        for col in self.stack:
            if hasattr(col, '_prepare_exc'):
                py.builtin._reraise(*col._prepare_exc)

        added_to_stack = self.stack.merge(needed_collectors)
        for col in added_to_stack:
            try:
                col.setup()
            except TEST_OUTCOME:
                col._prepare_exc = sys.exc_info()
                raise