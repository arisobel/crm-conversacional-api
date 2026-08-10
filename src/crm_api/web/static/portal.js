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
})();
