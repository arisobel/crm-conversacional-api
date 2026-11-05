(function () {
  "use strict";

  var storageKey = "crm-theme";

  function temaInicial() {
    var salvo = localStorage.getItem(storageKey);
    if (salvo === "dark" || salvo === "light") {
      return salvo;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function aplicarTema(tema) {
    document.documentElement.dataset.theme = tema;
    document.documentElement.style.colorScheme = tema;
  }

  aplicarTema(temaInicial());

  window.addEventListener("DOMContentLoaded", function () {
    var botao = document.getElementById("tema-toggle");
    if (!botao) {
      return;
    }

    function atualizarRotulo() {
      var escuro = document.documentElement.dataset.theme === "dark";
      var rotulo = escuro ? "Ativar modo claro" : "Ativar modo escuro";
      botao.setAttribute("aria-label", rotulo);
      botao.setAttribute("title", rotulo);
      botao.setAttribute("aria-pressed", String(escuro));
    }

    atualizarRotulo();
    botao.addEventListener("click", function () {
      var proximo = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      localStorage.setItem(storageKey, proximo);
      aplicarTema(proximo);
      atualizarRotulo();
    });
  });
})();
