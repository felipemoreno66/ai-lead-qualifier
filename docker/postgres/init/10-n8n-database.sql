-- n8n keeps its data in its own database on the same server (no SQLite file locks).
SELECT 'CREATE DATABASE n8n'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')\gexec
