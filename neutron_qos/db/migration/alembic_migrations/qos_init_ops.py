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

from alembic import op
import sqlalchemy as sa


directions = sa.Enum('ingress', 'egress', name='qoss_direction')


def upgrade():
    op.create_table(
        'eayun_qoss',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('direction', directions, nullable=False),
        sa.Column('port_id', sa.String(length=36), nullable=True),
        sa.Column('router_id', sa.String(length=36), nullable=True),
        sa.Column('rate', sa.BigInteger(), nullable=False),
        sa.Column('burst', sa.BigInteger(), nullable=True),
        sa.Column('cburst', sa.BigInteger(), nullable=True),
        sa.Column('default_queue_id', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['port_id'], ['ports.id']),
        sa.ForeignKeyConstraint(['router_id'], ['routers.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'eayun_qosqueues',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=True),
        sa.Column('qos_id', sa.String(length=36), nullable=False),
        sa.Column('parent_id', sa.String(length=36), nullable=True),
        sa.Column('prio', sa.Integer(), nullable=True),
        sa.Column('rate', sa.BigInteger(), nullable=False),
        sa.Column('ceil', sa.BigInteger(), nullable=True),
        sa.Column('burst', sa.BigInteger(), nullable=True),
        sa.Column('cburst', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['qos_id'], ['eayun_qoss.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'eayun_qosfilters',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=True),
        sa.Column('qos_id', sa.String(length=36), nullable=False),
        sa.Column('queue_id', sa.String(length=36), nullable=True),
        sa.Column('prio', sa.Integer(), nullable=False),
        sa.Column('protocol', sa.Integer(), nullable=True),
        sa.Column('src_port', sa.Integer(), nullable=True),
        sa.Column('dst_port', sa.Integer(), nullable=True),
        sa.Column('src_addr', sa.String(length=255), nullable=True),
        sa.Column('dst_addr', sa.String(length=255), nullable=True),
        sa.Column('custom_match', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['qos_id'], ['eayun_qoss.id']),
        sa.ForeignKeyConstraint(['queue_id'], ['eayun_qosqueues.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('eayun_qosfilters')
    op.drop_table('eayun_qosqueues')
    op.drop_table('eayun_qoss')
