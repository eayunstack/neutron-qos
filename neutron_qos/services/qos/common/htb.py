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
import socket
import time
import struct

from neutron.services.qos.common import netns

# RTNetlink message types
NLMSG_ERROR = 0x02
NLMSG_DONE = 0x03
RTM_NEWLINK = 0x10
RTM_GETLINK = 0x12
RTM_NEWQDISC = 0x24
RTM_GETQDISC = 0x26
RTM_NEWTCLASS = 0x28
RTM_GETTCLASS = 0x2A
RTM_NEWTFILTER = 0x2C
RTM_GETTFILTER = 0x2E

# RTNetlink message flags
NLM_F_REQUEST = 0x0001
NLM_F_MULTI = 0x0002
NLM_F_ROOT = 0x0100
NLM_F_MATCH = 0x0200
NLM_F_DUMP = NLM_F_ROOT | NLM_F_MATCH

# Root handler definition of tc
TC_H_ROOT = 0xFFFFFFFF

# RTA types for IfInfoMsg
IFLA_IFNAME = 3

# RTA types for TcMsg
TCA_KIND = 1
TCA_OPTIONS = 2

# RTA types for TcFilterMsg
TCA_ACT_KIND = 1
TCA_ACT_OPTIONS = 2

# NLA policy types for htb
TCA_HTB_PARMS = 1
TCA_HTB_INIT = 2

# NLA policy types for u32 selector
TCA_U32_CLASSID = 1
TCA_U32_SEL = 5

# Netmask int number to prefixlen map
MASK2PREFIXLEN_MAP = {}
_tmp = 0xFFFFFFFF
for i in xrange(33):
    MASK2PREFIXLEN_MAP[_tmp] = 32-i
    _tmp -= 2**i


class StructHelper(object):
    _fmt = None
    _tuple = None

    @property
    def data(self):
        if self._fmt is None or self._tuple is None:
            raise NotImplementedError
        return struct.pack(self._fmt, *self._tuple)

    @classmethod
    def from_data(cls, data):
        return cls(*(struct.unpack(cls._fmt, data)))


class NLM_Header(StructHelper):
    _fmt = 'IHHII'
    length = 16

    def __init__(self, length, msg_type, flags, seq, pid):
        self.length = length
        self.msg_type = msg_type
        self.flags = flags
        self.seq = seq
        self.pid = pid

    @property
    def _tuple(self):
        return (self.length, self.msg_type, self.flags, self.seq, self.pid)

    @classmethod
    def dump_request_header(cls, msg_type):
        return cls(0, msg_type, NLM_F_REQUEST | NLM_F_DUMP, 0, 0)


class IfInfoMsg(StructHelper):
    _fmt = 'BBHIII'
    length = 16

    def __init__(self, family, _, dev_type, ifindex, dev_flags, change_mask):
        self.family = family
        self.dev_type = dev_type
        self.ifindex = ifindex
        self.dev_flags = dev_flags
        self.change_mask = change_mask

    @property
    def _tuple(self):
        return (self.family, 0, self.dev_type, self.ifindex,
                self.dev_flags, self.change_mask)

    @classmethod
    def template_for_get_msg(cls):
        return cls(socket.AF_UNSPEC, 0, 0, 0, 0, 0xFFFFFFFF)


class TcMsg(StructHelper):
    _fmt = 'BBHIIII'
    length = 20

    def __init__(self, family, _, _2, ifindex, handle, parent, info):
        self.family = family
        self.ifindex = ifindex
        self.handle = handle
        self.parent = parent
        self.info = info

    @property
    def _tuple(self):
        return (self.family, 0, 0, self.ifindex, self.handle, self.parent,
                self.info)

    @classmethod
    def template_for_get_msg(cls, ifindex=0):
        return cls(socket.AF_UNSPEC, 0, 0, ifindex, 0, 0, 0)

    def _handle_to_str(self, handle):
        major = '{:x}'.format(handle >> 16).lstrip('0')
        minor = '{:x}'.format(handle & 0xFFFF).lstrip('0')
        return '%s:%s' % (major, minor)

    @property
    def handle_str(self):
        return self._handle_to_str(self.handle)

    @property
    def parent_str(self):
        if self.parent == TC_H_ROOT:
            return None
        return self._handle_to_str(self.parent)


class TcFilterMsg(TcMsg):

    def __init__(self, family, _, _2, ifindex, handle, parent, info):
        super(TcFilterMsg, self).__init__(family, _, _2,
                                          ifindex, handle, parent, info)
        # protocol is network/big endian
        self.protocol = socket.ntohs(self.info & 0xFFFF)
        self.prio = self.info >> 16


class GetNLMsg(object):
    def __init__(self, **kwargs):
        self.header = NLM_Header.dump_request_header(self._msg_type)
        self.template = self._template_class.template_for_get_msg(**kwargs)
        self.attrs = {}

    @property
    def data(self):
        length = NLM_Header.length + self.template.length
        d = self.template.data
        for attr in self.attrs:
            length += attr.length
            d += attr.data
        self.header.length = length  # Set the length of the whole message
        d = self.header.data + d
        return d


class GetIfInfoMsg(GetNLMsg):
    _template_class = IfInfoMsg
    _msg_type = RTM_GETLINK


class GetQdiscMsg(GetNLMsg):
    _template_class = TcMsg
    _msg_type = RTM_GETQDISC


class GetTClassMsg(GetNLMsg):
    _template_class = TcMsg
    _msg_type = RTM_GETTCLASS


class GetTFilterMsg(GetNLMsg):
    _template_class = TcFilterMsg
    _msg_type = RTM_GETTFILTER


class RecvNLMsg(object):
    def __init__(self, header):
        self.header = header

    def parse_msg(self, data):
        template_length = self._template_class.length
        self.template = self._template_class.from_data(data[:template_length])
        self.attrs = self.parse_attributes(data[template_length:])

    def parse_attributes(self, data):
        attrs = {}
        p = 0
        while p < len(data):
            (rta_len, rta_type) = struct.unpack('HH', data[p:p+4])
            rta_data = data[p+4:p+rta_len]
            attrs[rta_type] = rta_data
            p += (rta_len + 3)/4*4  # Align
        return attrs

    def parse_nlattrs(self, data):
        # nlattrs and IP Service specific data share the same TLV format
        return self.parse_attributes(data)

    def attr_data_to_name(self, attr_key):
        return self.attrs[attr_key].decode('UTF-8').strip('\x00')


class RecvIfInfoMsg(RecvNLMsg):
    _template_class = IfInfoMsg
    _msg_type = RTM_NEWLINK

    def parse_msg(self, data):
        super(RecvIfInfoMsg, self).parse_msg(data)
        self.name = self.attr_data_to_name(IFLA_IFNAME)


class RecvQdiscMsg(RecvNLMsg):
    _template_class = TcMsg
    _msg_type = RTM_NEWQDISC

    def parse_msg(self, data):
        super(RecvQdiscMsg, self).parse_msg(data)
        name = self.attr_data_to_name(TCA_KIND)
        self.is_root_htb = name == 'htb' and self.template.parent == TC_H_ROOT
        if self.is_root_htb:
            nlattrs = self.parse_nlattrs(self.attrs[TCA_OPTIONS])
            (
                version, r2q, default_cls, debug, direct_pkts
            ) = struct.unpack('IIIII', nlattrs[TCA_HTB_INIT])
            self.default_cls = '{:x}'.format(default_cls)
            # Not used
            self.r2q = r2q


class RecvTClassMsg(RecvNLMsg):
    _template_class = TcMsg
    _msg_type = RTM_NEWTCLASS

    def parse_msg(self, data):
        super(RecvTClassMsg, self).parse_msg(data)
        name = self.attr_data_to_name(TCA_KIND)
        self.is_htb = name == 'htb'
        if self.is_htb:
            nlattrs = self.parse_nlattrs(self.attrs[TCA_OPTIONS])
            (
                _celllog, _linklayer, _overhead, _cell_align, _mpu, rate,
                _celllogc, _linklayerc, _overheadc, _cell_alignc, _mpuc, ceil,
                bucket, cbucket, quantum, level, prio
            ) = struct.unpack('BBHhHIBBHhHIIIIII', nlattrs[TCA_HTB_PARMS])
            self.rate = rate
            self.ceil = ceil
            self.bucket = bucket
            self.cbucket = cbucket
            self.prio = prio
            # Not used
            self.quantum = quantum
            self.level = level


class RecvTFilterMsg(RecvNLMsg):
    _template_class = TcFilterMsg
    _msg_type = RTM_NEWTFILTER

    def data_to_qos_filter(self, data):
        qos_filter = {}
        (
            flags, offshift, nkeys, offmask, off, offoff, hoff, hmask
        ) = struct.unpack('BBBHHhhI', data[:16])
        # offmask and hmask are network/big endian
        offmask = socket.ntohs(offmask)
        hmask = socket.ntohs(hmask)
        for i in range(nkeys):
            p = 16 + i * 16
            # Mask and val are network/big endian
            (mask, val) = struct.unpack('!II', data[p:p+8])
            (off, offmask) = struct.unpack('ii', data[p+8:p+16])
            if off == 8 and mask == 0x00FF0000:
                qos_filter['protocol'] = val
            elif off == 20:
                if mask == 0xFFFF0000:
                    qos_filter['src_port'] = val >> 16
                elif mask == 0x0000FFFF:
                    qos_filter['dst_port'] = val
            elif off == 12:
                address = socket.inet_ntoa(data[p+4:p+8])
                prefix = MASK2PREFIXLEN_MAP[mask]
                qos_filter['src_addr'] = '%s/%s' % (address, prefix)
            elif off == 16:
                address = socket.inet_ntoa(data[p+4:p+8])
                prefix = MASK2PREFIXLEN_MAP[mask]
                qos_filter['dst_addr'] = '%s/%s' % (address, prefix)
        return qos_filter

    def parse_msg(self, data):
        super(RecvTFilterMsg, self).parse_msg(data)
        name = self.attr_data_to_name(TCA_ACT_KIND)
        if name == 'u32':
            if TCA_ACT_OPTIONS not in self.attrs:
                self.has_u32_sel = False
            else:
                nlattrs = self.parse_nlattrs(self.attrs[TCA_ACT_OPTIONS])
                if TCA_U32_SEL in nlattrs and TCA_U32_CLASSID in nlattrs:
                    self.has_u32_sel = True
                    self.classid = self.template._handle_to_str(
                        struct.unpack('I', nlattrs[TCA_U32_CLASSID])[0])
                    qos_filter = self.data_to_qos_filter(nlattrs[TCA_U32_SEL])
                    qos_filter['prio'] = self.template.prio
                    self.qos_filter_dict = qos_filter
                else:
                    self.has_u32_sel = False


class RTNetLink(netns.NetNSSwitcher):
    _recv_msg_class = {
        RecvIfInfoMsg._msg_type: RecvIfInfoMsg,
        RecvQdiscMsg._msg_type: RecvQdiscMsg,
        RecvTClassMsg._msg_type: RecvTClassMsg,
        RecvTFilterMsg._msg_type: RecvTFilterMsg,
    }

    def __init__(self, netns=None):
        super(RTNetLink, self).__init__(netns)

    def __enter__(self):
        super(RTNetLink, self).__enter__()
        self._sock = socket.socket(
            socket.AF_NETLINK, socket.SOCK_RAW, socket.NETLINK_ROUTE)
        self._sock.bind((self._pid, 0))
        self._seq = int(time.time())
        self._sfd = os.fdopen(self._sock.fileno(), 'w+b')
        return self

    def __exit__(self, e_type, e_value, traceback):
        super(RTNetLink, self).__exit__(e_type, e_value, traceback)
        self._sfd.close()
        self._sock.close()

    def send_and_recv(self, msg):
        msgs = []
        self._seq += 1
        msg.header.seq = self._seq
        self._sfd.write(msg.data)
        recv_header = NLM_Header.from_data(self._sfd.read(NLM_Header.length))
        if recv_header.msg_type != NLMSG_ERROR:
            while recv_header.msg_type != NLMSG_DONE:
                body_length = recv_header.length - NLM_Header.length
                recv_msg = self._recv_msg_class[recv_header.msg_type](
                    recv_header)
                recv_msg.parse_msg(self._sfd.read(body_length))
                msgs.append(recv_msg)
                recv_header = NLM_Header.from_data(
                    self._sfd.read(NLM_Header.length))
        self._sfd.read(recv_header.length-NLM_Header.length)
        return msgs


def get_qos_conf_scheme(router_id=None, filter_by_name=None):
    namespace = None
    if router_id:
        namespace = 'qrouter-' + router_id

    ret = {}

    with RTNetLink(namespace) as n:
        if namespace and not n.in_namespace:
            return None
        index_to_name = {}
        for ifinfo in n.send_and_recv(GetIfInfoMsg()):
            index_to_name[ifinfo.template.ifindex] = ifinfo.name
            if filter_by_name and not filter_by_name(ifinfo.name):
                continue
            ret[ifinfo.name] = {}
        for qdisc in n.send_and_recv(GetQdiscMsg()):
            ifindex = qdisc.template.ifindex
            if filter_by_name and not filter_by_name(index_to_name[ifindex]):
                continue
            if not qdisc.is_root_htb:
                continue

            # Classes
            tmp_parent = {}
            classes = {}
            ret[index_to_name[ifindex]] = classes
            for tclass in n.send_and_recv(GetTClassMsg(ifindex=ifindex)):
                if not tclass.is_htb:
                    continue
                handle = tclass.template.handle_str
                parent = tclass.template.parent_str
                classes[handle] = {
                    'rate': tclass.rate, 'ceil': tclass.ceil,
                    'buffer': tclass.bucket, 'cbuffer': tclass.cbucket,
                    'prio': tclass.prio, 'parent': parent,
                    'subclasses': tmp_parent.pop(handle, []), 'filters': []
                }
                # Add this class the its parent's subclasses list
                if parent is not None:
                    if parent in classes:
                        classes[parent]['subclasses'].append(handle)
                    # Deal with those parents which are not yet processed
                    elif parent in tmp_parent:
                        tmp_parent[parent].append(handle)
                    else:
                        tmp_parent[parent] = [handle]

            # Filters
            for tfilter in n.send_and_recv(GetTFilterMsg(ifindex=ifindex)):
                if not tfilter.has_u32_sel:
                    continue
                classes[tfilter.classid]['filters'].append(
                    tfilter.qos_filter_dict)

    return ret


# TC burst size to bucket tokens calculator
TIME_UNITS_PER_SEC = 1000000

_psched = open('/proc/net/psched', 'r')
[t2us, us2t, clock_res, hz] = [int(i, 16) for i in _psched.read().split()]
_psched.close()

HZ = hz if clock_res == 1000000 else os.environ.get('HZ', 1000)
TICKS_IN_USEC = (
    1 if clock_res == 1000000000 else float(t2us)/us2t
) * (float(clock_res) / TIME_UNITS_PER_SEC)


def calc_bucket_tokens(rate, size):
    time = int(TIME_UNITS_PER_SEC * (float(size)/rate))
    ticks = int(time * TICKS_IN_USEC)
    return ticks
