"""admin configuration tables -- the database becomes the source of truth

The admin console (design: ``admin-console.md`` sections 3 and 4) makes the
database the authority for models, task material, majors/classes/units and the
curriculum map wherever ``IDA_CONFIG_SOURCE=db``.  This revision creates the
tables for that -- and ONLY the tables.

⚠ SEEDING IS NOT A MIGRATION (AD-7).  The migrate initContainer gets only
``DATABASE_URL``; it cannot see the per-environment file overrides
(``IDA_MODELS_FILE``, ``IDA_TASKS_DIR``, ``IDA_MAJORS_FILE`` ...) that decide
WHICH YAML an environment uses, so a seed written here would seed prod's
content into dev or the reverse.  ``ida_core.configdb.seed.ensure_seeded``
runs at api/runner/sweep start instead, under an advisory lock, and only when
``config_revisions`` is empty.  Until ``IDA_CONFIG_SOURCE=db`` is set these
tables stay empty and nothing reads them, so this migration is inert in every
environment it lands in.

Both unit invariants are constraints, not just code (see
``ida_core.configdb.tables.UnitFamilyRow``): ``UNIQUE(unit_families.family_key)``
and the composite FK onto ``class_task_families``.

Portable types for the reason every revision here uses them: one migration has
to run against both the CI SQLite suite and CloudNativePG.

Revision ID: ida_0006_admin_config_tables
Revises: ida_0005_judge_attempts
Create Date: 2026-11-17 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ida_0006_admin_config_tables"
down_revision: Union[str, None] = "ida_0005_judge_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Parents before children: the FKs below need their targets to exist.
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor_login', sa.String(length=64), nullable=False),
    sa.Column('actor_sub', sa.String(length=255), nullable=True),
    sa.Column('via_subject', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=32), nullable=False),
    sa.Column('entity_id', sa.String(length=255), nullable=False),
    sa.Column('before', sa.JSON(), nullable=True),
    sa.Column('after', sa.JSON(), nullable=True),
    sa.Column('config_revision', sa.BigInteger(), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_log_at'), 'audit_log', ['at'], unique=False)
    op.create_index('ix_audit_log_entity', 'audit_log', ['entity_type', 'entity_id', 'at'], unique=False)
    op.create_table('config_revisions',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('seed_git_sha', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('curriculum_documents',
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('document', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('majors',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('department', sa.String(length=255), nullable=False),
    sa.Column('subject_codes', sa.JSON(), nullable=False),
    sa.Column('display_code', sa.String(length=32), nullable=True),
    sa.Column('catalog', sa.Text(), nullable=True),
    sa.Column('class_source', sa.String(length=32), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('model_families',
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('provider_credentials',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('nonce', sa.LargeBinary(length=12), nullable=False),
    sa.Column('kek_id', sa.String(length=16), nullable=False),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('task_families',
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('provenance', sa.String(length=16), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('task_revisions',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('task_id', sa.String(length=255), nullable=False),
    sa.Column('content_sha', sa.String(length=64), nullable=False),
    sa.Column('document', sa.JSON(), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('config_revision', sa.BigInteger(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_task_revisions_content_sha'), 'task_revisions', ['content_sha'], unique=False)
    op.create_index(op.f('ix_task_revisions_task_id'), 'task_revisions', ['task_id'], unique=False)
    op.create_table('classes',
    sa.Column('course', sa.String(length=32), nullable=False),
    sa.Column('major_id', sa.String(length=64), nullable=True),
    sa.Column('unassigned_reason', sa.Text(), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('credit_hours', sa.Float(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.CheckConstraint('(major_id IS NULL) <> (unassigned_reason IS NULL)', name='ck_classes_one_owner'),
    sa.ForeignKeyConstraint(['major_id'], ['majors.id'], ),
    sa.PrimaryKeyConstraint('course')
    )
    op.create_table('models',
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('family_key', sa.String(length=128), nullable=True),
    sa.Column('display_order', sa.Integer(), nullable=True),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('base_url', sa.Text(), nullable=True),
    sa.Column('base_url_env', sa.String(length=128), nullable=True),
    sa.Column('api_key_env', sa.String(length=128), nullable=True),
    sa.Column('credential_ref', sa.String(length=128), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('hidden', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('timeout_s', sa.Float(), nullable=False),
    sa.Column('max_retries', sa.Integer(), nullable=False),
    sa.Column('tags', sa.JSON(), nullable=False),
    sa.Column('serving', sa.JSON(), nullable=False),
    sa.Column('cost_input_usd_per_mtok', sa.Numeric(precision=12, scale=4, asdecimal=False), nullable=False),
    sa.Column('cost_output_usd_per_mtok', sa.Numeric(precision=12, scale=4, asdecimal=False), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.CheckConstraint('NOT (api_key_env IS NOT NULL AND credential_ref IS NOT NULL)', name='ck_models_one_key_source'),
    sa.ForeignKeyConstraint(['credential_ref'], ['provider_credentials.name'], ),
    sa.ForeignKeyConstraint(['family_key'], ['model_families.key'], ),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('tasks',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('family_key', sa.String(length=128), nullable=False),
    sa.Column('document', sa.JSON(), nullable=False),
    sa.Column('content_sha', sa.String(length=64), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('sample_count', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('upload_object_key', sa.Text(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.CheckConstraint("id LIKE family_key || '/%'", name='ck_tasks_id_in_family'),
    sa.ForeignKeyConstraint(['family_key'], ['task_families.key'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_family_key'), 'tasks', ['family_key'], unique=False)
    op.create_table('class_task_families',
    sa.Column('course', sa.String(length=32), nullable=False),
    sa.Column('family_key', sa.String(length=128), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['course'], ['classes.course'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['family_key'], ['task_families.key'], ),
    sa.PrimaryKeyConstraint('course', 'family_key')
    )
    op.create_table('units',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('course', sa.String(length=32), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('n', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('covers', sa.JSON(), nullable=False),
    sa.Column('blurb', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('caveat', sa.Text(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['course'], ['classes.course'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('course', 'key', name='uq_units_course_key'),
    sa.UniqueConstraint('course', 'n', name='uq_units_course_n')
    )
    op.create_table('unit_families',
    sa.Column('unit_id', sa.String(length=32), nullable=False),
    sa.Column('course', sa.String(length=32), nullable=False),
    sa.Column('family_key', sa.String(length=128), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['course', 'family_key'], ['class_task_families.course', 'class_task_families.family_key'], name='fk_unit_families_class_family'),
    sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('unit_id', 'family_key'),
    sa.UniqueConstraint('family_key', name='uq_unit_families_family')
    )


def downgrade() -> None:
    # Children before parents. Dropping these discards every admin edit made
    # since seeding; `GET /admin/export` (or `python -m ida_core.configdb
    # diff`) first if anything here matters.
    op.drop_table('unit_families')
    op.drop_table('units')
    op.drop_table('class_task_families')
    op.drop_index(op.f('ix_tasks_family_key'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_table('models')
    op.drop_table('classes')
    op.drop_index(op.f('ix_task_revisions_task_id'), table_name='task_revisions')
    op.drop_index(op.f('ix_task_revisions_content_sha'), table_name='task_revisions')
    op.drop_table('task_revisions')
    op.drop_table('task_families')
    op.drop_table('provider_credentials')
    op.drop_table('model_families')
    op.drop_table('majors')
    op.drop_table('curriculum_documents')
    op.drop_table('config_revisions')
    op.drop_index('ix_audit_log_entity', table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_at'), table_name='audit_log')
    op.drop_table('audit_log')
