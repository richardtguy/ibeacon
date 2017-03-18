#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
# Interpreter version: python 2.7
#
# Imports =====================================================================
import signal


# Functions & classes =========================================================
class TimeoutException(Exception):
    """
    Exception triggered when the decorated function timeouts.
    """
    def __init__(self, message = ""):
        self.message = message

    def __str__(self):
        return repr(self.message)


def __timeout_handler(signum, frame):
    raise TimeoutException()


def timeout(time_s, default_val=None, exception_message="Timed out!"):
    """
    Timeout wrapper.
    Args:
        time_s (int): Time measured in seconds.
        default_val (any): If set, return value of this parameter instead of
                           raising :class:`TimeoutException`.
        exception_message (str, default "Timeouted!"): If set, raise 
                          :class:`TimeoutException` with given
                          `exception_message`.
    """
    def __timeout_function(f):
        def decorator(*args, **kwargs):
            old_handler = signal.signal(
                signal.SIGALRM, __timeout_handler)
            signal.alarm(time_s)  # triger alarm in time_s seconds

            try:
                retval = f(*args, **kwargs)
            except TimeoutException:
                if default_val is None:
                    raise TimeoutException(exception_message)
                return default_val
            finally:
                signal.signal(signal.SIGALRM, old_handler)

            signal.alarm(0)
            return retval

        return decorator

    return __timeout_function