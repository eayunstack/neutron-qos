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

from neutron.common import rpc as n_rpc
from neutron.db.qos import qos_db
from neutron.services.qos.common import topics


class QosRpcCallback(n_rpc.RpcCallback):

    RPC_API_VERSION = '1.0'

    def __init__(self, qos_plugin):
        super(QosRpcCallback, self).__init__()
        self.qos_plugin = qos_plugin

    def sync_qos(self, context, host):
        return self.qos_plugin.sync_qos(context, host)


class QosAgentRpc(n_rpc.RpcProxy):

    RPC_API_VERSION = '1.0'

    def __init__(self):
        super(QosAgentRpc, self).__init__(
            topic=topics.QOS_AGENT, default_version=self.RPC_API_VERSION)


class QosPlugin(qos_db.QosDb, qos_db.QosPluginRpcDbMixin):

    supported_extension_aliases = ['qos']

    def __init__(self):
        super(QosPlugin, self).__init__()

        self.endpoints = [QosRpcCallback(self)]

        self.conn = n_rpc.create_connection(new=True)
        self.conn.create_consumer(
            topics.QOS_PLUGIN, self.endpoints, fanout=False)
        self.conn.consume_in_threads()

        self.agent_rpc = QosAgentRpc()
