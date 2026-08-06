# Backup do PostgreSQL de produção

App CapRover dedicado que roda `pg_dump` em ciclo, cifra o resultado e o envia
para armazenamento de objetos **fora da VPS**. O dump em texto claro existe
dentro do container por segundos e é apagado assim que o envio termina.

## Por que não usar o pgweb

`sosedoff/pgweb` é um navegador web para PostgreSQL, não uma ferramenta de
backup. Ele exporta o resultado de uma consulta em CSV/JSON — sem schema, sem
constraints, sem sequences, sem enums, sem ordem de dependência entre tabelas.
Não existe caminho confiável de restauração a partir disso.

Além disso: se o pgweb estiver publicado em domínio público, ele é um console de
banco aberto na internet. Ou tire o domínio (deixe acessível só pela rede interna
do CapRover), ou no mínimo configure `AUTH_USER`/`AUTH_PASS` e aponte-o para um
usuário PostgreSQL somente-leitura.

## Decisões de desenho

| Decisão | Motivo |
|---|---|
| `pg_dump --format=custom` | Permite restauração seletiva e `pg_restore --list` |
| `--compress=0` | Comprimir aqui geraria arquivo diferente a cada execução com dados iguais, destruindo a deduplicação do restic |
| restic | Cifra no cliente, deduplica e versiona; o storage nunca vê dado legível |
| Nome de arquivo fixo | O histórico vem dos snapshots; caminho estável maximiza a dedup |
| Dump apagado após envio | Reduz a janela em que existe cópia legível do banco em disco |
| Falha de ciclo não mata o laço | Uma indisponibilidade de rede não pode deixar o banco sem backup até alguém notar o container morto |

## Armazenamento: proteção no bucket, não na chave

Backup que a VPS pode apagar não protege contra o cenário mais provável de perda
total: alguém com acesso ao servidor. A defesa, porém, **não** é uma chave S3 sem
permissão de apagar.

O restic cria um arquivo de lock a cada operação e o remove ao terminar. Com uma
chave que não pode apagar, o `backup` grava o snapshot mas falha ao liberar o
lock, e a execução seguinte para com "repository is already locked". O modo
append-only do restic existe só no `rest-server`, não no protocolo S3.

O que funciona é dar à chave acesso normal ao bucket e proteger o **bucket**:

| Provedor | Como proteger |
|---|---|
| Backblaze B2 | Object Lock, ou regra de ciclo de vida "keep prior versions" por N dias |
| AWS S3 | Versionamento + Object Lock (governance) |
| Wasabi | Object Lock |
| Cloudflare R2 | Sem Object Lock maduro; prefira B2 ou S3 se a imutabilidade importa |

Com versionamento ou Object Lock, um `DELETE` vindo da VPS não destrói o dado:
ele vira uma versão anterior recuperável durante a janela configurada. Escolha
uma janela maior que o intervalo entre os seus ensaios de restauração — se você
testa a cada trimestre, 30 dias é pouco.

Restrinja a chave **a este bucket** e não a reutilize em nenhum outro app.

Com a chave normal, `RESTIC_PRUNE=true` funciona. Deixe-o `false` no começo
mesmo assim, e rode a retenção à mão até confiar no conjunto:

```bash
restic forget --group-by host,tags \
  --keep-daily 7 --keep-weekly 5 --keep-monthly 12 --prune
```

## Variáveis de ambiente

## Vários bancos na mesma instância

Um app atende quantos bancos você quiser. Use `BACKUP_DATABASES`, uma linha por
banco, no formato `<nome> <dsn>`:

```
crm postgresql://crm:senha@srv-captain--postgres:5432/crm
loja postgresql://loja:senha@srv-captain--postgres:5432/loja
relatorios postgresql://ro:senha@outro-host:5432/relatorios
```

O separador é espaço e quebra de linha porque nenhum dos dois pode aparecer em
uma URL válida — diferente de `;` ou `,`, que apareceriam em uma senha e
quebrariam o parsing. Se a senha tiver caracteres especiais, use percent-encoding
(`@` vira `%40`, `/` vira `%2F`).

O `<nome>` vira a tag do snapshot e o nome do arquivo, então precisa ser único e
conter apenas letras, números, `-` e `_`. É por ele que a restauração encontra o
dump certo.

A falha de um banco não impede os outros: o ciclo continua e termina com código
de erro, para que a falha apareça no log sem custar os backups que deram certo.

Para um banco só, `BACKUP_DATABASE_URL` continua funcionando; o nome padrão é
`crm` e pode ser trocado em `BACKUP_DB_NAME`.

### Quando vale separar em dois apps

- Bancos de **donos diferentes**, para que uma credencial não alcance os dois.
- Servidor PostgreSQL de **versão maior que 16**: `pg_dump` recusa dumpar um
  banco mais novo que ele. Nesse caso, um app com `FROM postgres:17-alpine`.
  Versões mais antigas (14, 15) funcionam nesta imagem sem alteração.

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|:--:|---|
| `BACKUP_DATABASES` | sim¹ | Uma linha por banco: `<nome> <dsn>` |
| `BACKUP_DATABASE_URL` | sim¹ | Alternativa para um banco só. Aceita `postgresql+asyncpg://`; o sufixo é removido |
| `BACKUP_DB_NAME` | não | Nome usado com `BACKUP_DATABASE_URL`; padrão `crm` |
| `RESTIC_REPOSITORY` | sim | Ex.: `s3:s3.us-west-004.backblazeb2.com/meu-bucket/crm` |
| `RESTIC_PASSWORD` | sim | Senha de cifragem do repositório. **Perdê-la torna os backups ilegíveis** |
| `AWS_ACCESS_KEY_ID` | sim | Chave append-only do bucket |
| `AWS_SECRET_ACCESS_KEY` | sim | Segredo correspondente |
| `BACKUP_INTERVAL_SECONDS` | não | Padrão `86400` (24 h) |
| `RUN_ONCE` | não | `true` executa um ciclo e encerra |
| `RESTIC_PRUNE` | não | Padrão `false`; ative só depois do primeiro ensaio de restauração |
| `RESTIC_CHECK` | não | Padrão `false`; `true` verifica integridade a cada ciclo |
| `BACKUP_HOST_TAG` | não | Rótulo do host nos snapshots; padrão `caprover` |

¹ Uma das duas. `BACKUP_DATABASES` tem precedência se ambas estiverem definidas.

Guarde `RESTIC_PASSWORD` em um gerenciador de senhas **fora da VPS**. Sem ela não
há restauração — nem por você, nem pelo provedor.

## Implantação

```powershell
.\ops\backup\build-backup-tarball.ps1
```

No CapRover: crie o app `crm-backup`, **sem domínio público** (ele não expõe
porta alguma) e **sem dados persistentes**, preencha as variáveis acima e envie o
tarball gerado em `dist/`.

A ausência de volume é intencional: o único arquivo que o container escreve é o
dump em texto claro, e ele é apagado logo após o envio. Um volume persistente
manteria uma cópia legível do banco na própria VPS — exatamente o que este
desenho evita. Todo o estado real vive no bucket.

## Rodar um ciclo na hora

O ciclo roda sozinho na subida do container e depois a cada
`BACKUP_INTERVAL_SECONDS`. Para forçar um agora, por SSH na VPS:

```bash
docker exec $(docker ps -q -f name=srv-captain--pg-backup) backup.sh
```

O mesmo caminho serve para o ensaio de restauração, trocando `backup.sh` por
`restore.sh`. Use `-it` quando quiser um shell:

```bash
docker exec -it $(docker ps -q -f name=srv-captain--pg-backup) sh
```

Reiniciar o app pelo painel do CapRover também dispara um ciclo, já que o
primeiro roda na subida.

O primeiro ciclo roda na subida de propósito — erro de credencial ou de rede
aparece no log do deploy, não silenciosamente 24 horas depois.

Se o PostgreSQL for um app do próprio CapRover, `BACKUP_DATABASE_URL` usa o nome
interno, algo como
`postgresql://crm:senha@srv-captain--postgres:5432/crm`.

## Ensaio de restauração

Faça isto **agora**, e depois a cada trimestre. Backup nunca restaurado não é
backup — é uma suposição.

No terminal do container `crm-backup`:

```bash
# 1. o que existe
restore.sh

# 2. baixar o mais recente e conferir se o arquivo é legível
restore.sh latest crm

# 3. restaurar de verdade, em um banco VAZIO de teste
RESTORE_TARGET_URL=postgresql://user:senha@host:5432/crm_restore_test \
RESTORE_CONFIRM=yes restore.sh latest crm
```

O segundo argumento é o nome do banco definido em `BACKUP_DATABASES`. Sem ele,
`latest` traria o snapshot mais recente de qualquer banco.

O passo 2 já pega dump corrompido, porque `pg_restore --list` precisa ler o
índice do arquivo. O passo 3 é o que comprova que o banco volta.

Depois do passo 3, confira se os dados estão lá de verdade:

```sql
SELECT
  (SELECT count(*) FROM customers)        AS clientes,
  (SELECT count(*) FROM price_list_items) AS itens_de_preco,
  (SELECT count(*) FROM users)            AS usuarios;
```

`RESTORE_TARGET_URL` nunca deve apontar para o banco de produção. O script exige
`RESTORE_CONFIRM=yes` justamente porque não há como ele distinguir um do outro.

## Limitações conhecidas

- **Dump lógico diário, não PITR.** A perda máxima é de um dia de dados. Se isso
  for inaceitável, o passo seguinte é WAL archiving contínuo — outra arquitetura.
- **O laço usa `sleep`, não cron.** O horário desloca a cada reinício do
  container. Para backup diário isso é irrelevante; para janela fixa, não serve.
- **Sem alerta de falha.** O erro vai para o log do app. Enquanto não houver
  monitoramento, alguém precisa olhar — ou o backup silenciosamente para de
  existir. É a lacuna mais séria desta configuração.
