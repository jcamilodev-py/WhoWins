"""index users.reset_token

Revision ID: b1c4d7e29f30
Revises: aa21823eab1e
Create Date: 2026-09-06

El reseteo de contraseña busca por reset_token en cada intento. Sin índice esa
consulta es un seq scan sobre toda la tabla users.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b1c4d7e29f30'
down_revision: Union[str, Sequence[str], None] = 'aa21823eab1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(op.f('ix_users_reset_token'), 'users', ['reset_token'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_users_reset_token'), table_name='users')
