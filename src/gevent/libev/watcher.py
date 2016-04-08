# pylint: disable=too-many-lines, protected-access, redefined-outer-name, not-callable
from __future__ import absolute_import, print_function
import sys

import gevent.libev._corecffi as _corecffi # pylint:disable=no-name-in-module,import-error

ffi = _corecffi.ffi # pylint:disable=no-member
libev = _corecffi.lib # pylint:disable=no-member

if hasattr(libev, 'vfd_open'):
    # Must be on windows
    assert sys.platform.startswith("win"), "vfd functions only needed on windows"
    vfd_open = libev.vfd_open
    vfd_free = libev.vfd_free
    vfd_get = libev.vfd_get
else:
    vfd_open = vfd_free = vfd_get = lambda fd: fd

#####
## NOTE on Windows:
# The C implementation does several things specially for Windows;
# a possibly incomplete list is:
#
# - the loop runs a periodic signal checker;
# - the io watcher constructor is different and it has a destructor;
# - the child watcher is not defined
#
# The CFFI implementation does none of these things, and so
# is possibly NOT FUNCTIONALLY CORRECT on Win32
#####

_events = [(libev.EV_READ, 'READ'),
           (libev.EV_WRITE, 'WRITE'),
           (libev.EV__IOFDSET, '_IOFDSET'),
           (libev.EV_PERIODIC, 'PERIODIC'),
           (libev.EV_SIGNAL, 'SIGNAL'),
           (libev.EV_CHILD, 'CHILD'),
           (libev.EV_STAT, 'STAT'),
           (libev.EV_IDLE, 'IDLE'),
           (libev.EV_PREPARE, 'PREPARE'),
           (libev.EV_CHECK, 'CHECK'),
           (libev.EV_EMBED, 'EMBED'),
           (libev.EV_FORK, 'FORK'),
           (libev.EV_CLEANUP, 'CLEANUP'),
           (libev.EV_ASYNC, 'ASYNC'),
           (libev.EV_CUSTOM, 'CUSTOM'),
           (libev.EV_ERROR, 'ERROR')]

def _events_to_str(events):
    result = []
    for (flag, string) in _events:
        c_flag = flag
        if events & c_flag:
            result.append(string)
            events = events & (~c_flag)
        if not events:
            break
    if events:
        result.append(hex(events))
    return '|'.join(result)


from gevent._ffi import watcher as _base


class watcher(_base.watcher):
    _FFI = ffi
    _LIB = libev
    _watcher_prefix = 'ev'

    def __init__(self, _loop, ref=True, priority=None, args=_base._NOARGS):
        if ref:
            self._flags = 0
        else:
            self._flags = 4

        super(watcher, self).__init__(_loop, ref=ref, priority=priority, args=args)

    def _watcher_ffi_set_priority(self, priority):
        libev.ev_set_priority(self._watcher, priority)

    def _watcher_ffi_init(self, args):
        self._watcher_init(self._watcher,
                           self._watcher_callback,
                           *args)

    def _watcher_ffi_start(self):
        self._watcher_start(self.loop._ptr, self._watcher)

    def _watcher_ffi_ref(self):
        if self._flags & 2:
            self.loop.ref()
            self._flags &= ~2

    def _watcher_ffi_unref(self):
        if self._flags & 6 == 4:
            self.loop.unref()
            self._flags |= 2

    def _get_ref(self):
        return False if self._flags & 4 else True

    def _set_ref(self, value):
        if value:
            if not self._flags & 4:
                return  # ref is already True
            if self._flags & 2:  # ev_unref was called, undo
                self.loop.ref()
            self._flags &= ~6  # do not want unref, no outstanding unref
        else:
            if self._flags & 4:
                return  # ref is already False
            self._flags |= 4
            if not self._flags & 2 and libev.ev_is_active(self._watcher):
                self.loop.unref()
                self._flags |= 2

    ref = property(_get_ref, _set_ref)


    def _get_priority(self):
        return libev.ev_priority(self._watcher)

    def _set_priority(self, priority):
        if libev.ev_is_active(self._watcher):
            raise AttributeError("Cannot set priority of an active watcher")
        libev.ev_set_priority(self._watcher, priority)

    priority = property(_get_priority, _set_priority)

    def feed(self, revents, callback, *args):
        self.callback = callback
        self.args = args or _NOARGS
        if self._flags & 6 == 4:
            self.loop.unref()
            self._flags |= 2
        libev.ev_feed_event(self.loop._ptr, self._watcher, revents)
        if not self._flags & 1:
            # Py_INCREF(<PyObjectPtr>self)
            self._flags |= 1

    @property
    def pending(self):
        return True if libev.ev_is_pending(self._watcher) else False


class io(_base.IoMixin, watcher):

    EVENT_MASK = libev.EV__IOFDSET | libev.EV_READ | libev.EV_WRITE

    def __init__(self, loop, fd, events, ref=True, priority=None):
        # XXX: Win32: Need to vfd_open the fd and free the old one?
        # XXX: Win32: Need a destructor to free the old fd?
        if fd < 0:
            raise ValueError('fd must be non-negative: %r' % fd)
        if events & ~(libev.EV__IOFDSET | libev.EV_READ | libev.EV_WRITE):
            raise ValueError('illegal event mask: %r' % events)
        watcher.__init__(self, loop, ref=ref, priority=priority, args=(fd, events))

    def _get_fd(self):
        return vfd_get(self._watcher.fd)

    def _set_fd(self, fd):
        if libev.ev_is_active(self._watcher):
            raise AttributeError("'io' watcher attribute 'fd' is read-only while watcher is active")
        vfd = vfd_open(fd)
        vfd_free(self._watcher.fd)
        self._watcher_init(self._watcher, self._watcher_callback, vfd, self._watcher.events)

    fd = property(_get_fd, _set_fd)

    def _get_events(self):
        return self._watcher.events

    def _set_events(self, events):
        if libev.ev_is_active(self._watcher):
            raise AttributeError("'io' watcher attribute 'events' is read-only while watcher is active")
        self._watcher_init(self._watcher, self._watcher_callback, self._watcher.fd, events)

    events = property(_get_events, _set_events)

    @property
    def events_str(self):
        return _events_to_str(self._watcher.events)

    def _format(self):
        return ' fd=%s events=%s' % (self.fd, self.events_str)


class timer(_base.TimerMixin, watcher):

    def _update_now(self):
        libev.ev_now_update(self.loop._ptr)

    @property
    def at(self):
        return self._watcher.at

    def again(self, callback, *args, **kw):
        # Exactly the same as start(), just with a different initializer
        # function
        self._watcher_start = libev.ev_timer_again
        try:
            self.start(callback, *args, **kw)
        finally:
            del self._watcher_start


class signal(_base.SignalMixin, watcher):
    pass

class idle(_base.IdleMixin, watcher):
    pass

class prepare(_base.PrepareMixin, watcher):
    pass

class check(_base.CheckMixin, watcher):
    pass

class fork(_base.ForkMixin, watcher):
    pass


class async(_base.AsyncMixin, watcher):

    def send(self):
        libev.ev_async_send(self.loop._ptr, self._watcher)

    @property
    def pending(self):
        return True if libev.ev_async_pending(self._watcher) else False


class child(_base.ChildMixin, watcher):
    _watcher_type = 'child'

    @property
    def pid(self):
        return self._watcher.pid

    @property
    def rpid(self, ):
        return self._watcher.rpid

    @rpid.setter
    def rpid(self, value):
        self._watcher.rpid = value

    @property
    def rstatus(self):
        return self._watcher.rstatus

    @rstatus.setter
    def rstatus(self, value):
        self._watcher.rstatus = value


class stat(_base.StatMixin, watcher):
    _watcher_type = 'stat'

    @property
    def attr(self):
        if not self._watcher.attr.st_nlink:
            return
        return self._watcher.attr

    @property
    def prev(self):
        if not self._watcher.prev.st_nlink:
            return
        return self._watcher.prev

    @property
    def interval(self):
        return self._watcher.interval
