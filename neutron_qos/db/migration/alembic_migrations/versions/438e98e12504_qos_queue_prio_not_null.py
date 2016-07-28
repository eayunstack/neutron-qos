# Copyright (c) 2016 Eayun, Inc.
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
#

"""qos_queue_prio_not_null

Revision ID: 438e98e12504
Revises: qos_db_refine_ops
Create Date: 2016-07-14 15:54:04.632126

"""

# revision identifiers, used by Alembic.
revision = '438e98e12504'
down_revision = 'qos_db_refine_ops'

from alembic import op
import sqlalchemy as sa

from neutron.db import migration


def upgrade():
    queues = sa.sql.table('eayun_qosqueues', sa.sql.column('prio'))
    op.execute(queues.update().where(queues.c.prio==None).values(prio=0))
    migration.alter_column_if_exists(
        'eayun_qosqueues', 'prio',
        type_=sa.types.Integer,
        nullable=False)


def downgrade():
    pass
