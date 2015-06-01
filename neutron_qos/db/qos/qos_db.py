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

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.orm import exc

from neutron.db import model_base
from neutron.db import models_v2
from neutron.db import common_db_mixin as base_db
from neutron.db import l3_db
from neutron.extensions import qos as ext_qos
from neutron.openstack.common import uuidutils
from neutron.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class Qos(model_base.BASEV2, models_v2.HasId, models_v2.HasTenant):
    __tablename__ = 'eayun_qoss'

    name = sa.Column(sa.String(255))
    description = sa.Column(sa.String(255))
    direction = sa.Column(sa.Enum('ingress', 'egress', name='qoss_direction'),
                          nullable=False)
    port_id = sa.Column(sa.String(36), sa.ForeignKey('ports.id'))
    router_id = sa.Column(sa.String(36), sa.ForeignKey('routers.id'))
    rate = sa.Column(sa.BigInteger, nullable=False)
    burst = sa.Column(sa.BigInteger)
    cburst = sa.Column(sa.BigInteger)
    default_queue_id = sa.Column(sa.String(36),
                                 sa.ForeignKey('eayun_qosqueues.id'))
    port = orm.relationship(
        models_v2.Port,
        backref=orm.backref(
            'eayun_qoss', cascade='all,delete', lazy='joined', uselist=True),
        primaryjoin='Port.id==Qos.port_id')
    router = orm.relationship(
        l3_db.Router,
        backref=orm.backref(
            'eayun_qoss', cascade='all,delete', lazy='joined', uselist=True),
        primaryjoin='Router.id==Qos.router_id')
    default_queue = orm.relationship(
        "QosQueue",
        primaryjoin='QosQueue.id==Qos.default_queue_id', post_update=True)


class QosQueue(model_base.BASEV2, models_v2.HasId, models_v2.HasTenant):
    __tablename__ = 'eayun_qosqueues'

    qos_id = sa.Column(sa.String(36),
                       sa.ForeignKey('eayun_qoss.id'),
                       nullable=False)
    parent_id = sa.Column(sa.String(36),
                          sa.ForeignKey('eayun_qosqueues.id'))
    prio = sa.Column(sa.Integer)
    rate = sa.Column(sa.BigInteger, nullable=False)
    ceil = sa.Column(sa.BigInteger)
    burst = sa.Column(sa.BigInteger)
    cburst = sa.Column(sa.BigInteger)
    qos = orm.relationship(
        Qos,
        backref=orm.backref(
            'queues', cascade='all,delete', lazy='joined', uselist=True),
        primaryjoin='Qos.id==QosQueue.qos_id')
    parent_queue = orm.relationship(
        "QosQueue",
        remote_side='QosQueue.id',
        backref=orm.backref(
            'subqueues', cascade='all,delete', lazy='joined', uselist=True),
        primaryjoin='QosQueue.id==QosQueue.parent_id')


class QosFilter(model_base.BASEV2, models_v2.HasId, models_v2.HasTenant):
    __tablename__ = 'eayun_qosfilters'

    qos_id = sa.Column(sa.String(36),
                       sa.ForeignKey('eayun_qoss.id', ondelete='CASCADE'),
                       nullable=False)
    queue_id = sa.Column(sa.String(36),
                         sa.ForeignKey('eayun_qosqueues.id'))
    prio = sa.Column(sa.Integer, nullable=False, unique=True)
    protocol = sa.Column(sa.Integer)
    src_port = sa.Column(sa.Integer)
    dst_port = sa.Column(sa.Integer)
    src_addr = sa.Column(sa.String(255))
    dst_addr = sa.Column(sa.String(255))
    custom_match = sa.Column(sa.String(255))
    qos = orm.relationship(
        Qos,
        backref=orm.backref(
            'filters', cascade='all,delete', lazy='joined', uselist=True),
        primaryjoin='Qos.id==QosFilter.qos_id')
    queue = orm.relationship(
        QosQueue,
        backref=orm.backref(
            'attached_filters', cascade='all,delete', lazy='joined',
            uselist=True),
        primaryjoin='QosQueue.id==QosFilter.queue_id')


class QosDbMixin(ext_qos.QosPluginBase, base_db.CommonDbMixin):
    """ Mixin class to add security group to db_base_plugin_v2. """

    __native_bulk_support = True

    def _get_qos(self, context, id):
        try:
            query = self._model_query(context, Qos)
            qos = query.filter(Qos.id == id).one()
        except exc.NoResultFound:
            raise ext_qos.QosNotFound(id=id)
        return qos

    def _get_qos_siblings(self, context, router_id, port_id):
        if router_id:
            return self._model_query(
                context, Qos).filter(Qos.router_id == router_id).all()
        elif port_id:
            return self._model_query(
                context, Qos).filter(Qos.port_id == port_id).all()
        else:
            return []

    def _parse_qos_input(self, qos_input):
        qos = qos_input['qos']
        queue = dict()

        if 'rate' in qos:
            queue['ceil'] = qos.get('rate')

        if 'default_rate' in qos:
            queue['rate'] = qos.pop('default_rate')

        if 'default_burst' in qos:
            queue['burst'] = qos.pop('default_burst')

        if 'default_cburst' in qos:
            queue['cburst'] = qos.pop('default_cburst')

        if 'target_type' not in qos and 'target_id' not in qos:
            pass
        else:
            target_type = qos.pop('target_type')
            target_id = qos.pop('target_id')

            qos['port_id'] = qos['router_id'] = None
            if (target_type is not None and target_id is not None):
                if target_type == 'router':
                    qos['router_id'] = target_id
                elif target_type == 'port':
                    qos['port_id'] = target_id

        return qos, queue

    def _make_qos_dict(self, qos, fields=None):
        res = {'id': qos.id,
               'tenant_id': qos.tenant_id,
               'name': qos.name,
               'description': qos.description,
               'direction': qos.direction,
               'rate': qos.rate,
               'burst': qos.burst,
               'cburst': qos.cburst,
               'default_queue_id': qos.default_queue_id}

        if qos.port_id is not None:
            res.update({'target_type': 'port',
                        'target_id': qos.port_id})
        elif qos.router_id is not None:
            res.update({'target_type': 'router',
                        'target_id': qos.router_id})
        else:
            res.update({'target_type': None, 'target_id': None})

        res['qos_queues'] = [
            self._make_qos_queue_dict(q) for q in
            filter(lambda q: q.parent_queue is None, qos.queues)
        ]

        res['unattached_filters'] = [
            self._make_qos_filter_dict(f) for f in
            filter(lambda f: f.queue is None, qos.filters)
        ]

        return self._fields(res, fields)

    def _aggregate_rate_of_qos(self, qos):
        return reduce(lambda x, y: x + y, [q.rate for q in qos.queues])

    def _check_qos_rate(self, qos, delta, maximum=None):
        if maximum is None:
            if delta <= 0:
                return
            else:
                maximum = qos.rate
        if self._aggregate_rate_of_qos(qos) + delta > maximum:
            raise ext_qos.QosRateTooSmall(id=qos.id, rate=maximum)

    def create_qos_bulk(self, context, qos):
        return self._create_bulk('qos', context, qos)

    def create_qos(self, context, qos):
        """ Create a qos and its default queue. """
        qos, queue = self._parse_qos_input(qos)
        tenant_id = self._get_tenant_id_for_create(context, qos)

        qos_id = qos.get('id') or uuidutils.generate_uuid()
        default_queue_id = uuidutils.generate_uuid()

        if qos['rate'] < queue['rate']:
            raise ext_qos.QosRateTooSmall(id=qos_id, rate=qos['rate'])

        if qos['router_id']:
            self._check_router(context, qos['router_id'])
        elif qos['port_id']:
            self._check_port(context, qos['port_id'])

        siblings = self._get_qos_siblings(
            context,
            qos['router_id'],
            qos['port_id'])
        if len(siblings) > 1:
            raise ext_qos.QosConflict()
        elif len(siblings) > 0:
            if siblings[0].direction == qos['direction']:
                raise ext_qos.QosConflict()

        with context.session.begin(subtransactions=True):
            qos_db = Qos(
                id=qos_id, tenant_id=tenant_id,
                name=qos['name'], description=qos['description'],
                direction=qos['direction'],
                port_id=qos['port_id'], router_id=qos['router_id'],
                rate=qos['rate'], burst=qos['burst'], cburst=qos['cburst'],
                default_queue_id=default_queue_id)
            qos_queue_db = QosQueue(
                id=default_queue_id, tenant_id=tenant_id,
                qos_id=qos_id, parent_id=None, prio=7,
                rate=queue['rate'], ceil=queue['ceil'],
                burst=queue['burst'], cburst=queue['cburst'])
            context.session.add(qos_db)
            context.session.add(qos_queue_db)

        return self._make_qos_dict(qos_db)

    def update_qos(self, context, id, qos):
        qos, queue = self._parse_qos_input(qos)

        router_id = qos.get('router_id', None)
        port_id = qos.get('port_id', None)
        if router_id:
            self._check_router(context, router_id)
        elif port_id:
            self._check_port(context, port_id)

        with context.session.begin(subtransactions=True):
            qos_db = self._get_qos(context, id)
            qos_queue_db = self._get_qos_queue(context,
                                               qos_db.default_queue_id)

            new_rate = qos.get('rate', qos_db.rate)
            new_queue_rate = queue.get('rate', qos_queue_db.rate)
            rate_delta = new_queue_rate - qos_queue_db.rate
            self._check_qos_rate(qos_db, rate_delta, new_rate)

            siblings = self._get_qos_siblings(context, router_id, port_id)
            # In case original target_id was specified when update
            siblings = filter(lambda s: s.id != qos_db.id, siblings)
            if len(siblings) > 1:
                raise ext_qos.QosConflict()
            elif len(siblings) > 0:
                if siblings[0].direction == qos_db.direction:
                    raise ext_qos.QosConflict()

            qos_db.update(qos)
            if queue:
                qos_queue_db.update(queue)

        return self._make_qos_dict(qos_db)

    def delete_qos(self, context, id):
        qos = self._get_qos(context, id)
        with context.session.begin(subtransactions=True):
            context.session.delete(qos)

    def get_qoss(self, context, filters=None, fields=None,
                 sorts=None, limit=None, marker=None,
                 page_reverse=False):
        marker_obj = self._get_marker_obj(context, 'qos', limit, marker)
        return self._get_collection(
            context, Qos, self._make_qos_dict,
            filters=filters, fields=fields, sorts=sorts,
            limit=limit, marker_obj=marker_obj, page_reverse=page_reverse)

    def get_qoss_count(self, context, filters=None):
        return self._get_collection_count(context, Qos, filters=filters)

    def get_qos(self, context, id, fields=None, tenant_id=None):
        if tenant_id:
            tmp_tenant_id = context.tenant_id
            context.tenant_id = tenant_id

        try:
            with context.session.begin(subtransactions=True):
                ret = self._make_qos_dict(self._get_qos(context, id), fields)
        finally:
            if tenant_id:
                context.tenant_id = tmp_tenant_id
        return ret

    def _get_qos_queue(self, context, id):
        try:
            query = self._model_query(context, QosQueue)
            qos_queue = query.filter(QosQueue.id == id).one()
        except exc.NoResultFound:
            raise ext_qos.QosQueueNotFound(id=id)
        return qos_queue

    def _make_qos_queue_dict(self, qos_queue, fields=None):
        res = {'id': qos_queue.id,
               'tenant_id': qos_queue.tenant_id,
               'qos_id': qos_queue.qos_id,
               'parent_id': qos_queue.parent_id,
               'prio': qos_queue.prio,
               'rate': qos_queue.rate,
               'ceil': qos_queue.ceil,
               'burst': qos_queue.burst,
               'cburst': qos_queue.cburst}

        res['subqueues'] = [self._make_qos_queue_dict(q)
                            for q in qos_queue.subqueues]
        res['attached_filters'] = [self._make_qos_filter_dict(f)
                                   for f in qos_queue.attached_filters]

        return self._fields(res, fields)

    def _aggregate_rate_of_qos_queue(self, qos_queue):
        if qos_queue.subqueues:
            return reduce(
                lambda x, y: x + y, [q.rate for q in qos_queue.subqueues])
        else:
            return 0

    def _check_qos_queue_rate(self, qos_queue, delta, maximum=None):
        if maximum is None:
            if delta <= 0:
                return
            else:
                maximum = qos_queue.rate
        if self._aggregate_rate_of_qos_queue(qos_queue) + delta > maximum:
            raise ext_qos.QosQueueRateTooSmall(id=qos_queue.id, rate=maximum)

    def _check_queue_in_qos(self, qos_id, qos_queue):
        if qos_id != qos_queue.qos_id:
            raise ext_qos.QosQueueNotInQos(
                qos_id=qos_id,
                qos_queue_id=qos_queue.qos_id
            )

    def create_qos_queue_bulk(self, context, qos_queue):
        return self._create_bulk('qos_queue', context, qos_queue)

    def create_qos_queue(self, context, qos_queue):
        qos_queue = qos_queue['qos_queue']

        qos_db = self._get_qos(context, qos_queue['qos_id'])
        self._check_qos_rate(qos_db, qos_queue['rate'])
        if qos_queue['parent_id'] is not None:
            parent_queue_db = self._get_qos_queue(context,
                                                  qos_queue['parent_id'])
            if parent_queue_db.attached_filters:
                raise ext_qos.QosParentQueueInUse(parent_id=parent_queue_db.id)
            self._check_queue_in_qos(qos_db.id, parent_queue_db)
            self._check_qos_queue_rate(parent_queue_db, qos_queue['rate'])
        tenant_id = self._get_tenant_id_for_create(context, qos_queue)
        qos_queue_id = qos_queue.get('id') or uuidutils.generate_uuid()
        with context.session.begin(subtransactions=True):
            qos_queue_db = QosQueue(
                id=qos_queue_id, tenant_id=tenant_id,
                qos_id=qos_queue['qos_id'], parent_id=qos_queue['parent_id'],
                prio=qos_queue['prio'],
                rate=qos_queue['rate'], ceil=qos_queue['ceil'],
                burst=qos_queue['burst'], cburst=qos_queue['cburst'])
            context.session.add(qos_queue_db)

        return self._make_qos_queue_dict(qos_queue_db)

    def update_qos_queue(self, context, id, qos_queue):
        qos_queue = qos_queue['qos_queue']

        with context.session.begin(subtransactions=True):
            qos_queue_db = self._get_qos_queue(context, id)
            if id == qos_queue_db.qos.default_queue_id:
                raise ext_qos.QosQueueCannotEditDefault(
                    qos_id=qos_queue_db.qos_id,
                    qos_queue_id=id)
            new_rate = qos_queue.get('rate', qos_queue_db.rate)
            rate_delta = new_rate - qos_queue_db.rate
            self._check_qos_rate(qos_queue_db.qos, rate_delta)
            if qos_queue_db.parent_queue:
                self._check_qos_queue_rate(qos_queue_db.parent_queue,
                                           rate_delta)
            if qos_queue_db.subqueues:
                new_rate = qos_queue.get('rate', qos_queue_db.rate)
                self._check_qos_queue_rate(qos_queue_db, 0, new_rate)
            qos_queue_db.update(qos_queue)
        return self._make_qos_queue_dict(qos_queue_db)

    def delete_qos_queue(self, context, id):
        qos_queue = self._get_qos_queue(context, id)
        if id == qos_queue.qos.default_queue_id:
            raise ext_qos.QosQueueCannotEditDefault(
                qos_id=qos_queue.qos_id,
                qos_queue_id=id)
        with context.session.begin(subtransactions=True):
            context.session.delete(qos_queue)

    def get_qos_queues(self, context, filters=None, fields=None,
                       sorts=None, limit=None, marker=None,
                       page_reverse=False):
        marker_obj = self._get_marker_obj(context, 'qos_queue', limit, marker)
        return self._get_collection(
            context, QosQueue, self._make_qos_queue_dict,
            filters=filters, fields=fields, sorts=sorts,
            limit=limit, marker_obj=marker_obj, page_reverse=page_reverse)

    def get_qos_queues_count(self, context, filters=None):
        return self._get_collection_count(context, QosQueue, filters=filters)

    def get_qos_queue(self, context, id, fields=None):
        qos_queue = self._get_qos_queue(context, id)
        return self._make_qos_queue_dict(qos_queue, fields)

    def _get_qos_filter(self, context, id):
        try:
            query = self._model_query(context, QosFilter)
            qos_filter = query.filter(QosFilter.id == id).one()
        except exc.NoResultFound:
            raise ext_qos.QosFilterNotFound(id=id)
        return qos_filter

    def _make_qos_filter_dict(self, qos_filter, fields=None):
        res = {'id': qos_filter.id,
               'tenant_id': qos_filter.tenant_id,
               'qos_id': qos_filter.qos_id,
               'queue_id': qos_filter.queue_id,
               'prio': qos_filter.prio,
               'protocol': qos_filter.protocol,
               'src_port': qos_filter.src_port,
               'dst_port': qos_filter.dst_port,
               'src_addr': qos_filter.src_addr,
               'dst_addr': qos_filter.dst_addr}

        if qos_filter.custom_match is not None:
            res.update({'custom_match': qos_filter.custom_match})

        return self._fields(res, fields)

    def create_qos_filter_bulk(self, context, qos_filter):
        return self._create_bulk('qos_filter', context, qos_filter)

    def create_qos_filter(self, context, qos_filter):
        qos_filter = qos_filter['qos_filter']

        qos_db = self._get_qos(context, qos_filter['qos_id'])
        if qos_filter['queue_id'] is not None:
            qos_queue_db = self._get_qos_queue(context, qos_filter['queue_id'])
            self._check_queue_in_qos(qos_db.id, qos_queue_db)
            if qos_queue_db.subqueues:
                raise ext_qos.QosQueueHasSub(qos_queue_id=qos_queue_db.id)
        tenant_id = self._get_tenant_id_for_create(context, qos_filter)
        qos_filter_id = qos_filter.get('id') or uuidutils.generate_uuid()
        with context.session.begin(subtransactions=True):
            qos_filter_db = QosFilter(
                id=qos_filter_id, tenant_id=tenant_id,
                qos_id=qos_filter['qos_id'], queue_id=qos_filter['queue_id'],
                prio=qos_filter['prio'],
                protocol=qos_filter['protocol'],
                src_port=qos_filter['src_port'],
                dst_port=qos_filter['dst_port'],
                src_addr=qos_filter['src_addr'],
                dst_addr=qos_filter['dst_addr'],
                custom_match=qos_filter['custom_match'])
            context.session.add(qos_filter_db)

        return self._make_qos_filter_dict(qos_filter_db)

    def update_qos_filter(self, context, id, qos_filter):
        qos_filter = qos_filter['qos_filter']

        with context.session.begin(subtransactions=True):
            qos_filter_db = self._get_qos_filter(context, id)
            if qos_filter.get('queue_id', None) is not None:
                qos_queue_db = self._get_qos_queue(context,
                                                   qos_filter['queue_id'])
                self._check_queue_in_qos(qos_filter_db.qos_id, qos_queue_db)
                if qos_queue_db.subqueues:
                    raise ext_qos.QosQueueHasSub(qos_queue_id=qos_queue_db.id)
            qos_filter_db.update(qos_filter)
        return self._make_qos_filter_dict(qos_filter_db)

    def delete_qos_filter(self,  context, id):
        qos_filter = self._get_qos_filter(context, id)
        with context.session.begin(subtransactions=True):
            context.session.delete(qos_filter)

    def get_qos_filters(self, context, filters=None, fields=None,
                        sorts=None, limit=None, marker=None,
                        page_reverse=False):
        marker_obj = self._get_marker_obj(context, 'qos_filter', limit, marker)
        return self._get_collection(
            context, QosFilter, self._make_qos_filter_dict,
            filters=filters, fields=fields, sorts=sorts,
            limit=limit, marker_obj=marker_obj, page_reverse=page_reverse)

    def get_qos_filters_count(self, context, filters=None):
        return self._get_collection_count(context, QosFilter, filters=filters)

    def get_qos_filter(self, context, id, fields=None):
        qos_filter = self._get_qos_filter(context, id)
        return self._make_qos_filter_dict(qos_filter, fields)
