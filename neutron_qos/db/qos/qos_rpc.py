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

from neutron.db.qos import qos_db
from neutron import manager
from neutron.extensions import qos as ext_qos
from neutron.openstack.common import log as logging
from neutron.plugins.common import constants as service_constants
from neutron.plugins.ml2 import db  # hacky

LOG = logging.getLogger(__name__)

NIC_NAME_LEN = 14


class QosServerRpcServerMixin(qos_db.QosDbMixin):

    def _get_host_from_qos_id(self, context, qos_id):
        qos = self._get_qos(context, qos_id)
        if qos['router_id'] is not None:
            plugin = manager.NeutronManager.get_service_plugins().get(
                service_constants.L3_ROUTER_NAT)
            adminContext = context if context.is_admin else context.elevated()
            l3_agents = plugin.get_l3_agents_hosting_routers(
                adminContext, [qos['router_id']],
                admin_state_up=True, active=True)
            return l3_agents[0].host
        elif qos['port_id'] is not None:
            """
            plugin = manager.NeutronManager.get_plugin()
            adminContext = context if context.is_admin else context.elevated()
            return plugin.get_port_binding_host(adminContext, qos['port_id'])
            """
            return db.get_port_binding_host(qos['port_id'])
        else:
            return None

    def _get_qos_on_host(self, context, host):
        hosting_qos = dict()
        for qos in self.get_qoss(context):
            if host == self._get_host_from_qos_id(context, qos['id']):
                qos.pop('unattached_filters')
                qos.update(
                    {'devices': self._get_qos_devices(context, qos['id'])})
                hosting_qos[qos['id']] = qos

        return hosting_qos

    def _get_qos_devices(self, context, qos_id):
        ret = []
        qos_db = self._get_qos(context, qos_id)
        if qos_db.router_id is not None:
            plugin = manager.NeutronManager.get_service_plugins().get(
                service_constants.L3_ROUTER_NAT)
            adminContext = context if context.is_admin else context.elevated()
            # A bit hacky here
            router = plugin._get_router(adminContext, qos_db.router_id)
            if qos_db.direction == 'egress':
                if router.gw_port_id:
                    ret.append(("qg-%s" % router.gw_port_id)[:NIC_NAME_LEN])
            else:
                for rp in router.attached_ports:
                    if rp.port_id != router.gw_port_id:
                        ret.append(("qr-%s" % rp.port_id)[:NIC_NAME_LEN])
        elif qos_db.port_id is not None:
            prefix = 'qvo' if qos_db.direction == 'ingress' else 'qvb'
            ret.append(("%s%s" % (prefix, qos_db.port_id))[:NIC_NAME_LEN])

        return ret

    def _check_port(self, context, port_id, tenant_id):
        plugin = manager.NeutronManager.get_plugin()
        adminContext = context if context.is_admin else context.elevated()
        port = plugin.get_port(adminContext, port_id)
        if not port['device_owner'].startswith('compute'):
            raise ext_qos.QosInvalidPortType(
                port_id=port_id, port_type=port['device_owner'])
        if not port['tenant_id'] == tenant_id:
            raise ext_qos.QosTargetNotOwnedByTenant(target_id=port_id)

    def _check_router(self, context, router_id, tenant_id):
        plugin = manager.NeutronManager.get_service_plugins().get(
            service_constants.L3_ROUTER_NAT)
        adminContext = context if context.is_admin else context.elevated()
        router = plugin.get_router(adminContext, router_id)
        if not router['tenant_id'] == tenant_id:
            raise ext_qos.QosTargetNotOwnedByTenant(target_id=router_id)

    def sync_qos(self, context, qos_list, host):
        hosting_qos = self._get_qos_on_host(context, host)
        deleted_qos = filter(lambda qos: qos not in hosting_qos, qos_list)

        for qos in qos_list:
            if qos in hosting_qos:
                hosting_qos.pop(qos)

        return {'deleted': deleted_qos, 'added': hosting_qos.values()}

    def create_qos(self, context, qos):
        qos = super(
            QosServerRpcServerMixin, self
        ).create_qos(context, qos)
        host = self._get_host_from_qos_id(context, qos['id'])
        unattached_filters = qos.pop('unattached_filters')
        qos.update({'devices': self._get_qos_devices(context, qos['id'])})
        self.notifier.qos_created(context, qos, host)
        qos.update({'unattached_filters': unattached_filters})
        qos.pop('devices')
        return qos

    def update_qos(self, context, id, qos):
        host_prev = self._get_host_from_qos_id(context, id)
        qos = super(
            QosServerRpcServerMixin, self
        ).update_qos(context, id, qos)
        host = self._get_host_from_qos_id(context, id)
        if host_prev != host:
            # assoicated port or router may be changed
            self.notifier.qos_moved(context, id, host_prev)
        unattached_filters = qos.pop('unattached_filters')
        qos.update({'devices': self._get_qos_devices(context, id)})
        self.notifier.qos_updated(context, qos, host)
        qos.update({'unattached_filters': unattached_filters})
        qos.pop('devices')
        return qos

    def delete_qos(self, context, id):
        host = self._get_host_from_qos_id(context, id)
        super(
            QosServerRpcServerMixin, self
        ).delete_qos(context, id)
        self.notifier.qos_deleted(context, id, host)

    def create_qos_queue(self, context, qos_queue):
        qos_queue = super(
            QosServerRpcServerMixin, self
        ).create_qos_queue(context, qos_queue)
        host = self._get_host_from_qos_id(context, qos_queue['qos_id'])
        self.notifier.qos_queue_created(context, qos_queue, host)
        return qos_queue

    def update_qos_queue(self, context, id, qos_queue):
        qos_queue = super(
            QosServerRpcServerMixin, self
        ).update_qos_queue(context, id, qos_queue)
        host = self._get_host_from_qos_id(context, qos_queue['qos_id'])
        self.notifier.qos_queue_updated(context, qos_queue, host)
        return qos_queue

    def delete_qos_queue(self, context, id):
        qos_queue = self._get_qos_queue(context, id)
        host = self._get_host_from_qos_id(context, qos_queue['qos_id'])
        super(
            QosServerRpcServerMixin, self
        ).delete_qos_queue(context, id)
        self.notifier.qos_queue_deleted(context, id, host)

    def create_qos_filter(self, context, qos_filter):
        qos_filter = super(
            QosServerRpcServerMixin, self
        ).create_qos_filter(context, qos_filter)
        if qos_filter['queue_id']:
            host = self._get_host_from_qos_id(context, qos_filter['qos_id'])
            self.notifier.qos_filter_created(context, qos_filter, host)
        return qos_filter

    def update_qos_filter(self, context, id, qos_filter):
        orig_queue_id = self.get_qos_filter(context, id)['queue_id']
        qos_filter = super(
            QosServerRpcServerMixin, self
        ).update_qos_filter(context, id, qos_filter)
        host = self._get_host_from_qos_id(context, qos_filter['qos_id'])
        if orig_queue_id is None:
            if qos_filter['queue_id']:
                self.notifier.qos_filter_created(context, qos_filter, host)
        else:
            if qos_filter['queue_id'] is None:
                self.notifier.qos_filter_deleted(context, id, host)
            else:
                self.notifier.qos_filter_updated(context, qos_filter, host)
        return qos_filter

    def delete_qos_filter(self, context, id):
        qos_filter = self.get_qos_filter(context, id)
        super(
            QosServerRpcServerMixin, self
        ).delete_qos_filter(context, id)
        if qos_filter['queue_id']:
            host = self._get_host_from_qos_id(context, qos_filter['qos_id'])
            self.notifier.qos_filter_deleted(context, id, host)


class QosRpcCallbacks(object):

    target = messaging.Target(version='1.0')

    def __init__(self, qos_plugin):
        self.qos_plugin = qos_plugin

    def sync_qos(self, context, **kwargs):
        qos_list = kwargs.get('qos_list')
        host = kwargs.get('host')
        return self.qos_plugin.sync_qos(context, qos_list, host)
