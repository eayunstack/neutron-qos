cp -av ./neutron_qos/db/qos /usr/lib/python2.7/site-packages/neutron/db/
cp -v ./neutron_qos/db/migration/alembic_migrations/qos_init_ops.py /usr/lib/python2.7/site-packages/neutron/db/migration/alembic_migrations/
cp -av ./neutron_qos/services/qos /usr/lib/python2.7/site-packages/neutron/services/
cp -v ./neutron_qos/extensions/qos.py /usr/lib/python2.7/site-packages/neutron/extensions/
cp -v ./neutron_qos/api/rpc/agentnotifiers/qos_rpc_agent_api.py /usr/lib/python2.7/site-packages/neutron/api/rpc/agentnotifiers/
cp -v ./etc/neutron/rootwrap.d/qos.filters /usr/share/neutron/rootwrap/

