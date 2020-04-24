from django.conf import settings
from django.db import migrations
from django.db import connection, migrations
from django.db.backends.postgresql_psycopg2.schema import DatabaseSchemaEditor
from django.db.migrations.state import StateApps
from zerver.lib.migrate import do_batch_update


def rebuild_pgroonga_index(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    with connection.cursor() as cursor:
        do_batch_update(cursor, 'zerver_message', ['search_pgroonga'],
                        ["escape_html(subject) || ' ' || rendered_content"],
                        escape=False, batch_size=10000)


    @staticmethod
    def noop(apps, schema_editor):
        return None


SQL_27 = """
ALTER ROLE zulip SET search_path TO zulip,public,pgroonga,pg_catalog;

SET search_path = zulip,public,pgroonga,pg_catalog;

ALTER TABLE zerver_message ADD COLUMN search_pgroonga text;

-- TODO: We want to use CREATE INDEX CONCURRENTLY but it can't be used in
-- transaction. Django uses transaction implicitly.
-- Django 1.10 may solve the problem.
CREATE INDEX zerver_message_search_pgroonga ON zerver_message
  USING pgroonga(search_pgroonga pgroonga.text_full_text_search_ops);
"""

SQL_27_ROLLBACK = """
SET search_path = zulip,public,pgroonga,pg_catalog;

DROP INDEX zerver_message_search_pgroonga;
ALTER TABLE zerver_message DROP COLUMN search_pgroonga;

SET search_path = zulip,public;

ALTER ROLE zulip SET search_path TO zulip,public;
"""

SQL_28 = """['\nALTER ROLE zulip SET search_path TO zulip,public;\n\nSET search_path = zulip,public;\n\nDROP INDEX zerver_message_search_pgroonga;\n', '\n\nCREATE INDEX CONCURRENTLY zerver_message_search_pgroonga ON zerver_message\n  USING pgroonga(search_pgroonga pgroonga_text_full_text_search_ops_v2);\n']"""

SQL_28_ROLLBACK = """['\nALTER ROLE zulip SET search_path TO zulip,public,pgroonga,pg_catalog;\n\nSET search_path = zulip,public,pgroonga,pg_catalog;\n\nDROP INDEX zerver_message_search_pgroonga;\n', '\n\nCREATE INDEX CONCURRENTLY zerver_message_search_pgroonga ON zerver_message\n  USING pgroonga(search_pgroonga pgroonga.text_full_text_search_ops);\n        ']"""

class Migration(migrations.Migration):

    replaces = [('pgroonga', '0001_enable'), ('pgroonga', '0002_html_escape_subject'), ('pgroonga', '0003_v2_api_upgrade')]

    dependencies = [
    ]

    operations = [
        migrations.RunSQL(
            sql=SQL_27,
            reverse_sql=SQL_27_ROLLBACK,
            elidable=False,
        ),
        migrations.RunPython(
            code=rebuild_pgroonga_index,
            reverse_code=RunPython.noop_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2_2,
            elidable=False,
        ),
        migrations.RunSQL(
            sql=SQL_28,
            reverse_sql=SQL_28_ROLLBACK,
            elidable=False,
        ),
    ]
