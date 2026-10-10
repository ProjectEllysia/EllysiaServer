"""company profile: los datos de la empresa de una cuenta

Una fila por dueño efectivo, con la identidad (razón social, NIF, dirección),
la descripción y el contacto de seguridad. Todo lo que cuelgue de la empresa
—cumplimiento normativo, píldoras de Aegis— lee de aquí.

Revision ID: d6f8a0b2c4e5
Revises: c5e7a9b1d3f4
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6f8a0b2c4e5'
down_revision: Union[str, Sequence[str], None] = 'c5e7a9b1d3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'CompanyProfile',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('User.id'), nullable=False, unique=True),
        sa.Column('legal_name', sa.String(length=255), nullable=True),
        sa.Column('tax_id', sa.String(length=32), nullable=True),
        sa.Column('address_line', sa.String(length=255), nullable=True),
        sa.Column('postal_code', sa.String(length=16), nullable=True),
        sa.Column('city', sa.String(length=128), nullable=True),
        sa.Column('province', sa.String(length=128), nullable=True),
        sa.Column('country', sa.String(length=2), nullable=True),
        sa.Column('sector', sa.String(length=128), nullable=True),
        sa.Column('company_size', sa.String(length=16), nullable=True),
        sa.Column('employee_count', sa.Integer(), nullable=True),
        sa.Column('jurisdiction', sa.String(length=128), nullable=True),
        sa.Column('work_model', sa.String(length=16), nullable=True),
        sa.Column('security_contact', sa.String(length=128), nullable=True),
        sa.Column('brand_logo', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('CompanyProfile')
