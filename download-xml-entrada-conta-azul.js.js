(async () => {
  const INICIO = { ano: 2025, mes: 2 }; // fevereiro/2025
  const FIM = { ano: 2026, mes: 5 };    // maio/2026

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  const mesesPorNome = {
    janeiro: 1,
    fevereiro: 2,
    março: 3,
    marco: 3,
    abril: 4,
    maio: 5,
    junho: 6,
    julho: 7,
    agosto: 8,
    setembro: 9,
    outubro: 10,
    novembro: 11,
    dezembro: 12
  };

  const regexMes = /(janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})/i;
  const chave = p => p.ano * 12 + p.mes;

  const isVisible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== "none" && s.visibility !== "hidden";
  };

  const exigirAbaAtiva = () => {
    if (document.visibilityState !== "visible") {
      throw new Error("A aba perdeu foco. Deixe o Conta Azul aberto e visível enquanto o script roda.");
    }
  };

  const clickSeguro = async el => {
    exigirAbaAtiva();

    el.scrollIntoView({ block: "center" });
    await sleep(300);

    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;

    ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(type => {
      el.dispatchEvent(new MouseEvent(type, {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: x,
        clientY: y
      }));
    });
  };

  const fecharMenus = async () => {
    for (let i = 0; i < 3; i++) {
      document.dispatchEvent(new KeyboardEvent("keydown", {
        key: "Escape",
        code: "Escape",
        keyCode: 27,
        which: 27,
        bubbles: true
      }));

      document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
      document.body.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }));

      await sleep(400);

      const menusAbertos = [...document.querySelectorAll(".ds-dropdown-item")].filter(isVisible);

      if (menusAbertos.length === 0) return;
    }
  };

  const getFiltroPeriodo = () => {
    const filtro = [...document.querySelectorAll(".ds-date-filter")]
      .find(el => isVisible(el) && regexMes.test(el.innerText || ""));

    if (!filtro) {
      throw new Error("Não encontrei o filtro de período.");
    }

    return filtro;
  };

  const getPeriodoAtual = () => {
    const filtro = getFiltroPeriodo();
    const texto = filtro.innerText.replace(/\s+/g, " ");
    const match = texto.match(regexMes);

    if (!match) {
      throw new Error("Não consegui ler o mês atual.");
    }

    return {
      texto: match[0],
      mes: mesesPorNome[match[1].toLowerCase()],
      ano: Number(match[2])
    };
  };

  const esperarXMLVisivel = async () => {
    for (let i = 0; i < 25; i++) {
      await sleep(150);

      const xml = [...document.querySelectorAll(".ds-dropdown-item")]
        .filter(isVisible)
        .find(el => el.textContent.trim() === "XML");

      if (xml) return xml;
    }

    return null;
  };

  const baixarXMLsDoMesAtual = async () => {
    exigirAbaAtiva();
    await fecharMenus();

    const atual = getPeriodoAtual();

    const itens = [...document.querySelectorAll("tbody tr")]
      .map(linha => ({
        linha,
        botao: [...linha.querySelectorAll("button")]
          .find(btn => btn.querySelector('svg[data-icon="arrow-down-to-line"]'))
      }))
      .filter(x => x.botao);

    console.log(`===== ${atual.texto} | XMLs encontrados: ${itens.length} =====`);

    for (let i = 0; i < itens.length; i++) {
      exigirAbaAtiva();

      const { linha, botao } = itens[i];

      await fecharMenus();
      await clickSeguro(botao);

      const xml = await esperarXMLVisivel();

      if (!xml) {
        console.warn("XML não encontrado nesta linha:", linha.innerText);
        continue;
      }

      await clickSeguro(xml);

      console.log(`XML ${i + 1}/${itens.length}: ${linha.innerText.replace(/\n/g, " | ")}`);
      await sleep(3800);
    }

    await fecharMenus();
  };

  const clicarProximoMes = async () => {
    await fecharMenus();
    window.scrollTo(0, 0);
    await sleep(900);

    const antes = getPeriodoAtual();

    for (let tentativa = 1; tentativa <= 4; tentativa++) {
      exigirAbaAtiva();

      await fecharMenus();
      window.scrollTo(0, 0);
      await sleep(700);

      const filtro = getFiltroPeriodo();

      const btnProximo =
        filtro.querySelector("button.ds-date-filter__button--next") ||
        [...filtro.querySelectorAll("button")]
          .find(btn => btn.querySelector('svg[data-icon="angle-right"]'));

      if (!btnProximo) {
        throw new Error("Não encontrei o botão de próximo mês.");
      }

      console.log(`Tentando avançar mês: ${antes.texto}. Tentativa ${tentativa}/4`);
      await clickSeguro(btnProximo);

      for (let i = 0; i < 30; i++) {
        await sleep(300);

        const depois = getPeriodoAtual();

        if (chave(depois) !== chave(antes)) {
          console.log(`Mês alterado: ${antes.texto} -> ${depois.texto}`);
          await sleep(3000);
          return depois;
        }
      }
    }

    throw new Error(`Não consegui avançar o mês após 4 tentativas. Ainda está em ${antes.texto}.`);
  };

  const prepararInicio = async () => {
    let atual = getPeriodoAtual();

    if (chave(atual) === chave(INICIO)) {
      console.log(`Já está em ${atual.texto}. Iniciando extração.`);
      return;
    }

    if (chave(atual) === chave({ ano: 2025, mes: 1 })) {
      console.log("Janeiro/2025 já foi baixado. Indo para Fevereiro/2025...");
      atual = await clicarProximoMes();
    }

    if (chave(atual) !== chave(INICIO)) {
      throw new Error(`A tela precisa estar em Janeiro/2025 ou Fevereiro/2025. Agora está em ${atual.texto}.`);
    }
  };

  console.log("Iniciando continuação: Fevereiro/2025 até Maio/2026.");
  console.log("Não saia desta aba. Deixe zoom em 100% e não mexa no mouse/teclado.");

  await prepararInicio();

  while (chave(getPeriodoAtual()) <= chave(FIM)) {
    const atualAntesDeBaixar = getPeriodoAtual();

    await baixarXMLsDoMesAtual();

    if (chave(atualAntesDeBaixar) === chave(FIM)) {
      break;
    }

    await clicarProximoMes();
  }

  console.log("Finalizado: Fevereiro/2025 até Maio/2026.");
})();
