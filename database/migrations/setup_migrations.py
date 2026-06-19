"""
Database Migration Setup
Run: alembic init database/migrations
     alembic revision --autogenerate -m "initial"
     alembic upgrade head
"""

# alembic.ini equivalent config (place in project root)
ALEMBIC_CONFIG = """
[alembic]
script_location = database/migrations
prepend_sys_path = .
sqlalchemy.url = sqlite:///./database/ea_bot.db

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""

# Initial migration content
INITIAL_MIGRATION = '''"""Initial schema

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'trades',
        sa.Column('id',          sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('ticket',      sa.Integer, unique=True, nullable=False),
        sa.Column('symbol',      sa.String(20), nullable=False),
        sa.Column('direction',   sa.String(10), nullable=False),
        sa.Column('open_time',   sa.DateTime, nullable=False),
        sa.Column('close_time',  sa.DateTime),
        sa.Column('open_price',  sa.Float, nullable=False),
        sa.Column('close_price', sa.Float),
        sa.Column('lots',        sa.Float, nullable=False),
        sa.Column('sl',          sa.Float),
        sa.Column('tp',          sa.Float),
        sa.Column('profit',      sa.Float, default=0.0),
        sa.Column('swap',        sa.Float, default=0.0),
        sa.Column('commission',  sa.Float, default=0.0),
        sa.Column('net_profit',  sa.Float, default=0.0),
        sa.Column('status',      sa.String(20), default='OPEN'),
        sa.Column('magic',       sa.Integer, default=0),
        sa.Column('comment',     sa.String(255), default=''),
        sa.Column('confidence',  sa.Float, default=0.0),
        sa.Column('regime',      sa.String(30), default=''),
        sa.Column('created_at',  sa.DateTime, default=datetime.utcnow),
        sa.Column('updated_at',  sa.DateTime, default=datetime.utcnow),
    )

    op.create_table(
        'signals',
        sa.Column('id',               sa.Integer, primary_key=True),
        sa.Column('symbol',           sa.String(20), nullable=False),
        sa.Column('direction',        sa.String(10), nullable=False),
        sa.Column('confidence',       sa.Float, nullable=False),
        sa.Column('trend_score',      sa.Float),
        sa.Column('momentum_score',   sa.Float),
        sa.Column('volume_score',     sa.Float),
        sa.Column('liquidity_score',  sa.Float),
        sa.Column('volatility_score', sa.Float),
        sa.Column('regime',           sa.String(30)),
        sa.Column('atr',              sa.Float),
        sa.Column('entry_price',      sa.Float),
        sa.Column('stop_loss',        sa.Float),
        sa.Column('take_profit',      sa.Float),
        sa.Column('risk_reward',      sa.Float),
        sa.Column('acted_on',         sa.Boolean, default=False),
        sa.Column('timestamp',        sa.DateTime, default=datetime.utcnow),
    )

    op.create_table(
        'account_snapshots',
        sa.Column('id',          sa.Integer, primary_key=True),
        sa.Column('balance',     sa.Float, nullable=False),
        sa.Column('equity',      sa.Float, nullable=False),
        sa.Column('margin_used', sa.Float, default=0.0),
        sa.Column('margin_free', sa.Float, default=0.0),
        sa.Column('open_pnl',   sa.Float, default=0.0),
        sa.Column('daily_pnl',  sa.Float, default=0.0),
        sa.Column('open_trades', sa.Integer, default=0),
        sa.Column('timestamp',  sa.DateTime, default=datetime.utcnow),
    )

    op.create_table(
        'news_events',
        sa.Column('id',         sa.Integer, primary_key=True),
        sa.Column('title',      sa.String(255), nullable=False),
        sa.Column('currency',   sa.String(10)),
        sa.Column('impact',     sa.String(20)),
        sa.Column('event_time', sa.DateTime, nullable=False),
        sa.Column('actual',     sa.String(50)),
        sa.Column('forecast',   sa.String(50)),
        sa.Column('previous',   sa.String(50)),
        sa.Column('source',     sa.String(50)),
        sa.Column('created_at', sa.DateTime, default=datetime.utcnow),
    )

    op.create_table(
        'system_logs',
        sa.Column('id',        sa.Integer, primary_key=True),
        sa.Column('level',     sa.String(10), nullable=False),
        sa.Column('module',    sa.String(50)),
        sa.Column('message',   sa.Text, nullable=False),
        sa.Column('timestamp', sa.DateTime, default=datetime.utcnow),
    )

    # Indexes
    op.create_index('ix_trades_symbol_open', 'trades', ['symbol', 'open_time'])
    op.create_index('ix_trades_magic', 'trades', ['magic'])
    op.create_index('ix_signals_symbol_time', 'signals', ['symbol', 'timestamp'])


def downgrade() -> None:
    op.drop_table('system_logs')
    op.drop_table('news_events')
    op.drop_table('account_snapshots')
    op.drop_table('signals')
    op.drop_table('trades')
'''

if __name__ == "__main__":
    import os

    os.makedirs("database/migrations/versions", exist_ok=True)

    # Write alembic.ini
    with open("alembic.ini", "w") as f:
        f.write(ALEMBIC_CONFIG)

    # Write initial migration
    with open("database/migrations/versions/001_initial.py", "w") as f:
        f.write(INITIAL_MIGRATION)

    print("Migration files created.")
    print("Run: alembic upgrade head")
