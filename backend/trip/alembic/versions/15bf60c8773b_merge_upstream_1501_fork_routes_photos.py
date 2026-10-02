"""merge upstream 1.50.1 chain and fork routes/photos chain

Revision ID: 15bf60c8773b
Revises: 204ff7948b78, e7a2c9104bd8
Create Date: 2026-10-02 15:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "15bf60c8773b"
down_revision = ("204ff7948b78", "e7a2c9104bd8")
branch_labels = None
depends_on = None


def upgrade():
    # The two parent chains touch disjoint tables; this revision only joins them.
    pass


def downgrade():
    pass
