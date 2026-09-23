/* Melhorias progressivas do portal.
 *
 * Tudo aqui é opcional: sem este arquivo o `<select>` nativo continua
 * escolhendo o produto e o formulário do artigo aparece aberto na página
 * (ver portal-nojs.css). Nada de regra de negócio vive no navegador.
 *
 * Não há dependência externa de propósito: a CSP do portal é
 * `default-src 'self'`, então nenhum CDN carregaria, e trazer jQuery para um
 * portal server-rendered custaria mais do que as ~130 linhas abaixo.
 */
(function () {
  "use strict";

  /* Acento não pode atrapalhar a busca: quem digita "poliester" precisa achar
   * "Poliéster". NFD separa a letra do acento e a faixa combining o remove. */
  function normalizar(texto) {
    return texto
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .trim();
  }

  function casaTodosOsTermos(alvo, termos) {
    return termos.every(function (termo) {
      return alvo.indexOf(termo) !== -1;
    });
  }

  var sequencia = 0;

  function montarCombobox(caixa) {
    var select = caixa.querySelector("select");
    if (!select) {
      return;
    }
    sequencia += 1;
    var idDaLista = "combobox-lista-" + sequencia;

    var opcoes = Array.prototype.slice
      .call(select.options)
      .filter(function (opcao) {
        return opcao.value !== "";
      })
      .map(function (opcao) {
        return { valor: opcao.value, texto: opcao.textContent.trim() };
      });

    var entrada = document.createElement("input");
    entrada.type = "text";
    entrada.className = "combobox-entrada";
    entrada.autocomplete = "off";
    entrada.placeholder = caixa.dataset.rotulo || "Buscar…";
    entrada.setAttribute("role", "combobox");
    entrada.setAttribute("aria-expanded", "false");
    entrada.setAttribute("aria-autocomplete", "list");
    entrada.setAttribute("aria-controls", idDaLista);

    var lista = document.createElement("ul");
    lista.id = idDaLista;
    lista.className = "combobox-lista";
    lista.setAttribute("role", "listbox");
    lista.hidden = true;

    caixa.appendChild(entrada);
    caixa.appendChild(lista);

    /* O select continua no formulário e continua sendo quem carrega o valor
     * enviado. `required` sai dele porque um campo escondido e obrigatório
     * trava o envio num erro de validação que o usuário não consegue ver. */
    select.hidden = true;
    select.removeAttribute("required");
    select.setAttribute("tabindex", "-1");
    select.setAttribute("aria-hidden", "true");

    var destacado = -1;

    function fechar() {
      lista.hidden = true;
      entrada.setAttribute("aria-expanded", "false");
      entrada.removeAttribute("aria-activedescendant");
      destacado = -1;
    }

    function escolher(valor, texto) {
      select.value = valor;
      entrada.value = texto;
      fechar();
    }

    function itemDeCadastro(termo) {
      var alvo = caixa.dataset.modal;
      if (!alvo || !document.getElementById(alvo)) {
        return null;
      }
      var item = document.createElement("li");
      item.className = "combobox-item combobox-criar";
      item.setAttribute("role", "option");
      item.textContent = termo
        ? '+ Cadastrar artigo "' + termo + '"'
        : "+ Cadastrar artigo";
      item.addEventListener("mousedown", function (evento) {
        evento.preventDefault();
        fechar();
        abrirModal(alvo, caixa.dataset.campoNome, termo);
      });
      return item;
    }

    function desenhar() {
      var termos = normalizar(entrada.value).split(/\s+/).filter(Boolean);
      var achados = opcoes.filter(function (opcao) {
        return casaTodosOsTermos(normalizar(opcao.texto), termos);
      });

      lista.textContent = "";
      achados.slice(0, 50).forEach(function (opcao) {
        var item = document.createElement("li");
        item.className = "combobox-item";
        item.setAttribute("role", "option");
        item.textContent = opcao.texto;
        item.addEventListener("mousedown", function (evento) {
          // `mousedown` em vez de `click`: o blur da entrada fecharia a lista
          // antes de o clique chegar.
          evento.preventDefault();
          escolher(opcao.valor, opcao.texto);
        });
        lista.appendChild(item);
      });

      if (!achados.length) {
        var vazio = document.createElement("li");
        vazio.className = "combobox-item combobox-vazio";
        vazio.textContent = "Nenhum artigo encontrado.";
        lista.appendChild(vazio);
      }

      var criar = itemDeCadastro(entrada.value.trim());
      if (criar) {
        lista.appendChild(criar);
      }

      lista.hidden = false;
      entrada.setAttribute("aria-expanded", "true");
      destacado = -1;
    }

    function selecionaveis() {
      return Array.prototype.slice.call(
        lista.querySelectorAll(".combobox-item:not(.combobox-vazio)")
      );
    }

    function destacar(passo) {
      var itens = selecionaveis();
      if (!itens.length) {
        return;
      }
      itens.forEach(function (item, indice) {
        item.classList.remove("destacado");
        item.id = idDaLista + "-" + indice;
      });
      destacado = (destacado + passo + itens.length) % itens.length;
      itens[destacado].classList.add("destacado");
      itens[destacado].scrollIntoView({ block: "nearest" });
      entrada.setAttribute("aria-activedescendant", itens[destacado].id);
    }

    entrada.addEventListener("input", function () {
      // Digitar depois de escolher desfaz a escolha: o texto na tela e o valor
      // enviado não podem divergir.
      select.value = "";
      desenhar();
    });
    entrada.addEventListener("focus", desenhar);
    entrada.addEventListener("blur", fechar);
    entrada.addEventListener("keydown", function (evento) {
      if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
        evento.preventDefault();
        if (lista.hidden) {
          desenhar();
        }
        destacar(evento.key === "ArrowDown" ? 1 : -1);
        return;
      }
      if (evento.key === "Enter") {
        var itens = selecionaveis();
        if (!lista.hidden && destacado >= 0 && itens[destacado]) {
          evento.preventDefault();
          itens[destacado].dispatchEvent(new MouseEvent("mousedown"));
        }
        return;
      }
      if (evento.key === "Escape") {
        fechar();
      }
    });

    var formulario = select.form;
    if (formulario) {
      formulario.addEventListener("submit", function (evento) {
        if (!select.value) {
          evento.preventDefault();
          entrada.focus();
          desenhar();
        }
      });
    }
  }

  function abrirModal(id, campoNome, valorInicial) {
    var modal = document.getElementById(id);
    if (!modal) {
      return;
    }
    if (campoNome && valorInicial) {
      var campo = document.getElementById(campoNome);
      if (campo && !campo.value) {
        campo.value = valorInicial;
      }
    }
    if (typeof modal.showModal === "function") {
      modal.showModal();
    } else {
      modal.setAttribute("open", "open");
    }
    var primeiro = modal.querySelector("input, select, textarea");
    if (primeiro) {
      primeiro.focus();
    }
  }

  function ligarModais() {
    document.querySelectorAll("[data-abre]").forEach(function (botao) {
      botao.addEventListener("click", function () {
        abrirModal(botao.dataset.abre);
      });
    });
    document.querySelectorAll("[data-fecha]").forEach(function (botao) {
      botao.addEventListener("click", function () {
        var modal = document.getElementById(botao.dataset.fecha);
        if (modal) {
          modal.close();
        }
      });
    });
  }

  /* Campo que só faz sentido quando o select está na opção vazia — o nome da
   * família nova ao lado da lista de famílias existentes. */
  function ligarAlternancias() {
    document.querySelectorAll("select[data-alterna]").forEach(function (select) {
      var campo = document.getElementById(select.dataset.alterna);
      if (!campo) {
        return;
      }
      var sincronizar = function () {
        var novo = select.value === "";
        campo.hidden = !novo;
        campo.required = novo;
      };
      select.addEventListener("change", sincronizar);
      sincronizar();
    });
  }

  document.querySelectorAll("[data-combobox]").forEach(montarCombobox);
  ligarModais();
  ligarAlternancias();

  /* Onboarding é iniciado no CRM; somente a janela do launcher segue para o
   * Gateway. Abrir a janela no gesto do clique evita bloqueador de popup, e o
   * token interno nunca entra neste JavaScript. */
  function ligarWhatsappBusiness() {
    var painel = document.getElementById("whatsapp-connection");
    if (!painel) return;
    var userId = painel.dataset.userId;
    var csrf = painel.dataset.csrfToken;
    var estado = painel.querySelector("[data-whatsapp-state]");
    var terminal = { CONNECTED: true, ACTION_REQUIRED: true, CONFLICT: true, FAILED: true };
    var tentativas = 0;
    var maxTentativas = 100; // cinco minutos, em intervalos de três segundos

    function mostrar(conexao) {
      if (!conexao) {
        estado.innerHTML = "<p>Nenhuma linha conectada.</p><button type=\"button\" data-whatsapp-action=\"create\">Conectar WhatsApp</button>";
      } else if (conexao.status === "CONNECTED") {
        estado.innerHTML = "<p><strong>Conectado</strong></p><p>" + (conexao.display_phone_number || "Número aguardando atualização.") + "</p><p class=\"dica\">Linha pronta para uso.</p>";
      } else if (conexao.status === "ACTION_REQUIRED") {
        estado.innerHTML = "<p>A configuração precisa de uma ação adicional.</p><button type=\"button\" data-whatsapp-action=\"resume\">Retomar configuração</button>";
      } else if (conexao.status === "CONFLICT") {
        estado.innerHTML = "<p>Existe um conflito na configuração desta linha.</p><p class=\"dica\">Contate um administrador.</p>";
      } else if (conexao.status === "FAILED") {
        estado.innerHTML = "<p>Não foi possível concluir a conexão.</p><button type=\"button\" data-whatsapp-action=\"resume\">Tentar novamente</button>";
      } else {
        estado.innerHTML = "<p>Conexão em andamento...</p><p class=\"dica\">Esta página acompanha a configuração automaticamente.</p>";
      }
      ligarBotoes();
    }

    async function requisitar(method, sufixo) {
      var resposta = await fetch("/api/v1/representatives/" + userId + "/whatsapp-connection" + sufixo, {
        method: method, credentials: "same-origin", headers: { "X-CSRF-Token": csrf }
      });
      if (!resposta.ok) throw new Error("Não foi possível consultar a configuração.");
      return resposta.json();
    }

    async function atualizar() {
      try {
        var conexao = await requisitar("GET", "");
        mostrar(conexao);
        if (conexao && !terminal[conexao.status] && tentativas++ < maxTentativas) setTimeout(atualizar, 3000);
      } catch (_) {
        estado.innerHTML = "<p>Não foi possível consultar a configuração agora.</p><p class=\"dica\">Atualize a página ou tente novamente em alguns instantes.</p>";
      }
    }

    function ligarBotoes() {
      var botao = estado.querySelector("[data-whatsapp-action]");
      if (!botao) return;
      botao.addEventListener("click", async function () {
        botao.disabled = true;
        try {
          var conexao = await requisitar("POST", botao.dataset.whatsappAction === "resume" ? "/resume" : "");
          // Resume normalmente continua o provisioning no Gateway. Só uma
          // resposta que de fato pede interação Meta abre uma nova janela.
          if (conexao.launch_url) {
            window.open(conexao.launch_url, "whatsapp_onboarding", "width=700,height=760");
          }
          mostrar(conexao);
          tentativas = 0;
          if (!terminal[conexao.status]) setTimeout(atualizar, 3000);
        } catch (_) {
          botao.disabled = false;
          estado.insertAdjacentHTML("beforeend", "<p class=\"aviso erro\">Não foi possível iniciar a configuração.</p>");
        }
      });
    }
    ligarBotoes();
    if (estado.textContent.indexOf("andamento") !== -1) setTimeout(atualizar, 3000);
  }
  ligarWhatsappBusiness();
})();
