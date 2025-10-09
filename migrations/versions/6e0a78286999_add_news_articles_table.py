"""add news_articles table

Revision ID: 6e0a78286999
Revises: dbdaed9f65ab
Create Date: 2025-08-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e0a78286999'
down_revision = 'dbdaed9f65ab'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'news_articles',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('url', sa.String(length=1024), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('image_url', sa.String(length=1024), nullable=True),
        sa.Column('added_by', sa.String(length=128), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_news_articles_added_at'), 'news_articles', ['added_at'], unique=False)
    op.create_index(op.f('ix_news_articles_added_by'), 'news_articles', ['added_by'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_news_articles_added_by'), table_name='news_articles')
    op.drop_index(op.f('ix_news_articles_added_at'), table_name='news_articles')
    op.drop_table('news_articles')
