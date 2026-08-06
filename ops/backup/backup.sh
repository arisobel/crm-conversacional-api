#!/bin/sh
# Um ciclo de backup: dump lógico, envio cifrado e descarte do arquivo local.
# Atende um ou vários bancos; ver README para o formato de BACKUP_DATABASES.
set -eu

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY é obrigatória}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD é obrigatória}"

BACKUP_ROOT="/var/backups"

cleanup_all() {
    # Nenhum dump legível sobrevive ao ciclo, nem quando ele falha no meio.
    find "$BACKUP_ROOT" -name "*.dump" -type f -delete 2>/dev/null || true
}
trap cleanup_all EXIT INT TERM

# `postgresql+asyncpg://` é dialeto do SQLAlchemy. O libpq não entende o sufixo
# e falha com "invalid URI scheme", então ele sai aqui.
strip_dialect() {
    printf '%s' "$1" | sed 's|+asyncpg||; s|+psycopg2||; s|+psycopg||'
}

backup_one() {
    name="$1"
    url="$2"

    case "$name" in
        *[!a-zA-Z0-9_-]*|"")
            echo "[backup] ERRO: nome '$name' deve conter apenas letras, números, - e _" >&2
            return 1
            ;;
    esac

    # Um diretório por banco: o caminho estável é o que permite ao restic
    # deduplicar os blocos que não mudaram de um dia para o outro.
    target_dir="${BACKUP_ROOT}/${name}"
    dump_file="${target_dir}/${name}.dump"
    mkdir -p "$target_dir"

    echo "[backup] ${name}: iniciando dump"

    # --compress=0 de propósito: comprimir aqui produziria um arquivo diferente
    # a cada execução mesmo com dados idênticos, destruindo a deduplicação. O
    # restic comprime e deduplica melhor do que o pg_dump sozinho.
    if ! pg_dump \
        --dbname="$(strip_dialect "$url")" \
        --format=custom \
        --compress=0 \
        --no-owner \
        --no-privileges \
        --file="$dump_file"
    then
        echo "[backup] ${name}: ERRO no pg_dump" >&2
        rm -f "$dump_file"
        return 1
    fi

    # Um pg_dump interrompido pode deixar arquivo truncado. Enviá-lo como
    # sucesso é pior do que não ter backup: cria confiança injustificada.
    if [ ! -s "$dump_file" ]; then
        echo "[backup] ${name}: ERRO: dump vazio; nada será enviado" >&2
        rm -f "$dump_file"
        return 1
    fi

    echo "[backup] ${name}: $(wc -c < "$dump_file") bytes; enviando"

    if ! restic backup "$dump_file" \
        --tag "$name" \
        --tag automated \
        --host "${BACKUP_HOST_TAG:-caprover}"
    then
        echo "[backup] ${name}: ERRO no envio" >&2
        rm -f "$dump_file"
        return 1
    fi

    rm -f "$dump_file"
    echo "[backup] ${name}: concluído"
}

echo "[backup] $(date -u +%Y-%m-%dT%H:%M:%SZ) ciclo iniciado"

failures=0
processed=0

if [ -n "${BACKUP_DATABASES:-}" ]; then
    # Uma linha por banco: "<nome> <dsn>". O separador é espaço/quebra de linha
    # porque nenhum dos dois pode aparecer em uma URL válida — diferente de `;`
    # ou `,`, que apareceriam em uma senha e quebrariam o parsing.
    #
    # Here-document, e não `printf | while`: um pipe põe o laço em subshell e os
    # contadores abaixo seriam descartados ao final dele.
    while IFS=' ' read -r name url rest; do
        [ -z "$name" ] && continue
        case "$name" in \#*) continue ;; esac

        processed=$((processed + 1))
        if [ -z "$url" ]; then
            echo "[backup] ERRO: linha '$name' sem DSN" >&2
            failures=$((failures + 1))
            continue
        fi
        [ -n "$rest" ] && echo "[backup] aviso: texto extra após o DSN de ${name}" >&2

        if ! backup_one "$name" "$url"; then
            failures=$((failures + 1))
        fi
    done <<EOF
$BACKUP_DATABASES
EOF
elif [ -n "${BACKUP_DATABASE_URL:-}" ]; then
    processed=1
    backup_one "${BACKUP_DB_NAME:-crm}" "$BACKUP_DATABASE_URL" || failures=1
else
    echo "[backup] ERRO: defina BACKUP_DATABASES ou BACKUP_DATABASE_URL" >&2
    exit 1
fi

if [ "$processed" -eq 0 ]; then
    echo "[backup] ERRO: nenhum banco processado" >&2
    exit 1
fi

# A retenção exige permissão de apagar. Com uma chave append-only — que é a
# recomendação — este bloco falharia, e a limpeza é feita à parte, de uma
# máquina confiável. Ver README.
if [ "${RESTIC_PRUNE:-false}" = "true" ]; then
    echo "[backup] aplicando retenção"
    restic forget \
        --group-by host,tags \
        --keep-daily "${KEEP_DAILY:-7}" \
        --keep-weekly "${KEEP_WEEKLY:-5}" \
        --keep-monthly "${KEEP_MONTHLY:-12}" \
        --prune
fi

if [ "${RESTIC_CHECK:-false}" = "true" ]; then
    echo "[backup] verificando integridade do repositório"
    restic check --read-data-subset="${RESTIC_CHECK_SUBSET:-5%}"
fi

restic snapshots --latest 5

if [ "$failures" -gt 0 ]; then
    echo "[backup] $(date -u +%Y-%m-%dT%H:%M:%SZ) ciclo terminou com ${failures} falha(s)" >&2
    exit 1
fi

echo "[backup] $(date -u +%Y-%m-%dT%H:%M:%SZ) ciclo concluído: ${processed} banco(s)"
