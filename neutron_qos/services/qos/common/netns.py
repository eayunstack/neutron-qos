# Copyright (c) 2015 Eayun, Inc.
# All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import ctypes
import platform

__NR_setns_map = {
    'x86_64': {'64bit': 308},
    'i386': {'32bit': 346}
    # FIXME: Other machine types and architectures
}

__NR_setns = __NR_setns_map.get(
    platform.machine(), {}
).get(platform.architecture()[0], 308)
CLONE_NEWNET = 0x40000000

NETNS_RUN_DIR_PATH = '/var/run/netns/{namespace}'
NETNS_PID_PATH = '/proc/{pid}/ns/net'

libc = None


def setns(netnsfd):
    global libc
    libc = libc or ctypes.CDLL('libc.so.6', use_errno=True)
    ret = libc.syscall(__NR_setns, netnsfd, CLONE_NEWNET)
    if ret != 0:
        raise OSError(ctypes.get_errno(), 'failed to open netns')


class NetNSSwitcher(object):
    def __init__(self, netns=None):
        self._pid = os.getpid()
        self._netns = netns
        self.in_namespace = True

    def _save_origin_netns(self):
        f = NETNS_PID_PATH.format(pid=self._pid)
        self._originnsfd = os.open(f, os.O_RDONLY)

    def _return_origin_netns(self):
        setns(self._originnsfd)
        os.close(self._originnsfd)

    def __enter__(self):
        if self._netns:
            self._save_origin_netns()
            f = NETNS_RUN_DIR_PATH.format(namespace=self._netns)
            if os.path.isfile(f):
                nsfd = os.open(f, os.O_RDONLY)
                setns(nsfd)
                os.close(nsfd)
            else:
                self.in_namespace = False

    def __exit__(self, e_type, e_value, traceback):
        if self._netns:
            self._return_origin_netns()
