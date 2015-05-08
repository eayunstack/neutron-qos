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

import abc

import six

from neutron.api import extensions
from neutron.api.v2 import attributes as attr
from neutron.api.v2 import base
from neutron.api.v2 import resource_helper
from neutron.common import exceptions as nexception
from neutron import manager
from neutron.services import service_base

EAYUN_QOS = "/eayun_qos"


class QosInvalidPortType(nexception.InvalidInput):
    message = _("Cannot create qos under port %(port_id)s, its "
                "type %(port_type)s is not compute:nova")


class QosNotFound(nexception.NotFound):
    message = _("Qos %(id)s does not exists.")


class QosQueueNotFound(nexception.NotFound):
    message = _("Qos queue %(id)s does not exists.")


class QosFilterNotFound(nexception.NotFound):
    message = _("Qos filter %(id)s does not exists.")


class QosConflict(nexception.InvalidInput):
    message = _("A Qos of the same direction is already set with the target")


class QosRateTooSmall(nexception.NeutronException):
    message = _("Rate %(rate)s of qos %(id)s is too small to afford "
                "its queues.")


class QosQueueRateTooSmall(nexception.NeutronException):
    message = _("Rate %(rate)s of qos queue %(id)s is too small to afford "
                "its subqueues.")


class QosQueueNotInQos(nexception.NeutronException):
    message = _("Qos queue %(qos_queue_id)s is not in Qos %(qos_id)s.")


class QosQueueCannotEditDefault(nexception.InvalidInput):
    message = _("Qos queue %(qos_queue_id)s cannot be edited directly. "
                "It is the default queue of Qos %(qos_id)s.")


class QosParentQueueInUse(nexception.InUse):
    message = _("Cannot create subqueue under parent queue %(parent_id)s, "
                "it has filters attached.")


class QosQueueHasSub(nexception.InUse):
    message = _("Cannot create filter(s) under parent queue %(qos_queue_id)s, "
                "it has subqueues.")


class QosInvalidRateValue(nexception.InvalidInput):
    message = _("Invalid value for rate: %(rate)s. "
                "It must be 1 to 4294967295.")


class QosInvalidCeilValue(nexception.InvalidInput):
    message = _("Invalid value for ceil: %(ceil)s. "
                "It must be None or between 1 to 4294967295.")


class QosInvalidBurstValue(nexception.InvalidInput):
    message = _("Invalid value for burst: %(burst)s. "
                "It must be None or between 1 to 4294967295.")


class QosInvalidCburstValue(nexception.InvalidInput):
    message = _("Invalid value for cburst: %(cburst)s. "
                "It must be None or between 1 to 4294967295.")


class QosInvalidQueuePrioValue(nexception.InvalidInput):
    message = _("Invalid value for queue prio: %(prio)s. "
                "It must be None or between 0 to 7.")


class QosInvalidFilterPrioValue(nexception.InvalidInput):
    message = _("Invalid value for filter prio: %(prio)s. "
                "It must be None or between 0 to 4294967295.")


class QosInvalidProtocolValue(nexception.InvalidInput):
    message = _("Invalid value for protocol: %(protocol)s. "
                "It must be None or between 1 to 255.")


class QosInvalidPortValue(nexception.InvalidInput):
    message = _("Invalid value for port: %(port)s. "
                "It must be None or between 1 to 65535.")


def convert_to_tc_u32(value):
    """ Callers should at least catch ValueError and TypeError. """
    u32 = int(value)
    if not (u32 >= 0 and u32 <= 4294967295):
        raise ValueError

    return u32


def convert_to_tc_not_zero_u32(value):
    """ Callers should at least catch ValueError and TypeError. """
    u32 = convert_to_tc_u32(value)
    if not u32 > 0:
        raise ValueError

    return u32


def convert_to_tc_u32_or_none(value):
    """ Callers should at least catch ValueError and probably TypeError. """
    if value is None:
        ret = value
    else:
        ret = convert_to_tc_u32(value)

    return ret


def convert_to_tc_not_zero_u32_or_none(value):
    """ Callers should at least catch ValueError and probably TypeError. """
    if value is None:
        ret = value
    else:
        ret = convert_to_tc_not_zero_u32(value)

    return ret


def convert_to_rate(value):
    try:
        return convert_to_tc_not_zero_u32(value)
    except (ValueError, TypeError):
        raise QosInvalidRateValue(rate=value)


def convert_to_ceil(value):
    try:
        return convert_to_tc_not_zero_u32_or_none(value)
    except (ValueError, TypeError):
        raise QosInvalidCeilValue(ceil=value)


def convert_to_burst(value):
    try:
        return convert_to_tc_not_zero_u32_or_none(value)
    except (ValueError, TypeError):
        raise QosInvalidBurstValue(burst=value)


def convert_to_cburst(value):
    try:
        return convert_to_tc_not_zero_u32_or_none(value)
    except (ValueError, TypeError):
        raise QosInvalidCburstValue(cburst=value)


def convert_to_filter_prio(value):
    try:
        value = convert_to_tc_u32(value)
        if not value <= 65535:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise QosInvalidFilterPrioValue(prio=value)


def convert_to_queue_prio(value):
    try:
        value = convert_to_tc_u32_or_none(value)
        if not value <= 7:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise QosInvalidQueuePrioValue(prio=value)


def convert_to_protocol(value):
    if value is None:
        ret = value
    else:
        try:
            ret = int(value)
            if not (ret >= 1 and ret <= 255):
                raise ValueError
        except (ValueError, TypeError):
            raise QosInvalidProtocolValue(protocol=value)

    return ret


def convert_to_port(value):
    if value is None:
        ret = value
    else:
        try:
            ret = int(value)
            if not (ret >= 1 and ret <= 65535):
                raise ValueError
        except (ValueError, TypeError):
            raise QosInvalidPortValue(port=value)

    return ret


RESOURCE_ATTRIBUTE_MAP = {
    'qoss': {
        'id': {'allow_post': False, 'allow_put': False,
               'is_visible': True,
               'validate': {'type:uuid': None},
               'primary_key': True},
        'tenant_id': {'allow_post': True, 'allow_put': False,
                      'is_visible': True, 'required_by_policy': True,
                      'validate': {'type:string': None}},
        'name': {'allow_post': True, 'allow_put': True,
                 'is_visible': True, 'default': '',
                 'validate': {'type:string': None}},
        'description': {'allow_post': True, 'allow_put': True,
                        'is_visible': True, 'default': ''},
        'direction': {'allow_post': True, 'allow_put': False,
                      'is_visible': True,
                      'validate': {'type:values': ['ingress', 'egress']}},
        'target_type': {'allow_post': True, 'allow_put': True,
                        'is_visible': True, 'default': None,
                        'validate': {'type:values': [None, 'router', 'port']}},
        'target_id': {'allow_post': True, 'allow_put': True,
                      'is_visible': True, 'default': None,
                      'validate': {'type:uuid_or_none': None}},
        'rate': {'allow_post': True, 'allow_put': True,
                 'is_visible': True,
                 'convert_to': convert_to_rate},
        'burst': {'allow_post': True, 'allow_put': True,
                  'is_visible': True, 'default': None,
                  'convert_to': convert_to_burst},
        'cburst': {'allow_post': True, 'allow_put': True,
                   'is_visible': True, 'default': None,
                   'convert_to': convert_to_cburst},
        'default_rate': {'allow_post': True, 'allow_put': True,
                         'is_visible': True,
                         'convert_to': convert_to_rate},
        'default_burst': {'allow_post': True, 'allow_put': True,
                          'is_visible': True, 'default': None,
                          'convert_to': convert_to_burst},
        'default_cburst': {'allow_post': True, 'allow_put': True,
                           'is_visible': True, 'default': None,
                           'convert_to': convert_to_cburst},
        'default_queue_id': {'allow_post': False, 'allow_put': False,
                             'is_visible': True},
        'qos_queues': {'allow_post': False, 'allow_put': False,
                       'is_visible': True},
        'unattached_filters': {'allow_post': False, 'allow_put': False,
                               'is_visible': True},
    },
    'qos_queues': {
        'id': {'allow_post': False, 'allow_put': False,
               'is_visible': True,
               'validate': {'type:uuid': None},
               'primary_key': True},
        'tenant_id': {'allow_post': True, 'allow_put': False,
                      'is_visible': True, 'required_by_policy': True,
                      'validate': {'type:string': None}},
        'qos_id': {'allow_post': True, 'allow_put': False,
                   'is_visible': True, 'required_by_policy': True},
        'parent_id': {'allow_post': True, 'allow_put': False,
                      'is_visible': True, 'default': None,
                      'validate': {'type:uuid_or_none': None}},
        'prio': {'allow_post': True, 'allow_put': True,
                 'is_visible': True, 'default': None,
                 'convert_to': convert_to_queue_prio},
        'rate': {'allow_post': True, 'allow_put': True,
                 'is_visible': True,
                 'convert_to': convert_to_rate},
        'ceil': {'allow_post': True, 'allow_put': True,
                 'is_visible': True, 'default': None,
                 'convert_to': convert_to_ceil},
        'burst': {'allow_post': True, 'allow_put': True,
                  'is_visible': True, 'default': None,
                  'convert_to': convert_to_burst},
        'cburst': {'allow_post': True, 'allow_put': True,
                   'is_visible': True, 'default': None,
                   'convert_to': convert_to_cburst},
        'subqueues': {'allow_post': False, 'allow_put': False,
                      'is_visible': True},
        'attached_filters': {'allow_post': False, 'allow_put': False,
                             'is_visible': True},
    },
    'qos_filters': {
        'id': {'allow_post': False, 'allow_put': False,
               'is_visible': True,
               'validate': {'type:uuid': None},
               'primary_key': True},
        'tenant_id': {'allow_post': True, 'allow_put': False,
                      'is_visible': True, 'required_by_policy': True,
                      'validate': {'type:string': None}},
        'qos_id': {'allow_post': True, 'allow_put': False,
                   'is_visible': True, 'required_by_policy': True},
        'queue_id': {'allow_post': True, 'allow_put': True,
                     'is_visible': True, 'default': None,
                     'validate': {'type:uuid_or_none': None}},
        'prio': {'allow_post': True, 'allow_put': True,
                 'is_visible': True,
                 'convert_to': convert_to_filter_prio},
        'protocol': {'allow_post': True, 'allow_put': True,
                     'is_visible': True, 'default': None,
                     'convert_to': convert_to_protocol},
        'src_port': {'allow_post': True, 'allow_put': True,
                     'is_visible': True, 'default': None,
                     'convert_to': convert_to_port},
        'dst_port': {'allow_post': True, 'allow_put': True,
                     'is_visible': True, 'default': None,
                     'convert_to': convert_to_port},
        'src_addr': {'allow_post': True, 'allow_put': True,
                     'is_visible': True, 'default': None,
                     'validate': {'type:subnet_or_none': None}},
        'dst_addr': {'allow_post': True, 'allow_put': True,
                     'is_visible': True, 'default': None,
                     'validate': {'type:subnet_or_none': None}},
        'custom_match': {'allow_post': True, 'allow_put': True,
                         'is_visible': True, 'default': None,
                         'validate': {'type:string_or_none': None}},
        },
}


class Qos(extensions.ExtensionDescriptor):
    """ Qos extension. """
    @classmethod
    def get_name(cls):
        return "Eayun Neutron Qos"

    @classmethod
    def get_alias(cls):
        return "qos"

    @classmethod
    def get_description(cls):
        return "Eayun Neutron Qos extension."

    @classmethod
    def get_namespace(cls):
        return "https://github.com/eayunstack"

    @classmethod
    def get_updated(cls):
        return "2015-04-30T12:00:00-00:00"

    @classmethod
    def get_plugin_interface(cls):
        return QosPluginBase

    @classmethod
    def get_resources(cls):
        """Returns Ext Resources."""
        plural_mappings = resource_helper.build_plural_mappings(
            {}, RESOURCE_ATTRIBUTE_MAP)
        attr.PLURALS.update(plural_mappings)
        exts = []
        plugin = manager.NeutronManager.get_service_plugins()['qos']
        for resource_name in ['qos', 'qos_queue', 'qos_filter']:
            collection_name = resource_name.replace('_', '-') + "s"
            params = RESOURCE_ATTRIBUTE_MAP.get(resource_name + "s", dict())
            controller = base.create_resource(collection_name,
                                              resource_name,
                                              plugin, params, allow_bulk=True,
                                              allow_pagination=True,
                                              allow_sorting=True)

            ex = extensions.ResourceExtension(collection_name,
                                              controller,
                                              path_prefix=EAYUN_QOS,
                                              attr_map=params)
            exts.append(ex)

        return exts

    def update_attributes_map(self, attributes):
        super(Qos, self).update_attributes_map(
            attributes, extension_attrs_map=RESOURCE_ATTRIBUTE_MAP)

    def get_extended_resources(self, version):
        if version == "2.0":
            return RESOURCE_ATTRIBUTE_MAP
        else:
            return {}


@six.add_metaclass(abc.ABCMeta)
class QosPluginBase(service_base.ServicePluginBase):

    def get_plugin_name(self):
        return 'qos'

    def get_plugin_description(self):
        return 'qos'

    def get_plugin_type(self):
        return 'qos'

    @abc.abstractmethod
    def create_qos(self, context, qos):
        pass

    @abc.abstractmethod
    def update_qos(self, context, id, qos):
        pass

    @abc.abstractmethod
    def delete_qos(self, context, id):
        pass

    @abc.abstractmethod
    def get_qoss(self, context, filters=None, fields=None,
                 sorts=None, limit=None, marker=None,
                 page_reverse=False):
        pass

    @abc.abstractmethod
    def get_qos(self, context, id, fields=None):
        pass

    @abc.abstractmethod
    def create_qos_queue(self, context, qos_queue):
        pass

    @abc.abstractmethod
    def update_qos_queue(self, context, id, qos_queue):
        pass

    @abc.abstractmethod
    def delete_qos_queue(self, context, id):
        pass

    @abc.abstractmethod
    def get_qos_queues(self, context, filters=None, fields=None,
                       sorts=None, limit=None, marker=None,
                       page_reverse=False):
        pass

    @abc.abstractmethod
    def get_qos_queue(self, context, id, fields=None):
        pass

    @abc.abstractmethod
    def create_qos_filter(self, context, qos_filter):
        pass

    @abc.abstractmethod
    def update_qos_filter(self, context, id, qos_filter):
        pass

    @abc.abstractmethod
    def delete_qos_filter(self, context, id):
        pass

    @abc.abstractmethod
    def get_qos_filters(self, context, filters=None, fields=None,
                        sorts=None, limit=None, marker=None,
                        page_reverse=False):
        pass

    @abc.abstractmethod
    def get_qos_filter(self, context, id, fields=None):
        pass
