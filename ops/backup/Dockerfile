# A imagem base acompanha a versão do servidor: pg_dump recusa dumpar um banco
# de versão maior que a sua. Se o PostgreSQL de produção subir para 17, esta
# linha sobe junto.
FROM postgres:16-alpine

RUN apk add --no-cache restic ca-certificates tzdata

COPY backup.sh restore.sh entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/restore.sh \
    /usr/local/bin/entrypoint.sh

# O dump em texto claro só existe dentro deste diretório e por poucos segundos;
# `backup.sh` o apaga assim que o restic termina de enviá-lo.
RUN mkdir -p /var/backups/crm
WORKDIR /var/backups/crm

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
