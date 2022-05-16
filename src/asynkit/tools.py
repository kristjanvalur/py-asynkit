def deque_pop(d, pos=-1):
    if pos == -1:
        return d.pop()
    elif pos == 0:
        return d.popleft()

    if pos >= 0:
        if pos < len(d):
            d.rotate(-pos)
            r = d.popleft()
            d.rotate(pos)
            return r
    elif pos >= -len(d):
        pos += 1
        d.rotate(-pos)
        r = d.pop()
        d.rotate(pos)
        return r
    # create exception
    [].pop(pos)
