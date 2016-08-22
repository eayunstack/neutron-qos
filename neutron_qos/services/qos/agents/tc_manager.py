# Copyright (c) 2016 Eayun, Inc.
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
"""Wrapper for tc."""

import json

from neutron.agent.linux import utils as linux_utils
from neutron.common import utils
from neutron.services.qos.common import htb

utils.synchronized('tc', external=True)

ROUTER_NS_PREFIX = 'qrouter-'


class TcManager(object):
    """Wrapper for tc."""

    @staticmethod
    def get_hosting_qos(namespace, root_helper=None):
        """Get concerned hosting qos."""
        cmd = ['neutron-get-htb-conf']
        if namespace:
            cmd = ['ip', 'netns', 'exec', namespace] + cmd
            prefix = 'qr-,qg-'
        else:
            prefix = 'qvo,qvb'
        cmd += ['--prefix', prefix]
        try:
            return json.loads(
                linux_utils.execute(cmd, root_helper=root_helper))
        except RuntimeError:
            return None

    @staticmethod
    def build_handle_for_class(tc_class):
        """Build the handle for a tc class minor."""
        if not tc_class:
            return None
        else:
            return '1:' + hex(tc_class)[2:]

    @staticmethod
    def add_root_qdisc(device, namespace, root_helper=None):
        """Add the root htb qdisc for device."""
        cmd = ['tc', 'qdisc', 'add', 'dev', device, 'root', 'handle',
               '1:0', 'htb', 'default', 'fffe']
        if namespace:
            cmd = ['ip', 'netns', 'exec', namespace] + cmd
        linux_utils.execute(cmd, root_helper=root_helper)

    @staticmethod
    def destroy_root_qdisc(device, namespace, root_helper=None):
        """Delete the root htb qdisc for device."""
        cmd = ['tc', 'qdisc', 'del', 'dev', device, 'root']
        if namespace:
            cmd = ['ip', 'netns', 'exec', namespace] + cmd
        linux_utils.execute(cmd, root_helper=root_helper,
                            check_exit_code=False)

    def __init__(self, device, namespace, execute=None, root_helper=None):
        self.device = device
        self.current = None
        self.target = None
        self.namespace = namespace
        self.execute = execute or linux_utils.execute
        self.root_helper = root_helper
        self.changes = {'to_delete': [], 'to_add': []}

    def replace_class(self, parent, handle, target):
        """Prepare for replacing the tc class."""
        cmd = ['tc', 'class', 'replace', 'dev', self.device]
        if parent:
            cmd += ['parent', parent]
        rate = '%sbps' % target['rate']
        ceil = '%sbps' % target['ceil']
        cmd += ['classid', handle, 'htb', 'rate', rate, 'ceil', ceil]
        burst = target.get('burst', None)
        cburst = target.get('cburst', None)
        if burst:
            cmd += ['burst', burst]
        if cburst:
            cmd += ['cburst', cburst]
        cmd += ['prio', target['prio']]
        self.changes['to_add'].append(cmd)

    def delete_class(self, handle, current_class):
        """Prepare for deleting the tc class."""
        for tc_filter in current_class.get('filters', []):
            prio = tc_filter['prio']
            cmd = ['tc', 'filter', 'delete', 'dev', self.device, 'prio', prio]
            self.changes['to_delete'].append(cmd)
        for subclass in current_class.get('subclasses', []):
            self.delete_class(subclass, self.current.pop(subclass, {}))
        cmd = ['tc', 'class', 'delete', 'dev', self.device, 'classid', handle]
        self.changes['to_delete'].append(cmd)

    def replace_filter(self, handle, tc_filter):
        """Prepare for replacing the tc filter."""
        protocol = tc_filter.get('protocol', None)
        src_port = tc_filter.get('src_port', None)
        dst_port = tc_filter.get('dst_port', None)
        cmd = ['tc', 'filter', 'replace', 'dev', self.device,
               'protocol', 'ip', 'parent', '1:0', 'prio', tc_filter['prio'],
               'u32']
        cmd.extend(['match', 'ip', 'src', tc_filter['src_addr']])
        cmd.extend(['match', 'ip', 'dst', tc_filter['dst_addr']])
        if protocol:
            cmd.extend(['match', 'ip', 'protocol', protocol, '0xff'])
        if src_port:
            cmd.extend(['match', 'ip', 'sport', src_port, '0xffff'])
        if dst_port:
            cmd.extend(['match', 'ip', 'dport', dst_port, '0xffff'])
        cmd.extend(['flowid', handle])
        self.changes['to_add'].append(cmd)

    def delete_filter(self, prio):
        """Prepare for deleting the tc filter."""
        cmd = ['tc', 'filter', 'delete', 'dev', self.device,
               'protocol', 'ip', 'parent', '1:0', 'prio', prio]
        self.changes['to_delete'].append(cmd)

    def change_filter(self, handle, new, old):
        """Check whether a tc filter should be changed and then do it."""
        changed = False
        changed |= new['src_addr'] != old.get('src_addr', '')
        changed |= new['dst_addr'] != old.get('dst_addr', '')
        changed |= new.get('protocol', 0) != old.get('protocol', 0)
        changed |= new.get('src_addr', 0) != old.get('src_addr', 0)
        changed |= new.get('dst_addr', 0) != old.get('dst_addr', 0)
        if changed:
            self.replace_filter(handle, new)

    def change_filters(self, handle, new_filters, old_filters):
        """Change filters attached to a class."""

        def _tcfilter_list_to_dict(tcfilters):
            return {
                tcfilter['prio']: tcfilter
                for tcfilter in tcfilters
            }

        new_filters = _tcfilter_list_to_dict(new_filters)
        old_filters = _tcfilter_list_to_dict(old_filters)

        new_prios = set(new_filters.keys())
        old_prios = set(old_filters.keys())

        for prio in new_prios - old_prios:
            # Newly added filters
            self.replace_filter(handle, new_filters[prio])
        for prio in old_prios - new_prios:
            # Deleted filters
            self.delete_filter(prio)
        for prio in new_prios.intersection(old_prios):
            # Filters that might be changed
            self.change_filter(handle, new_filters[prio], old_filters[prio])

    def collect_garbage_class(self):
        """Prepare for deleting the garbage tc classes."""
        # If classes remain in self.current, delete them
        for classid, setting in self.current.items():
            if setting['parent'] not in self.current:
                self.delete_class(classid, setting)

    def change_class(self, tc_class):
        """Change a tc class."""
        target = self.target.pop(str(tc_class))
        new_buffer = htb.calc_bucket_tokens(
            target['rate'], target.get('burst', 1600))
        new_cbuffer = htb.calc_bucket_tokens(
            target['ceil'], target.get('cburst', 1600))

        handle = self.build_handle_for_class(tc_class)
        qdisc_handle = hex(tc_class)[2:] + ':0'
        current = self.current.pop(handle, {})

        class_changed = False
        parent = self.build_handle_for_class(target.get('parent', None))

        if not current or parent != current['parent']:
            # Rebuild this class
            if tc_class == 1:
                self.destroy_root_qdisc(self.device, self.namespace,
                                        root_helper=self.root_helper)
                self.add_root_qdisc(self.device, self.namespace,
                                    root_helper=self.root_helper)
                self.current = {}
            elif current:
                self.delete_class(handle, current)
            current = {}
            class_changed = True
        else:
            class_changed |= target['rate'] != current['rate']
            class_changed |= target['ceil'] != current['ceil']
            class_changed |= target['prio'] != current['prio']
            class_changed |= new_buffer != current['buffer']
            class_changed |= new_cbuffer != current['cbuffer']

        if class_changed:
            self.replace_class(parent, handle, target)

        subclasses = target.get('subclasses', [])
        if subclasses:
            if not current.get('subclasses', True):
                # This class was a leaf class, but now it's not
                cmd = ['tc', 'qdisc', 'del', 'dev', self.device,
                       'parent', handle, 'handle', qdisc_handle]
                self.changes['to_delete'].append(
                    (cmd, {'check_exit_code': False}))
            for subclass in subclasses:
                self.change_class(subclass)
        else:
            if current.get('subclasses', True):
                # This class is a newly added leaf class
                cmd = ['tc', 'qdisc', 'replace', 'dev', self.device,
                       'parent', handle, 'handle', qdisc_handle,
                       'sfq', 'perturb', '10']
                self.changes['to_add'].append(cmd)

        self.change_filters(
            handle, target.get('filters', []), current.get('filters', []))

    def _apply(self):
        cmd_prefix = []
        kwargs = {}
        if self.namespace:
            cmd_prefix = ['ip', 'netns', 'exec', self.namespace]
        for cmd in self.changes['to_delete'] + self.changes['to_add']:
            if type(cmd) == tuple:
                cmd, kwargs = cmd
            cmd = cmd_prefix + cmd
            linux_utils.execute(cmd, root_helper=self.root_helper, **kwargs)

    def apply_changes(self, current, target):
        """Calculate and apply the changes from current to target."""
        self.current = current
        self.target = target
        self.change_class(1)
        self.collect_garbage_class()
        self._apply()
