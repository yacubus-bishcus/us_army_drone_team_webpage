"""add open_count to news articles"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '4d1f3e6e4f2a'
down_revision = '6e0a78286999'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('news_articles') as batch_op:
        batch_op.add_column(sa.Column('open_count', sa.Integer(), nullable=False, server_default='0'))
    op.execute("UPDATE news_articles SET open_count = 0 WHERE open_count IS NULL")
    with op.batch_alter_table('news_articles') as batch_op:
        batch_op.alter_column('open_count', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('news_articles') as batch_op:
        batch_op.drop_column('open_count')
