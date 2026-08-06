#!/bin/sh
# Inicializa o repositório se preciso e executa o ciclo de backup em laço.
set -eu

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY é obrigatória}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD é obrigatória}"

if [ "$#" -gt 0 ]; then
    # Permite abrir um shell ou rodar `restore.sh` no mesmo container.
    exec "$@"
fi

if ! restic cat config >/dev/null 2>&1; then
    echo "[entrypoint] repositório ausente; inicializando"
    restic init
fi

# O primeiro ciclo roda na subida, de propósito: um erro de credencial ou de
# rede aparece no log do deploy, e não silenciosamente 24 horas depois.
/usr/local/bin/backup.sh

if [ "${RUN_ONCE:-false}" = "true" ]; then
    echo "[entrypoint] RUN_ONCE ativo; encerrando"
    exit 0
fi

INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

while true; do
    echo "[entrypoint] próximo ciclo em ${INTERVAL}s"
    sleep "$INTERVAL"
    # Uma falha isolada — rede, storage fora do ar — não pode matar o laço e
    # deixar o banco sem backup até alguém perceber que o container morreu.
    if ! /usr/local/bin/backup.sh; then
        echo "[entrypoint] ciclo falhou; tentando de novo no próximo intervalo" >&2
    fi
done
