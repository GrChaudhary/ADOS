-- Runs once, automatically, on first `docker compose up` (mounted at
-- /docker-entrypoint-initdb.d/) — creates the test database alongside the
-- default POSTGRES_DB so tests never need a manual setup step beyond
-- `docker compose up -d postgres`. See conftest.py for how tests point at
-- this database instead of the dev one.
CREATE DATABASE ados_test;
