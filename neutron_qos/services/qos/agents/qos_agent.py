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
import eventlet

from oslo.config import cfg

from neutron.agent.common import config
from neutron.agent import rpc as agent_rpc
from neutron.common import config as common_config
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.openstack.common import service
from neutron.openstack.common import log as logging
from neutron.openstack.common import lockutils
from neutron.openstack.common import loopingcall
from neutron.openstack.common import periodic_task
from neutron.services.qos.agents.tc_manager import TcManager
from neutron.services.qos.common import topics as qos_topics
from neutron import service as neutron_service
from neutron import context
from neutron import manager

eventlet.monkey_patch()
LOG = logging.getLogger(__name__)


class QosPluginRpc(n_rpc.RpcProxy):

    RPC_API_VERSION = '1.0'

    def __init__(self, topic, host):
        super(QosPluginRpc, self).__init__(
            topic=topic, default_version=self.RPC_API_VERSION)
        self.host = host

    def sync_qos(self, context):
        return self.call(
            context,
            self.make_msg('sync_qos', host=self.host))


class QosAgent(manager.Manager):

    Opts = [
        cfg.IntOpt('report_interval', default=300,
                   help=_("Interval between two qos reports")),
    ]

    RPC_API_VERSION = '1.0'

    def __init__(self, host, conf=None):
        super(QosAgent, self).__init__(host=host)
        self.conf = conf or cfg.CONF
        self.context = context.get_admin_context_without_session()
        self.host = host
        self.root_helper = config.get_root_helper(self.conf)
        self.plugin_rpc = QosPluginRpc(qos_topics.QOS_PLUGIN, self.host)

    def _compare_and_configure_qos(self, current, target, namespace):
        LOG.debug('Current is %(current)s, target is %(target)s.',
                  {'current': current, 'target': target})
        for t in target:
            devices = t['devices']
            scheme = t['scheme']
            for device in devices:
                if device not in current:
                    LOG.debug('Device %(device) is not on this host.',
                              {'device': device})
                    continue
                tcmanager = TcManager(device, namespace,
                                      root_helper=self.root_helper)
                tcmanager.apply_changes(current.pop(device), scheme)
        for device, scheme in current.iteritems():
            # Removed QoS
            if scheme:
                TcManager.destroy_root_qdisc(
                    device, namespace,
                    root_helper=self.root_helper)

    @lockutils.synchronized('qos-agent', 'neutron-')
    def _handle_qos_dict(self, qos_dict):
        for namespace, target in qos_dict.iteritems():
            if namespace == '_root':
                namespace = None
            hosting_qos = TcManager.get_hosting_qos(
                namespace, root_helper=self.root_helper)
            if hosting_qos is None:
                LOG.debug('Targets not found in namespace %s on this host',
                          namespace)
                continue
            self._compare_and_configure_qos(
                hosting_qos, target, namespace)

    @periodic_task.periodic_task(run_immediately=True)
    def _sync_qos_task(self, context):
        qos_dict = self.plugin_rpc.sync_qos(context)
        LOG.debug("Qos on this host from server: %s", qos_dict)
        self._handle_qos_dict(qos_dict)


class QosAgentWithStateReport(QosAgent):

    def __init__(self, host, conf=None):
        super(QosAgentWithStateReport, self).__init__(
            host=host, conf=conf)
        self.state_rpc = agent_rpc.PluginReportStateAPI(topics.PLUGIN)
        self.agent_state = {
            'binary': 'neutron-qos-agent',
            'host': host,
            'topic': qos_topics.QOS_AGENT,
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
        topic=qos_topics.QOS_AGENT,
        manager='neutron.services.qos.agents.'
                'qos_agent.QosAgentWithStateReport')
    service.launch(server).wait()
