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

import sys
import uuid
import eventlet
eventlet.monkey_patch()


from oslo.config import cfg

from neutron.api.rpc.agentnotifiers import qos_rpc_agent_api
from neutron.agent.common import config
from neutron.agent import rpc as agent_rpc
from neutron.agent.linux import utils
from neutron.common import config as common_config
from neutron.common import topics
from neutron.openstack.common import service
from neutron.openstack.common import log as logging
from neutron.openstack.common import loopingcall
from neutron.openstack.common import periodic_task
from neutron import service as neutron_service
from neutron import context
from neutron import manager

LOG = logging.getLogger(__name__)

# Qos Info Dictionary:
# Qos:
# {
#     'id': {
#         'target_type': xxx,
#         'target_id': xxx,
#         'devices': [],
#         'rate': xxx,
#         'burst': xxx,
#         'cburst': xxx,
#         'default_queue_id': xxx
#         'queues': [xxx, ...]
#         'registered_classes': {
#             '1':  'me'
#             'fffe': 'default_queue_id'
#             'class1': 'queue_id1'
#         },
#     },
#     'id2': {
#     },
# }
# Queue:
# {
#     'id': {
#         'qos_id': xxx,
#         'class': xxx,
#         'parent_id': xxx,
#         'prio': xxx,
#         'rate': xxx,
#         'ceil' xxx,
#         'burst': xxx,
#         'cburst': xxx,
#         'subqueues': [xxx, ...],
#         'filters': [xxx, ...],
#     },
#     'id2': {
#     },
# }
# Filter:
# {
#     'id': {
#         'qos_id': xxx,
#         'queue_id': xxx,
#         'prio': xxx,
#         'protocol': xxx,
#         'src_port' xxx,
#         'dst_port': xxx,
#         'src_addr': xxx,
#         'dst_addr': xxx,
#         'custom_match': xxx,
#     },
#     'id2': {
#     },
# }


class QosAgent(qos_rpc_agent_api.QosPluginRpc, manager.Manager):

    Opts = [
        cfg.IntOpt('report_interval', default=300,
                   help=_("Interval between two qos reports")),
    ]

    def __init__(self, host, conf=None):
        self.conf = conf or cfg.CONF
        self.context = context.get_admin_context_without_session()
        self.host = host
        self.qos_info = {'qos': {}, 'queue': {}, 'filter': {}}
        self.root_helper = config.get_root_helper(self.conf)
        super(QosAgent, self).__init__(host=host)

    def _run_tc(self, cmd, namespace=''):
        if namespace:
            cmd = ['ip', 'netns', 'exec', namespace] + cmd
        return utils.execute(cmd, root_helper=self.root_helper,
                             check_exit_code=False)

    def _tc_add_qos(self, qos_id):
        qos = self.qos_info['qos'][qos_id]

        if qos['target_type'] == 'router':
            namespace = ("qrouter-%s" % qos['target_id'])
        else:
            namespace = ''

        rate = ("%sbps" % qos['rate'])
        ceil = ("%sbps" % qos['rate'])
        for device in qos['devices']:
            # delete the existing one in case of agent has restarted
            del_qdisc = [
                'tc', 'qdisc', 'del', 'dev', device,
                'root', 'handle', '1:', 'htb'
            ]
            self._run_tc(del_qdisc, namespace)

            add_qdisc = [
                'tc', 'qdisc', 'replace', 'dev', device,
                'root', 'handle', '1:', 'htb', 'default', 'fffe'
            ]
            add_class = [
                'tc', 'class', 'replace', 'dev', device,
                'parent', '1:0', 'classid', '1:1', 'htb',
                'rate', rate, 'ceil', ceil
            ]
            if qos['burst']:
                add_class.extend(['burst', qos['burst']])
            if qos['cburst']:
                add_class.extend(['cburst', qos['cburst']])

            self._run_tc(add_qdisc, namespace)
            self._run_tc(add_class, namespace)

    def _tc_update_qos(self, qos_id):
        qos = self.qos_info['qos'][qos_id]

        if qos['target_type'] == 'router':
            namespace = ("qrouter-%s" % qos['target_id'])
        else:
            namespace = ''

        rate = ("%sbps" % qos['rate'])
        ceil = ("%sbps" % qos['rate'])
        for device in qos['devices']:
            change_class = [
                'tc', 'class', 'change', 'dev', device,
                'parent', '1:0', 'classid', '1:1', 'htb',
                'rate', rate, 'ceil', ceil
            ]
            if qos['burst']:
                change_class.extend(['burst', qos['burst']])
            if qos['cburst']:
                change_class.extend(['cburst', qos['cburst']])

            self._run_tc(change_class, namespace)

    def _tc_delete_qos(self, qos_id):
        qos = self.qos_info['qos'][qos_id]

        if qos['target_type'] == 'router':
            namespace = ("qrouter-%s" % qos['target_id'])
        else:
            namespace = ''

        for device in qos['devices']:
            del_qdisc = [
                'tc', 'qdisc', 'del', 'dev', device,
                'root', 'handle', '1:', 'htb'
            ]
            self._run_tc(del_qdisc, namespace)

    def _tc_add_queue(self, queue_id):
        queue = self.qos_info['queue'][queue_id]
        qos = self.qos_info['qos'][queue['qos_id']]

        if qos['target_type'] == 'router':
            namespace = ("qrouter-%s" % qos['target_id'])
        else:
            namespace = ''

        if queue['parent_id']:
            parent_class = self.qos_info['queue'][queue['parent_id']]['class']
        else:
            parent_class = 1
        parent_id = "1:%s" % parent_class
        class_id = "1:%s" % queue['class']
        rate = ("%sbps" % queue['rate'])
        for device in qos['devices']:
            add_class = [
                'tc', 'class', 'replace', 'dev', device,
                'parent', parent_id, 'classid', class_id, 'htb',
                'rate', rate
            ]
            if queue['prio']:
                add_class.extend(['prio', queue['prio']])
            if queue['ceil']:
                ceil = ("%sbps" % queue['ceil'])
                add_class.extend(['ceil', ceil])
            if queue['burst']:
                add_class.extend(['burst', queue['burst']])
            if queue['cburst']:
                add_class.extend(['cburst', queue['cburst']])

            self._run_tc(add_class, namespace)

    def _tc_update_queue(self, queue_id):
        queue = self.qos_info['queue'][queue_id]
        qos = self.qos_info['qos'][queue['qos_id']]

        if qos['target_type'] == 'router':
            namespace = ("qrouter-%s" % qos['target_id'])
        else:
            namespace = ''

        if queue['parent_id']:
            parent_class = self.qos_info['queue'][queue['parent_id']]['class']
        else:
            parent_class = 1
        parent_id = "1:%s" % parent_class
        class_id = "1:%s" % queue['class']
        rate = ("%sbps" % queue['rate'])
        for device in qos['devices']:
            change_class = [
                'tc', 'class', 'change', 'dev', device,
                'parent', parent_id, 'classid', class_id, 'htb',
                'rate', rate
            ]
            if queue['prio']:
                change_class.extend(['prio', queue['prio']])
            if queue['ceil']:
                ceil = ("%sbps" % queue['ceil'])
                change_class.extend(['ceil', ceil])
            if queue['burst']:
                change_class.extend(['burst', queue['burst']])
            if queue['cburst']:
                change_class.extend(['cburst', queue['cburst']])

            self._run_tc(change_class, namespace)

    def _tc_delete_queue(self, queue_id):
        queue = self.qos_info['queue'][queue_id]
        qos = self.qos_info['qos'][queue['qos_id']]

        if qos['target_type'] == 'router':
            namespace = ("qrouter-%s" % qos['target_id'])
        else:
            namespace = ''

        if queue['parent_id']:
            parent_class = self.qos_info['queue'][queue['parent_id']]['class']
        else:
            parent_class = 1
        parent_id = "1:%s" % parent_class
        class_id = "1:%s" % queue['class']
        for device in qos['devices']:
            delete_class = [
                'tc', 'class', 'del', 'dev', device,
                'parent', parent_id, 'classid', class_id
            ]
            self._run_tc(delete_class, namespace)

    def _tc_add_filter(self, filter_id):
        qf = self.qos_info['filter'][filter_id]
        qos = self.qos_info['qos'][qf['qos_id']]

        if qos['target_type'] == 'router':
            namespace = ("qrouter-%s" % qos['target_id'])
        else:
            namespace = ''

        flowid = "1:%s" % self.qos_info['queue'][qf['queue_id']]['class']
        for device in qos['devices']:
            add_filter = [
               'tc', 'filter', 'add', 'dev', device,
               'protocol', 'ip', 'parent', '1:0', 'prio', qf['prio']
            ]
            selector = []
            selector.extend(['u32'])
            if qf['protocol']:
                selector.extend([
                    'match', 'ip', 'protocol', qf['protocol'], '0xff'
                ])
            if qf['src_port']:
                selector.extend([
                    'match', 'ip', 'sport', qf['src_port'], '0xffff'
                ])
            if qf['dst_port']:
                selector.extend([
                    'match', 'ip', 'dport', qf['dst_port'], '0xffff'
                ])
            if qf['src_addr']:
                selector.extend([
                    'match', 'ip', 'src', qf['src_addr']
                ])
            if qf['dst_addr']:
                selector.extend([
                    'match', 'ip', 'dst', qf['dst_addr']
                ])
            if len(selector) > 1:
                add_filter.extend(selector)
            add_filter.extend(['flowid', flowid])

            self._run_tc(add_filter, namespace)

    def _tc_delete_filter(self, filter_id):
        qf = self.qos_info['filter'][filter_id]
        qos = self.qos_info['qos'][qf['qos_id']]

        if qos['target_type'] == 'router':
            namespace = ("qrouter-%s" % qos['target_id'])
        else:
            namespace = ''

        for device in qos['devices']:
            del_filter = [
               'tc', 'filter', 'del', 'dev', device,
               'protocol', 'ip', 'parent', '1:0', 'prio', qf['prio']
            ]
            self._run_tc(del_filter, namespace)

    # Here start the deletion part
    def _remove_queue_from_qos(self, queue_id):
        queue = self.qos_info['queue'][queue_id]
        qos_id = queue['qos_id']
        registered_class = queue['class']

        qos = self.qos_info['qos'][qos_id]
        qos['queues'].remove(queue_id)
        qos['registered_classes'].pop(registered_class)

    def _remove_subqueue_from_queue(self, subqueue_id):
        subqueue = self.qos_info['queue'][subqueue_id]
        parent_queue_id = subqueue['parent_id']
        parent_queue = self.qos_info['queue'][parent_queue_id]
        parent_queue['subqueues'].remove(subqueue_id)

    def _remove_filter_from_queue(self, filter_id):
        queue_id = self.qos_info['filter'][filter_id]['queue_id']
        self.qos_info['queue'][queue_id]['filters'].remove(filter_id)

    def _delete_qos(self, qos_id, info_only=False):
        if not info_only:
            self._tc_delete_qos(qos_id)
        for queue_id in self.qos_info['qos'][qos_id]['queues']:
            self._delete_queue(queue_id, info_only=True)
        del self.qos_info['qos'][qos_id]

    def _delete_queue(self, queue_id, info_only=False):
        for filter_id in self.qos_info['queue'][queue_id]['filters']:
            self._delete_filter(filter_id, info_only=info_only)
        for subqueue_id in self.qos_info['queue'][queue_id]['subqueues']:
            self._delete_queue(subqueue_id, info_only=info_only)
        if not info_only:
            self._tc_delete_queue(queue_id)
        if self.qos_info['queue'][queue_id]['parent_id']:
            self._remove_subqueue_from_queue(queue_id)
        self._remove_queue_from_qos(queue_id)
        del self.qos_info['queue'][queue_id]

    def _delete_filter(self, filter_id, info_only=False):
        self._remove_filter_from_queue(filter_id)
        if not info_only:
            self._tc_delete_filter(filter_id)
        del self.qos_info['filter'][filter_id]

    # Here start the addition part
    def _add_queue_to_qos(self, queue_id):
        queue = self.qos_info['queue'][queue_id]
        qos_id = queue['qos_id']

        qos = self.qos_info['qos'][qos_id]
        qos['queues'].append(queue_id)

        if qos['default_queue_id'] == queue_id:
            class_id = 'fffe'
        else:
            class_id = queue_id[:4]
            while class_id in qos['registered_classes']:
                class_id = str(uuid.uuid4())[:4]
            qos['registered_classes'].update({class_id: queue_id})

        queue.update({'class': class_id})

    def _add_subqueue_to_parent(self, subqueue_id):
        subqueue = self.qos_info['queue'][subqueue_id]
        parent_queue_id = subqueue['parent_id']
        if parent_queue_id:
            parent_queue = self.qos_info['queue'][parent_queue_id]
            parent_queue['subqueues'].append(subqueue_id)

    def _add_filter_to_queue(self, filter_id):
        queue_id = self.qos_info['filter'][filter_id]['queue_id']
        queue = self.qos_info['queue'][queue_id]
        queue['filters'].append(filter_id)

    def _add_qos(self, qos):
        qos_id = qos['id']
        added_qos = {
            'target_type': qos['target_type'],
            'target_id': qos['target_id'],
            'devices': qos['devices'],
            'rate': qos['rate'],
            'burst': qos['burst'],
            'cburst': qos['cburst'],
            'default_queue_id': qos['default_queue_id'],
            'queues': [],
            'registered_classes': {
                '0001': 'myself',
                'fffe': qos['default_queue_id'],
            },
        }
        self.qos_info['qos'][qos_id] = added_qos
        self._tc_add_qos(qos_id)
        for queue in qos['qos_queues']:
            self._add_queue(queue)

    def _add_queue(self, queue):
        queue_id = queue['id']
        added_queue = {
            'qos_id': queue['qos_id'],
            'class': None,  # class should be updated when add to qos
            'parent_id': queue['parent_id'],
            'prio': queue['prio'],
            'rate': queue['rate'],
            'ceil': queue['ceil'],
            'burst': queue['burst'],
            'cburst': queue['cburst'],
            'subqueues': [],
            'filters': [],
        }
        self.qos_info['queue'][queue_id] = added_queue
        self._add_queue_to_qos(queue_id)
        self._add_subqueue_to_parent(queue_id)
        self._tc_add_queue(queue_id)
        for subqueue in queue['subqueues']:
            self._add_queue(subqueue)
        for qos_filter in queue['attached_filters']:
            self._add_filter(qos_filter)

    def _add_filter(self, qos_filter):
        qf_id = qos_filter['id']
        qf = {
            'qos_id': qos_filter['qos_id'],
            'queue_id': qos_filter['queue_id'],
            'prio': qos_filter['prio'],
            'protocol': qos_filter['protocol'],
            'src_port': qos_filter['src_port'],
            'dst_port': qos_filter['dst_port'],
            'src_addr': qos_filter['src_addr'],
            'dst_addr': qos_filter['dst_addr'],
            'custom_match': qos_filter.get('custom_match', None),
        }
        self.qos_info['filter'][qf_id] = qf
        self._tc_add_filter(qf_id)
        self._add_filter_to_queue(qf_id)

    # Here start the update part
    def _update_qos(self, qos):
        qos_id = qos['id']
        if qos_id not in self.qos_info['qos']:
            self._add_qos(qos)
        elif self.qos_info['qos'][qos_id]['devices'] == qos['devices']:
            updated_qos = {
                'rate': qos['rate'],
                'burst': qos['burst'],
                'cburst': qos['cburst'],
            }
            self.qos_info['qos'][qos_id].update(updated_qos)
            self._tc_update_qos(qos_id)
            for queue in qos['qos_queues']:
                if queue['id'] == qos['default_queue_id']:
                    self._update_queue(queue)
        else:
            self._delete_qos(qos_id)
            self._add_qos(qos)

    def _update_queue(self, queue):
        queue_id = queue['id']
        updated_queue = {
            'prio': queue['prio'],
            'rate': queue['rate'],
            'ceil': queue['ceil'],
            'burst': queue['burst'],
            'cburst': queue['cburst'],
        }
        self.qos_info['queue'][queue_id].update(updated_queue)
        self._tc_update_queue(queue_id)

    def _update_filter(self, qos_filter):
        # filter has no class/handle for "tc change"
        self._delete_filter(qos_filter['id'])
        self._add_filter(qos_filter)

    @periodic_task.periodic_task(run_immediately=True)
    def _sync_qos_task(self, context):
        qos = self._sync_qos(context, self.qos_info['qos'].keys())
        for deleted_qos in qos['deleted']:
            self._delete_qos(deleted_qos, info_only=True)
        for added_qos in qos['added']:
            self._add_qos(added_qos)

    def qos_created(self, context, payload):
        self._add_qos(payload)

    def qos_updated(self, context, payload):
        self._update_qos(payload)

    def qos_moved(self, context, payload):
        self._delete_qos(payload)

    def qos_deleted(self, context, payload):
        self._delete_qos(payload)

    def qos_queue_created(self, context, payload):
        self._add_queue(payload)

    def qos_queue_updated(self, context, payload):
        self._update_queue(payload)

    def qos_queue_deleted(self, context, payload):
        self._delete_queue(payload)

    def qos_filter_created(self, context, payload):
        self._add_filter(payload)

    def qos_filter_updated(self, context, payload):
        self._update_filter(payload)

    def qos_filter_deleted(self, context, payload):
        self._delete_filter(payload)


class QosAgentWithStateReport(QosAgent):

    def __init__(self, host, conf=None):
        super(QosAgentWithStateReport, self).__init__(
            host=host, conf=conf)
        self.state_rpc = agent_rpc.PluginReportStateAPI(topics.PLUGIN)
        self.agent_state = {
            'binary': 'neutron-qos-agent',
            'host': host,
            'topic': qos_rpc_agent_api.QOS_AGENT,
            'configurations': {
                'report_interval': self.conf.report_interval,
            },
            'start_flag': True,
            'agent_type': 'Qos agent',
        }
        report_interval = cfg.CONF.AGENT.report_interval
        self.use_call = True
        if report_interval:
            self.heartbeat = loopingcall.FixedIntervalLoopingCall(
                self._report_state)
            self.heartbeat.start(interval=report_interval)

    def _report_state(self):
        try:
            self.state_rpc.report_state(self.context, self.agent_state,
                                        self.use_call)
            self.agent_state.pop('start_flag', None)
            self.use_call = False
        except AttributeError:
            # This means the server does not support report_state
            LOG.warn("Neutron server does not support state report."
                     " State report for this agent will be disabled.")
            self.heartbeat.stop()
            return
        except Exception:
            LOG.exception("Failed reporting state!")

    def agent_updated(self, context, payload):
        LOG.info("agent_updated by server side %s!", payload)


def main():
    conf = cfg.CONF
    conf.register_opts(QosAgent.Opts)
    config.register_agent_state_opts_helper(conf)
    config.register_root_helper(conf)
    common_config.init(sys.argv[1:])
    config.setup_logging()
    server = neutron_service.Service.create(
        binary='neutron-qos-agent',
        topic=qos_rpc_agent_api.QOS_AGENT,
        manager='neutron.services.qos.agents.'
                'qos_agent.QosAgentWithStateReport')
    service.launch(server).wait()
