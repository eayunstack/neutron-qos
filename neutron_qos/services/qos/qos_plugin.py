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

from neutron.api.rpc.agentnotifiers import qos_rpc_agent_api
from neutron.common import rpc as n_rpc
from neutron.db.qos import qos_rpc


class QosPlugin(qos_rpc.QosServerRpcServerMixin):

    supported_extension_aliases = ['qos']

    def __init__(self):
        super(QosPlugin, self).__init__()

        self.endpoints = [qos_rpc.QosRpcCallbacks(self)]

        self.conn = n_rpc.create_connection(new=True)
        self.conn.create_consumer(
            qos_rpc_agent_api.QOS_PLUGIN, self.endpoints, fanout=False)
        self.conn.consume_in_threads()

        self.notifier = qos_rpc_agent_api.QosAgentNotifyAPI()
