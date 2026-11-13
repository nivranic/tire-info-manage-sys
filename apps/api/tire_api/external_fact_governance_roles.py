"""Auditable, non-owner PostgreSQL privileges for the governance workstation.

No connection, password, role creation or grants are performed by the SQL-plan
command. A DBA reviews/applies its output in the explicitly named database.
"""
import argparse
import json
import re
import sys

from sqlalchemy import text

from .external_fact_governance import GovernanceError


READ_TABLES = (
    'audit_events', 'external_fact_grant_revisions', 'external_fact_license_evidence',
    'query_runs', 'safety_gate_snapshots', 'safety_gate_verifications', 'snapshots',
    'tire_schema_versions', 'users', 'verifications',
)
APPEND_TABLES = ('audit_events', 'external_fact_grant_revisions', 'external_fact_license_evidence')


def _identifier(value):
    if type(value) is not str or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,62}', value) is None:
        raise GovernanceError('postgres_role_identifier_invalid')
    return value


def _audit_sql(*, require_grants):
    """One catalog query; all identifiers/privileges are reviewed constants.

    Native pg_settings UPDATE is PostgreSQL's session-local SET interface,
    available to PUBLIC. Keep its built-in parameter checks; separately reject
    explicit parameter ACLs that could authorize privileged settings.
    """
    allowed = ','.join("('%s',%s)" % (name, 'true' if name in APPEND_TABLES else 'false') for name in READ_TABLES)
    query = """
WITH target AS (SELECT * FROM pg_catalog.pg_roles WHERE rolname = :role),
allowed(name, appendable) AS (VALUES ALLOWED_VALUES),
relations AS (
 SELECT c.oid, c.relname, c.relkind, c.relrowsecurity, n.nspname
 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
), system_relations AS (
 SELECT c.oid, c.relname, n.nspname
 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE (n.nspname ~ '^pg_' OR n.nspname='information_schema') AND c.relkind IN ('r','p','v','m','f')
), checks(code, failed) AS (
 SELECT 'role_missing', NOT EXISTS(SELECT 1 FROM target)
 UNION ALL SELECT 'role_attributes', EXISTS(SELECT 1 FROM target WHERE
   NOT rolcanlogin OR rolinherit OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
 UNION ALL SELECT 'role_memberships', EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m, target t
   WHERE m.member=t.oid OR m.roleid=t.oid)
 UNION ALL SELECT 'default_privileges', EXISTS(
   SELECT 1 FROM target t, pg_catalog.pg_default_acl d, pg_catalog.aclexplode(d.defaclacl) a
   WHERE a.grantee=t.oid OR (a.grantee=0 AND d.defaclobjtype IN ('r','S','n')))
 UNION ALL SELECT 'object_ownership', EXISTS(SELECT 1 FROM pg_catalog.pg_shdepend d, target t
   WHERE d.refclassid='pg_catalog.pg_authid'::regclass AND d.refobjid=t.oid AND d.deptype='o')
 UNION ALL SELECT 'database_ddl', EXISTS(SELECT 1 FROM target t WHERE
   pg_catalog.has_database_privilege(t.oid, current_database(), 'CREATE') OR
   pg_catalog.has_database_privilege(t.oid, current_database(), 'TEMPORARY') OR
   pg_catalog.has_database_privilege(t.oid, current_database(), 'CONNECT WITH GRANT OPTION'))
 UNION ALL SELECT 'schema_ddl', EXISTS(SELECT 1 FROM pg_catalog.pg_namespace n, target t
   WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema' AND
   (pg_catalog.has_schema_privilege(t.oid,n.oid,'CREATE') OR pg_catalog.has_schema_privilege(t.oid,n.oid,'USAGE WITH GRANT OPTION')))
 UNION ALL SELECT 'required_tables', EXISTS(SELECT 1 FROM allowed a WHERE NOT EXISTS(
   SELECT 1 FROM relations r WHERE r.nspname='public' AND r.relname=a.name AND r.relkind IN ('r','p')))
 UNION ALL SELECT 'row_security_unsupported', EXISTS(SELECT 1 FROM relations r JOIN allowed a ON a.name=r.relname
   WHERE r.nspname='public' AND r.relrowsecurity)
 UNION ALL SELECT 'table_privileges', EXISTS(
   SELECT 1 FROM target t CROSS JOIN relations r
   CROSS JOIN (VALUES ('SELECT'),('INSERT'),('UPDATE'),('DELETE'),('TRUNCATE'),('REFERENCES'),('TRIGGER'),('MAINTAIN')) p(priv)
   LEFT JOIN allowed a ON r.nspname='public' AND r.relname=a.name
   WHERE r.relkind IN ('r','p','v','m','f') AND pg_catalog.has_table_privilege(t.oid,r.oid,p.priv)
   AND NOT (COALESCE(a.name IS NOT NULL AND p.priv='SELECT',false) OR COALESCE(a.appendable AND p.priv='INSERT',false)))
 UNION ALL SELECT 'table_grant_options', EXISTS(
   SELECT 1 FROM target t, relations r,
   (VALUES ('SELECT'),('INSERT'),('UPDATE'),('DELETE'),('TRUNCATE'),('REFERENCES'),('TRIGGER'),('MAINTAIN')) p(priv)
   WHERE r.relkind IN ('r','p','v','m','f') AND pg_catalog.has_table_privilege(t.oid,r.oid,p.priv || ' WITH GRANT OPTION'))
 UNION ALL SELECT 'column_privileges', EXISTS(
   SELECT 1 FROM target t CROSS JOIN relations r
   JOIN pg_catalog.pg_attribute c ON c.attrelid=r.oid AND c.attnum>0 AND NOT c.attisdropped
   CROSS JOIN (VALUES ('SELECT'),('INSERT'),('UPDATE'),('REFERENCES')) p(priv)
   LEFT JOIN allowed a ON r.nspname='public' AND r.relname=a.name
   WHERE r.relkind IN ('r','p','v','m','f') AND pg_catalog.has_column_privilege(t.oid,r.oid,c.attnum,p.priv)
   AND NOT (COALESCE(a.name IS NOT NULL AND p.priv='SELECT',false) OR COALESCE(a.appendable AND p.priv='INSERT',false)
     OR (r.nspname='public' AND r.relname='users' AND c.attname='display_name' AND p.priv='UPDATE')))
 UNION ALL SELECT 'column_grant_options', EXISTS(
   SELECT 1 FROM target t CROSS JOIN relations r
   JOIN pg_catalog.pg_attribute c ON c.attrelid=r.oid AND c.attnum>0 AND NOT c.attisdropped
   CROSS JOIN (VALUES ('SELECT'),('INSERT'),('UPDATE'),('REFERENCES')) p(priv)
   WHERE r.relkind IN ('r','p','v','m','f') AND pg_catalog.has_column_privilege(t.oid,r.oid,c.attnum,p.priv || ' WITH GRANT OPTION'))
 UNION ALL SELECT 'sequence_privileges', EXISTS(SELECT 1 FROM target t, relations r,
   (VALUES ('SELECT'),('UPDATE'),('USAGE')) p(priv)
   WHERE r.relkind='S' AND pg_catalog.has_sequence_privilege(t.oid,r.oid,p.priv))
 UNION ALL SELECT 'security_definer_access', EXISTS(
   SELECT 1 FROM target t, pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema' AND p.prosecdef
   AND pg_catalog.has_function_privilege(t.oid,p.oid,'EXECUTE'))
 UNION ALL SELECT 'catalog_secrets', EXISTS(
   SELECT 1 FROM target t CROSS JOIN system_relations r
   JOIN pg_catalog.pg_attribute c ON c.attrelid=r.oid AND c.attnum>0 AND NOT c.attisdropped
   WHERE r.nspname='pg_catalog' AND r.relname IN ('pg_authid','pg_shadow','pg_user_mapping')
   AND pg_catalog.has_column_privilege(t.oid,r.oid,c.attnum,'SELECT'))
 UNION ALL SELECT 'catalog_writes', EXISTS(
   SELECT 1 FROM target t, system_relations r,
   (VALUES ('INSERT'),('UPDATE'),('DELETE'),('TRUNCATE'),('REFERENCES'),('TRIGGER'),('MAINTAIN'),
           ('SELECT WITH GRANT OPTION'),('UPDATE WITH GRANT OPTION')) p(priv)
   WHERE pg_catalog.has_table_privilege(t.oid,r.oid,p.priv)
   AND NOT (r.nspname='pg_catalog' AND r.relname='pg_settings' AND p.priv='UPDATE')) OR EXISTS(
   SELECT 1 FROM target t CROSS JOIN system_relations r
   JOIN pg_catalog.pg_attribute c ON c.attrelid=r.oid AND c.attnum>0 AND NOT c.attisdropped
   CROSS JOIN (VALUES ('INSERT'),('UPDATE'),('REFERENCES'),('SELECT WITH GRANT OPTION'),('UPDATE WITH GRANT OPTION')) p(priv)
   WHERE pg_catalog.has_column_privilege(t.oid,r.oid,c.attnum,p.priv)
   AND NOT (r.nspname='pg_catalog' AND r.relname='pg_settings' AND p.priv='UPDATE'))
 UNION ALL SELECT 'parameter_privileges', EXISTS(
   SELECT 1 FROM target t, pg_catalog.pg_parameter_acl p, pg_catalog.aclexplode(p.paracl) a
   WHERE a.grantee IN (t.oid,0))
 UNION ALL SELECT 'explicit_routine_privileges', EXISTS(
   SELECT 1 FROM target t, pg_catalog.pg_proc p, pg_catalog.aclexplode(p.proacl) a
   WHERE a.grantee=t.oid AND a.privilege_type='EXECUTE')
 UNION ALL SELECT 'server_file_routines', EXISTS(
   SELECT 1 FROM target t, pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='pg_catalog' AND p.proname IN ('pg_read_file','pg_read_binary_file','pg_ls_dir','pg_stat_file')
   AND pg_catalog.has_function_privilege(t.oid,p.oid,'EXECUTE'))
 REQUIRED_CHECKS
)
SELECT code FROM checks WHERE failed ORDER BY code
""".replace('ALLOWED_VALUES', allowed)
    required = """
 UNION ALL SELECT 'required_access', EXISTS(SELECT 1 FROM target t WHERE
   NOT pg_catalog.has_database_privilege(t.oid,current_database(),'CONNECT') OR
   NOT pg_catalog.has_schema_privilege(t.oid,'public','USAGE'))
 UNION ALL SELECT 'required_table_grants', EXISTS(SELECT 1 FROM target t, relations r JOIN allowed a ON a.name=r.relname
   WHERE r.nspname='public' AND r.relkind IN ('r','p') AND
   (NOT pg_catalog.has_table_privilege(t.oid,r.oid,'SELECT') OR
    (a.appendable AND NOT pg_catalog.has_table_privilege(t.oid,r.oid,'INSERT'))))
 UNION ALL SELECT 'actor_lock_grant', EXISTS(SELECT 1 FROM target t WHERE NOT EXISTS(
   SELECT 1 FROM relations r JOIN pg_catalog.pg_attribute c ON c.attrelid=r.oid AND c.attnum>0 AND NOT c.attisdropped
   WHERE r.nspname='public' AND r.relname='users' AND c.attname='display_name'
   AND pg_catalog.has_column_privilege(t.oid,r.oid,c.attnum,'UPDATE')))
""" if require_grants else ''
    return query.replace('REQUIRED_CHECKS', required)


def check_governance_role(engine):
    """Read-only effective-ACL snapshot for this connection's current role only."""
    with engine.connect() as connection:
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        version = int(connection.exec_driver_sql("SELECT current_setting('server_version_num')").scalar())
        if version < 170000:
            violations = ['server_version_unsupported']
        else:
            role = connection.exec_driver_sql('SELECT current_user').scalar()
            violations = list(connection.execute(text(_audit_sql(require_grants=True)), {'role': role}).scalars())
    return {'schema': 'external-fact-role-check@1', 'ok': not violations, 'violations': violations}


def governance_role_sql(role, database):
    """Generate a reviewable atomic GRANT plan, without contacting a database."""
    role, database = _identifier(role), _identifier(database)
    def guard(required):
        query = _audit_sql(require_grants=required).replace(':role', "'" + role + "'")
        return "DO $governance_role$ BEGIN IF EXISTS (" + query + ") THEN " \
            "RAISE EXCEPTION 'postgres_governance_role_rejected'; END IF; END $governance_role$;"
    statements = [
        'BEGIN;', "SET LOCAL search_path = pg_catalog, public;", "SET LOCAL lock_timeout = '2s';",
        "SET LOCAL statement_timeout = '5s';",
        "SET LOCAL idle_in_transaction_session_timeout = '15s';",
        "SELECT pg_advisory_xact_lock(821741905);",
        "DO $governance_role$ BEGIN IF current_database() <> '" + database + "' OR "
        "current_setting('server_version_num')::int < 170000 THEN "
        "RAISE EXCEPTION 'postgres_governance_target_invalid'; END IF; END $governance_role$;",
        guard(False),
        f'GRANT CONNECT ON DATABASE "{database}" TO "{role}";',
        f'GRANT USAGE ON SCHEMA public TO "{role}";',
        'GRANT SELECT ON ' + ', '.join('public.' + name for name in READ_TABLES) + f' TO "{role}";',
        'GRANT INSERT ON ' + ', '.join('public.' + name for name in APPEND_TABLES) + f' TO "{role}";',
        f'GRANT UPDATE (display_name) ON public.users TO "{role}";',
        guard(True), 'COMMIT;',
    ]
    return '\n\n'.join(statements) + '\n'


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise GovernanceError('request_invalid')


def main(argv=None):
    try:
        parser = _Parser(description='Generate SQL for DBA review; never connects or creates roles.')
        parser.add_argument('--role', required=True)
        parser.add_argument('--database', required=True)
        args = parser.parse_args(argv)
        output = governance_role_sql(args.role, args.database)
    except GovernanceError as error:
        print(json.dumps({'ok': False, 'code': error.code}), file=sys.stderr)
        return 1
    print(output, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
