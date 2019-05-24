import traceback
import sys


def clip(x, min_x, max_x):
    """Constrain a number between two limits

    >>> clip(3, 1, 2)
    2
    >>> clip(0, 1, 2)
    1
    >>> clip(1.5, 1, 2)
    1.5
    """
    if x < min_x:
        return min_x
    if x > max_x:
        return max_x
    return x


def map_values(x, min_x, max_x, min_y, max_y):
    full_scale_in = max_x - min_x
    full_scale_out = max_y - min_y
    return (x - min_x) * (full_scale_out / full_scale_in) + min_y


def getserial():
    # Extract serial from cpuinfo file
    cpu_serial = "0000000000000000"
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line[0:6] == 'Serial':
                    cpu_serial = line.rstrip()[-16:]
                    break
    except:
        cpu_serial = "ERROR000000000"

    return cpu_serial


def _retry(fn, retries=5):
    status = False
    retry_num = 0
    while retry_num < retries and not status:
        try:
            status = fn()
            if status is None:
                status = True
        except:
            print(traceback.format_exc())
            status = False
        retry_num += 1

    return status


def is_callable(callback):
    if sys.version_info[0] < 3 or sys.version_info[1] >= 2:
        # Python 2.x or 3.2+
        return callable(callback)
    else:
        return hasattr(callback, '__call__')