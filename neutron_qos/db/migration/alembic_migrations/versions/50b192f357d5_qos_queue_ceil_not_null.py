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

"""qos_queue_ceil_not_null

Revision ID: 50b192f357d5
Revises: 438e98e12504
Create Date: 2016-07-14 17:42:52.903363

"""

# revision identifiers, used by Alembic.
revision = '50b192f357d5'
down_revision = '438e98e12504'

from alembic import op
import sqlalchemy as sa

from neutron.db import migration


def upgrade():
    queues = sa.sql.table(
        'eayun_qosqueues', sa.sql.column('rate'), sa.sql.column('ceil'))
    op.execute(
        queues.update().where(queues.c.ceil==None).values(ceil=queues.c.rate))
    migration.alter_column_if_exists(
        'eayun_qosqueues', 'ceil',
        type_=sa.types.BigInteger,
        nullable=False)


def downgrade():
    pass
