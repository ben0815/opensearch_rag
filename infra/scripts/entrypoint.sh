#!/bin/bash
set -e

# Datenbank-Schema auf den aktuellen Stand bringen.
# Bei einer leeren Datenbank werden alle Tabellen angelegt.
# Bei einer bereits aktuellen Datenbank ist dies ein No-op.
alembic upgrade head

exec python -m "$@"
