# Copyright 2016 OpenStack Foundation
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
#

"""qos_queue_tc_class

Revision ID: 5108f17d7012
Revises: 2a853fe8a8b1
Create Date: 2016-07-20 15:23:09.216804

"""

# revision identifiers, used by Alembic.
revision = '5108f17d7012'
down_revision = '2a853fe8a8b1'

from alembic import op
import sqlalchemy as sa



def upgrade():
    op.create_table(
        'eayun_qostcclassranges',
        sa.Column('qos_id', sa.String(length=36), nullable=False),
        sa.Column('first', sa.Integer(), nullable=False),
        sa.Column('last', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('qos_id')
    )
    op.create_foreign_key(
        'fk-eayun_qostcclassranges-qos_id-eayun_qoss',
        'eayun_qostcclassranges', 'eayun_qoss',
        ['qos_id'], ['id'],
        ondelete='CASCADE'
    )
    op.add_column(
        'eayun_qosqueues', sa.Column('tc_class', sa.Integer(), nullable=True)
    )
    qos_queues = sa.sql.table('eayun_qosqueues', sa.sql.column('tc_class'))
    op.execute(qos_queues.update().values(tc_class=None))


def downgrade():
    op.drop_table('eayun_qostcclassranges')
    op.drop_column('eayun_qosqueues', 'tc_class')
