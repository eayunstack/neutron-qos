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

"""qos_filter_addr_not_null

Revision ID: 2a853fe8a8b1
Revises: 50b192f357d5
Create Date: 2016-07-14 19:14:22.811223

"""

# revision identifiers, used by Alembic.
revision = '2a853fe8a8b1'
down_revision = '50b192f357d5'

from alembic import op
import sqlalchemy as sa

from neutron.db import migration


def upgrade():
    tc_filters = sa.sql.table(
        'eayun_qosfilters',
        sa.sql.column('src_addr'), sa.sql.column('dst_addr'))
    op.execute(
        tc_filters.update().where(tc_filters.c.src_addr==None).values(
            src_addr='0.0.0.0/0'))
    migration.alter_column_if_exists(
        'eayun_qosfilters', 'src_addr',
        type_=sa.types.String(255),
        nullable=False)
    op.execute(
        tc_filters.update().where(tc_filters.c.dst_addr==None).values(
            dst_addr='0.0.0.0/0'))
    migration.alter_column_if_exists(
        'eayun_qosfilters', 'dst_addr',
        type_=sa.types.String(255),
        nullable=False)


def downgrade():
    pass
