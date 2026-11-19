"""Initial persistent queues, settings, history, and favorites."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('groups', sa.Column('id', sa.BigInteger(), primary_key=True), sa.Column('loop', sa.Boolean(), nullable=False), sa.Column('volume', sa.Integer(), nullable=False))
    op.create_table('queue_tracks', sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True), sa.Column('chat_id', sa.BigInteger(), sa.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False), sa.Column('position', sa.Integer(), nullable=False), sa.Column('source_id', sa.String(64), nullable=False), sa.Column('title', sa.String(500), nullable=False), sa.Column('duration', sa.Integer()), sa.Column('thumbnail', sa.String(2048)), sa.Column('video', sa.Boolean(), nullable=False))
    op.create_index('ix_queue_tracks_chat_id', 'queue_tracks', ['chat_id'])
    op.create_index('ix_queue_chat_position', 'queue_tracks', ['chat_id', 'position'], unique=True)
    op.create_table('playback_history', sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True), sa.Column('chat_id', sa.BigInteger(), sa.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False), sa.Column('source_id', sa.String(64), nullable=False), sa.Column('title', sa.String(500), nullable=False))
    op.create_index('ix_playback_history_chat_id', 'playback_history', ['chat_id'])
    op.create_table('favorites', sa.Column('user_id', sa.BigInteger(), primary_key=True), sa.Column('source_id', sa.String(64), primary_key=True), sa.Column('title', sa.String(500), nullable=False))


def downgrade():
    op.drop_table('favorites')
    op.drop_table('playback_history')
    op.drop_table('queue_tracks')
    op.drop_table('groups')
