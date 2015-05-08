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

from oslo import messaging

from neutron.common import rpc as n_rpc
from neutron.openstack.common import log as logging

LOG = logging.getLogger(__name__)

QOS_AGENT = 'qos_agent'
QOS_PLUGIN = 'qos_plugin'


class QosAgentNotifyAPI(object):
    """ API for plugin to notify qos agent. """

    def __init__(self, topic=QOS_AGENT):
        self.topic = topic
        target = messaging.Target(topic=topic, version='1.0')
        self.client = n_rpc.get_client(target)

    def _notification(self, context, method, payload, host):
        if host:
            LOG.debug('Notify qos agent at %(topic)s.%(host)s '
                      'the message %(method)s',
                      {'topic': self.topic, 'host': host, 'method': method})
            cctxt = self.client.prepare(server=host)
            cctxt.cast(context, method, payload=payload)
        else:
            LOG.debug('Not notify qos agent at %(topic)s '
                      'the message %(method)s '
                      'due to no target host',
                      {'topic': self.topic, 'method': method})

    def qos_created(self, context, qos, host):
        self._notification(context, 'qos_created', qos, host)

    def qos_updated(self, context, qos, host):
        self._notification(context, 'qos_updated', qos, host)

    def qos_moved(self, context, qos, host):
        self._notification(context, 'qos_moved', qos, host)

    def qos_deleted(self, context, id, host):
        self._notification(context, 'qos_deleted', id, host)

    def qos_queue_created(self, context, qos_queue, host):
        self._notification(context, 'qos_queue_created', qos_queue, host)

    def qos_queue_updated(self, context, qos_queue, host):
        self._notification(context, 'qos_queue_updated', qos_queue, host)

    def qos_queue_deleted(self, context, id, host):
        self._notification(context, 'qos_queue_deleted', id, host)

    def qos_filter_created(self, context, qos_filter, host):
        self._notification(context, 'qos_filter_created', qos_filter, host)

    def qos_filter_updated(self, context, qos_filter, host):
        self._notification(context, 'qos_filter_updated', qos_filter, host)

    def qos_filter_deleted(self, context, id, host):
        self._notification(context, 'qos_filter_deleted', id, host)


class QosPluginRpc(object):

    def __init__(self, host):
        super(QosPluginRpc, self).__init__()
        target = messaging.Target(topic=QOS_PLUGIN, version='1.0')
        self.client = n_rpc.get_client(target)

    def _sync_qos(self, context, qos_list):
        try:
            cctxt = self.client.prepare()
            return cctxt.call(
                context, 'sync_qos', host=self.host, qos_list=qos_list)
        except Exception:
            LOG.exception('Failed to sync qos.')
