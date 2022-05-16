from collections import deque
import pytest
import asynkit.tools


def test_deque_pop():
    """
    Test that our pop for a deque has same semantics as that for a list
    """

    for i in range(-7, 7):
        ref = list(range(5))
        deq = deque(range(5))

        try:
            refpop = ref.pop(i)
            ok = True
        except IndexError:
            ok = False

        if ok:
            pop = asynkit.tools.deque_pop(deq, i)
            assert pop == refpop
            assert list(deq) == ref
        else:
            with pytest.raises(IndexError):
                asynkit.tools.deque_pop(deq, i)