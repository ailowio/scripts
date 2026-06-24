(async () => {
  const INICIO = { ano: 2024, mes: 11 }; // novembro/2024
  const FIM = { ano: 2026, mes: 5 };     // maio/2026

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

  const nomeMes = {
    1: "janeiro",
    2: "fevereiro",
    3: "março",
    4: "abril",
    5: "maio",
    6: "junho",
    7: "julho",
    8: "agosto",
    9: "setembro",
    10: "outubro",
    11: "novembro",
    12: "dezembro"
  };

  const regexMes = /(janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})/i;
  const chave = p => p.ano * 12 + p.mes;

  const exigirAbaAtiva = () => {
    if (document.visibilityState !== "visible") {
      throw new Error("A aba perdeu foco. Deixe o Conta Azul aberto e visível enquanto o script roda.");
    }
  };

  const isVisible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== "none" && s.visibility !== "hidden";
  };

  const clickSeguro = async el => {
    exigirAbaAtiva();

    el.scrollIntoView({ block: "center" });
    await sleep(250);

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

    el.click();
  };

  const fecharMenus = async () => {
    document.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Escape",
      code: "Escape",
      keyCode: 27,
      which: 27,
      bubbles: true
    }));
    await sleep(400);
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
      throw new Error("Não consegui ler o mês atual no filtro de período.");
    }

    return {
      texto: match[0],
      mes: mesesPorNome[match[1].toLowerCase()],
      ano: Number(match[2])
    };
  };

  const esperarMesMudar = async antes => {
    for (let i = 0; i < 50; i++) {
      exigirAbaAtiva();
      await sleep(300);

      const depois = getPeriodoAtual();

      if (chave(depois) !== chave(antes)) {
        console.log(`Mês alterado: ${antes.texto} -> ${depois.texto}`);
        await sleep(2500);
        return depois;
      }
    }

    throw new Error(`Cliquei no próximo mês, mas a tela continuou em ${antes.texto}.`);
  };

  const clicarProximoMes = async () => {
    await fecharMenus();
    window.scrollTo(0, 0);
    await sleep(700);

    const antes = getPeriodoAtual();

    for (let tentativa = 1; tentativa <= 3; tentativa++) {
      exigirAbaAtiva();

      const filtro = getFiltroPeriodo();

      const btnProximo =
        filtro.querySelector("button.ds-date-filter__button--next") ||
        [...filtro.querySelectorAll("button")]
          .find(btn => btn.querySelector('svg[data-icon="angle-right"]'));

      if (!btnProximo) {
        throw new Error("Não encontrei o botão de próximo mês.");
      }

      console.log(`Tentando avançar mês. Tentativa ${tentativa}/3...`);
      await clickSeguro(btnProximo);

      try {
        return await esperarMesMudar(antes);
      } catch (e) {
        if (tentativa === 3) throw e;
        await sleep(1200);
      }
    }
  };

  const baixarXMLsDoMesAtual = async () => {
    exigirAbaAtiva();
    await fecharMenus();

    const atual = getPeriodoAtual();

    const itens = [...document.querySelectorAll("tbody tr")]
      .map(linha => ({
        chaveLinha: linha.innerText.replace(/\s+/g, " ").trim(),
        linha,
        botao: [...linha.querySelectorAll("button")]
          .find(btn => btn.querySelector('svg[data-icon="arrow-down-to-line"]'))
      }))
      .filter(x => x.botao);

    const jaProcessadas = new Set();

    console.log(`===== ${atual.texto} | XMLs encontrados: ${itens.length} =====`);

    for (let i = 0; i < itens.length; i++) {
      exigirAbaAtiva();

      const { linha, botao, chaveLinha } = itens[i];

      if (jaProcessadas.has(chaveLinha)) {
        console.warn("Linha duplicada ignorada:", chaveLinha);
        continue;
      }

      jaProcessadas.add(chaveLinha);

      await fecharMenus();
      await clickSeguro(botao);
      await sleep(1000);

      const xml = [...document.querySelectorAll(".ds-dropdown-item")]
        .filter(isVisible)
        .find(el => el.textContent.trim() === "XML");

      if (!xml) {
        console.warn("XML não encontrado nesta linha:", linha.innerText);
        continue;
      }

      await clickSeguro(xml);

      console.log(`XML ${i + 1}/${itens.length}: ${linha.innerText.replace(/\n/g, " | ")}`);
      await sleep(3200);
    }
  };

  const irParaNovembroSeEstiverEmOutubro = async () => {
    const atual = getPeriodoAtual();

    if (atual.ano === 2024 && atual.mes === 10) {
      console.log("Outubro/2024 já foi finalizado. Indo para novembro/2024...");
      await clicarProximoMes();
    }

    const novoAtual = getPeriodoAtual();

    if (chave(novoAtual) !== chave(INICIO)) {
      throw new Error(`A tela precisa estar em novembro/2024. Agora está em ${novoAtual.texto}.`);
    }
  };

  console.log("Iniciando. Não saia desta aba até finalizar.");
  await irParaNovembroSeEstiverEmOutubro();

  while (chave(getPeriodoAtual()) <= chave(FIM)) {
    const atual = getPeriodoAtual();

    await baixarXMLsDoMesAtual();

    if (chave(atual) === chave(FIM)) {
      break;
    }

    await clicarProximoMes();
  }

  console.log("Finalizado: novembro/2024 até maio/2026.");
})();
