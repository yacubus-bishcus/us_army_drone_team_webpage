"""store whitepaper pdf data in db

Revision ID: b8a52a894715
Revises: 4d1f3e6e4f2a
Create Date: 2024-08-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from pathlib import Path
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'b8a52a894715'
down_revision = '4d1f3e6e4f2a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('white_papers', sa.Column('data', sa.LargeBinary(), nullable=True))

    bind = op.get_bind()
    result = bind.execute(text("SELECT id, filename FROM white_papers"))
    rows = result.mappings().all()

    if rows:
        upload_dir = Path(__file__).resolve().parents[2] / 'instance' / 'uploads' / 'whitepapers'
        for row in rows:
            data = b''
            filename = (row.get('filename') or '').strip()
            if filename:
                candidate = upload_dir / filename
                try:
                    data = candidate.read_bytes()
                except FileNotFoundError:
                    data = b''
            bind.execute(
                text("UPDATE white_papers SET data = :data WHERE id = :id"),
                {"data": data, "id": row['id']},
            )

    op.alter_column('white_papers', 'data', existing_type=sa.LargeBinary(), nullable=False)


def downgrade() -> None:
    op.drop_column('white_papers', 'data')
