"""Mensagens do portal, endereçadas por código.

Após um POST bem-sucedido o portal redireciona (padrão POST-Redirect-GET, que
evita reenvio ao atualizar a página), e o resultado viaja na query string. Só
viajam **códigos**, nunca o texto: assim a query string não vira um canal para
injetar mensagem arbitrária numa página autenticada.

O texto também troca o jargão do domínio por linguagem de operação — quem usa o
portal não precisa saber o que é uma violação de índice parcial.
"""

_MENSAGENS: dict[str, tuple[str, str]] = {
    # sucesso
    "cliente-criado": ("ok", "Cliente cadastrado."),
    "cliente-salvo": ("ok", "Cadastro atualizado."),
    "titular-alterado": ("ok", "Titular atualizado."),
    "titular-sem-mudanca": ("ok", "Esse já era o titular; nada mudou."),
    "contato-criado": ("ok", "Contato adicionado."),
    "contato-salvo": ("ok", "Contato atualizado."),
    "localidade-criada": ("ok", "Localidade adicionada."),
    "localidade-salva": ("ok", "Localidade atualizada."),
    "usuario-criado": ("ok", "Usuário criado."),
    "usuario-salvo": ("ok", "Usuário atualizado."),
    "preferido-adicionado": ("ok", "Produto incluído entre os preferidos."),
    "preferido-salvo": ("ok", "Preferências atualizadas."),
    "artigo-cadastrado": (
        "ok",
        "Artigo cadastrado e incluído entre os preferidos. O preço entrou como "
        "rascunho na tabela do mês: publique o lote em Tabelas para ele passar "
        "a valer.",
    ),
    "lote-publicado": ("ok", "Tabela publicada na competência."),
    "regra-criada": ("ok", "Regra de ICMS cadastrada."),
    # falhas de validação
    "uf-invalida": ("erro", "UF inválida. Use uma das 27 unidades federativas."),
    "documento-duplicado": ("erro", "Já existe um cliente com esse documento."),
    "telefone-duplicado": ("erro", "Esse WhatsApp já pertence a outro contato."),
    "telefone-invalido": (
        "erro",
        "Telefone inválido. Use o formato internacional, como +55 11 99999-9999.",
    ),
    "padrao-obrigatoria": (
        "erro",
        "Promova outra localidade a padrão antes de desativar esta.",
    ),
    "titular-invalido": ("erro", "O titular escolhido precisa ser um usuário ativo."),
    "email-duplicado": ("erro", "Já existe um usuário com esse e-mail."),
    "senha-fraca": (
        "erro",
        "Senha recusada: mínimo de 12 caracteres, com ao menos uma letra e um "
        "número, e sem conter a parte do e-mail antes do @.",
    ),
    "alteracao-insegura": (
        "erro",
        "Alteração recusada: você não pode desativar a própria conta nem deixar "
        "o tenant sem administrador ativo.",
    ),
    "preferido-duplicado": ("erro", "Esse produto já está entre os preferidos."),
    "produto-inexistente": ("erro", "Produto não encontrado no catálogo."),
    "artigo-incompleto": ("erro", "Informe o SKU e o nome comercial do artigo."),
    "artigo-invalido": ("erro", "Dados do artigo inválidos. Refaça o cadastro pela tela."),
    "sku-duplicado": (
        "erro",
        "Já existe um artigo com esse SKU. Procure-o na busca em vez de "
        "cadastrar outro.",
    ),
    "familia-obrigatoria": (
        "erro",
        "Escolha uma família existente ou informe o nome de uma nova.",
    ),
    "preco-obrigatorio": (
        "erro",
        "Informe o preço-base, ou mude a disponibilidade para sem estoque, "
        "suspenso ou sob consulta.",
    ),
    "preco-invalido": ("erro", "Preço inválido. Use números, como 12,34."),
    "lote-nao-publicavel": (
        "erro",
        "Este lote está cancelado ou expirado e não pode ser publicado.",
    ),
    "regra-conflitante": (
        "erro",
        "Escolha produto ou família, não os dois: são níveis diferentes de "
        "especificidade e juntos tornariam a precedência ambígua.",
    ),
    "aliquota-invalida": ("erro", "Alíquota fora da faixa aceitável."),
    # falhas que impedem a lista de preço — descritas pelo que falta fazer,
    # porque cada uma tem uma correção diferente e nenhuma é automática
    "sem-regra-icms": (
        "erro",
        "Não há regra de ICMS para esse par de UFs. Cadastre-a na matriz antes "
        "de gerar a lista — o sistema não estima alíquota.",
    ),
    "regra-ambigua": (
        "erro",
        "Duas regras igualmente específicas cobrem esse caso. Ajuste a "
        "prioridade ou a vigência de uma delas.",
    ),
    "sem-origem": (
        "erro",
        "A UF de origem do faturamento não está configurada no tenant.",
    ),
    "sem-localidade": (
        "erro",
        "O cliente não tem localidade padrão ativa; sem ela não há UF de destino.",
    ),
    "sem-competencia": (
        "erro",
        "Nenhuma competência publicada até esta data. Publique a tabela do mês.",
    ),
    # falhas de contexto
    "nao-encontrado": ("erro", "Registro não encontrado."),
    "csrf": ("erro", "O formulário expirou. Tente novamente."),
    "sem-permissao": ("erro", "Seu papel não permite essa operação."),
    "credenciais": ("erro", "E-mail ou senha inválidos."),
    "muitas-tentativas": ("erro", "Tentativas demais. Aguarde alguns minutos."),
    "expirada": ("erro", "Sua sessão expirou. Entre novamente."),
}


def resolve(codigo: str | None) -> tuple[str | None, str | None]:
    """Devolve `(aviso, erro)` para o contexto do template."""
    if not codigo:
        return None, None
    entrada = _MENSAGENS.get(codigo)
    if entrada is None:
        return None, None
    tipo, texto = entrada
    return (texto, None) if tipo == "ok" else (None, texto)
