import string

# From http://www.inspircd.org/wiki/Modules/spanningtree/UUIDs.html
chars = string.digits + string.ascii_uppercase
iters = [iter(chars) for _ in range(6)]
a = [next(i) for i in iters]

def next_uid(sid, level=-1):
    try:
        a[level] = next(iters[level])
        return sid + ''.join(a)
    except StopIteration:
        return UID(level-1)
