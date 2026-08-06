#!/bin/sh
# Ensaio de restauração. Um backup que nunca foi restaurado não é um backup.
#
#   restore.sh                          lista os snapshots disponíveis
#   restore.sh <snapshot|latest> [nome] baixa o dump e valida que é legível
#
# Restaurar POR CIMA de um banco existente exige RESTORE_TARGET_URL e
# RESTORE_CONFIRM=yes. Sem os dois, o script apenas deixa o arquivo pronto.
set -eu

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY é obrigatória}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD é obrigatória}"

SNAPSHOT="${1:-}"
DB_NAME="${2:-${RESTORE_DB_NAME:-crm}}"
TARGET_DIR="${RESTORE_DIR:-/var/backups/restore}"

if [ -z "$SNAPSHOT" ]; then
    echo "Snapshots disponíveis:"
    restic snapshots
    echo
    echo "Use: restore.sh latest [nome-do-banco]"
    exit 0
fi

mkdir -p "$TARGET_DIR"
echo "[restore] baixando snapshot ${SNAPSHOT} do banco '${DB_NAME}'"

# `latest` sozinho pegaria o snapshot mais recente de qualquer banco; a tag
# garante que venha o do banco pedido.
if [ "$SNAPSHOT" = "latest" ]; then
    restic restore latest --tag "$DB_NAME" --target "$TARGET_DIR"
else
    restic restore "$SNAPSHOT" --target "$TARGET_DIR"
fi

DUMP_FILE=$(find "$TARGET_DIR" -name "${DB_NAME}.dump" -type f | head -1)
if [ -z "$DUMP_FILE" ]; then
    echo "[restore] ERRO: ${DB_NAME}.dump não encontrado no snapshot" >&2
    find "$TARGET_DIR" -name "*.dump" -type f >&2
    exit 1
fi

echo "[restore] dump em ${DUMP_FILE} ($(wc -c < "$DUMP_FILE") bytes)"

# Verificação barata que já pega dump corrompido: pg_restore precisa ler o
# índice interno do arquivo para conseguir listar seu conteúdo.
echo "[restore] conteúdo (primeiras linhas):"
pg_restore --list "$DUMP_FILE" | head -20

if [ -z "${RESTORE_TARGET_URL:-}" ]; then
    echo
    echo "[restore] nenhum RESTORE_TARGET_URL definido; parando aqui."
    echo "Para restaurar em um banco vazio de teste:"
    echo "  RESTORE_TARGET_URL=postgresql://user:senha@host:5432/teste \\"
    echo "  RESTORE_CONFIRM=yes restore.sh ${SNAPSHOT} ${DB_NAME}"
    exit 0
fi

if [ "${RESTORE_CONFIRM:-no}" != "yes" ]; then
    echo "[restore] RESTORE_CONFIRM=yes é obrigatório para escrever no banco" >&2
    exit 1
fi

DSN=$(printf '%s' "$RESTORE_TARGET_URL" | sed 's|+asyncpg||; s|+psycopg2||; s|+psycopg||')

echo "[restore] restaurando (isto ESCREVE no banco de destino)"
pg_restore \
    --dbname="$DSN" \
    --no-owner \
    --no-privileges \
    --single-transaction \
    "$DUMP_FILE"

rm -rf "$TARGET_DIR"
echo "[restore] concluído. Confira a contagem das tabelas antes de confiar."
