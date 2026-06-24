"""Extrai dados de NF-e (modelo 55) de compras para CSVs normalizados e
move copias renomeadas dos XMLs para xml_renomeados/AAAA/MM/.

NAO altera os arquivos XML originais. NAO acessa banco de dados.

Uso:
    python scripts/processar_nfe.py

Saidas:
    output/csv/*.csv          -> tabelas normalizadas + master flat
    output/manifest_renomeacao.csv
    output/relatorio_qualidade.csv
    xml_renomeados/AAAA/MM/*.xml  -> copias renomeadas
"""

import csv
import os
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "output")
CSV_DIR = os.path.join(OUT_DIR, "csv")
RENAMED_DIR = os.path.join(BASE_DIR, "xml_renomeados")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def txt(elem, path, default=""):
    """Retorna texto de um sub-elemento ou default."""
    if elem is None:
        return default
    found = elem.findtext(path, default=default, namespaces=NS)
    return found if found is not None else default


def to_float(value, default=0.0):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def parse_date(value):
    """Aceita 'YYYY-MM-DD' ou 'YYYY-MM-DDThh:mm:ss-03:00'. Retorna date ou None."""
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def slugify(text, max_len=30):
    """Razao social -> SLUG sem acentos, MAIUSCULAS, espacos -> '-'."""
    if not text:
        return "SEM-NOME"
    nfkd = unicodedata.normalize("NFKD", text)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    sem_acento = sem_acento.upper()
    sem_acento = re.sub(r"[^A-Z0-9]+", "-", sem_acento)
    sem_acento = sem_acento.strip("-")
    return sem_acento[:max_len].strip("-") or "SEM-NOME"


def safe_filename(name):
    """Remove caracteres invalidos para nome de arquivo no Windows."""
    return re.sub(r'[<>:"/\\|?*]', "_", name)


# ----------------------------------------------------------------------------
# Extracao por NF
# ----------------------------------------------------------------------------
def extrair_nfe(xml_path):
    """Faz parse de um XML e retorna um dicionario com todas as entidades.

    Retorna None se o XML nao tiver infNFe.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    inf = root.find(".//nfe:infNFe", NS)
    if inf is None:
        return None

    chave = (inf.get("Id") or "").replace("NFe", "")

    ide = inf.find("nfe:ide", NS)
    emit = inf.find("nfe:emit", NS)
    dest = inf.find("nfe:dest", NS)
    total_icms = inf.find("nfe:total/nfe:ICMSTot", NS)
    total_ibs = inf.find("nfe:total/nfe:IBSCBSTot", NS)
    transp = inf.find("nfe:transp", NS)
    cobr = inf.find("nfe:cobr", NS)
    pag = inf.find("nfe:pag", NS)
    infadic = inf.find("nfe:infAdic", NS)
    protnfe = root.find(".//nfe:protNFe/nfe:infProt", NS)

    # --- ide ---
    numero_nf = txt(ide, "nfe:nNF")
    serie = txt(ide, "nfe:serie")
    data_emissao = parse_date(txt(ide, "nfe:dhEmi"))
    data_saida = parse_date(txt(ide, "nfe:dhSaiEnt"))
    nat_op = txt(ide, "nfe:natOp")
    fin_nfe = txt(ide, "nfe:finNFe")

    # --- emit (fornecedor) ---
    cnpj_forn = txt(emit, "nfe:CNPJ") or txt(emit, "nfe:CPF")
    forn = {
        "cnpj_cpf": cnpj_forn,
        "razao_social": txt(emit, "nfe:xNome"),
        "nome_fantasia": txt(emit, "nfe:xFant"),
        "uf": txt(emit, "nfe:enderEmit/nfe:UF"),
        "municipio": txt(emit, "nfe:enderEmit/nfe:xMun"),
        "ie": txt(emit, "nfe:IE"),
        "crt": txt(emit, "nfe:CRT"),
        "email": txt(emit, "nfe:email"),
        "fone": txt(emit, "nfe:enderEmit/nfe:fone"),
    }

    uf_emit = forn["uf"]
    uf_dest = txt(dest, "nfe:enderDest/nfe:UF")
    flag_interestadual = 1 if (uf_emit and uf_dest and uf_emit != uf_dest) else 0

    # --- itens ---
    itens = []
    cfop_por_valor = defaultdict(float)
    for det in inf.findall("nfe:det", NS):
        nitem = det.get("nItem", "")
        prod = det.find("nfe:prod", NS)
        imposto = det.find("nfe:imposto", NS)

        cfop = txt(prod, "nfe:CFOP")
        v_prod = to_float(txt(prod, "nfe:vProd"))
        q_com = to_float(txt(prod, "nfe:qCom"))
        cfop_por_valor[cfop] += v_prod

        # impostos do item
        cst_icms = ""
        v_icms = 0.0
        icms = imposto.find("nfe:ICMS", NS) if imposto is not None else None
        if icms is not None and len(icms):
            icms_grp = icms[0]  # ICMS00, ICMS60, etc.
            cst_icms = txt(icms_grp, "nfe:CST") or txt(icms_grp, "nfe:CSOSN")
            v_icms = to_float(txt(icms_grp, "nfe:vICMS"))
        v_pis = 0.0
        pis = imposto.find("nfe:PIS", NS) if imposto is not None else None
        if pis is not None and len(pis):
            v_pis = to_float(txt(pis[0], "nfe:vPIS"))
        v_cofins = 0.0
        cofins = imposto.find("nfe:COFINS", NS) if imposto is not None else None
        if cofins is not None and len(cofins):
            v_cofins = to_float(txt(cofins[0], "nfe:vCOFINS"))

        preco_unit_calc = round(v_prod / q_com, 6) if q_com else 0.0

        itens.append(
            {
                "chave_nfe": chave,
                "nItem": nitem,
                "cnpj_fornecedor": cnpj_forn,
                "codigo_produto_fornecedor": txt(prod, "nfe:cProd"),
                "descricao": txt(prod, "nfe:xProd"),
                "ncm": txt(prod, "nfe:NCM"),
                "cfop": cfop,
                "unidade": txt(prod, "nfe:uCom"),
                "quantidade": q_com,
                "valor_unitario": to_float(txt(prod, "nfe:vUnCom")),
                "valor_total": v_prod,
                "cst_icms": cst_icms,
                "valor_icms": v_icms,
                "valor_pis": v_pis,
                "valor_cofins": v_cofins,
                "preco_unitario_calc": preco_unit_calc,
            }
        )

    cfop_predominante = (
        max(cfop_por_valor.items(), key=lambda kv: kv[1])[0] if cfop_por_valor else ""
    )

    # --- totais / impostos NF ---
    impostos_nf = {
        "chave_nfe": chave,
        "vBC": to_float(txt(total_icms, "nfe:vBC")),
        "vICMS": to_float(txt(total_icms, "nfe:vICMS")),
        "vICMSDeson": to_float(txt(total_icms, "nfe:vICMSDeson")),
        "vST": to_float(txt(total_icms, "nfe:vST")),
        "vIPI": to_float(txt(total_icms, "nfe:vIPI")),
        "vPIS": to_float(txt(total_icms, "nfe:vPIS")),
        "vCOFINS": to_float(txt(total_icms, "nfe:vCOFINS")),
        "vOutro": to_float(txt(total_icms, "nfe:vOutro")),
        "vFrete": to_float(txt(total_icms, "nfe:vFrete")),
        "vSeg": to_float(txt(total_icms, "nfe:vSeg")),
        "vDesc": to_float(txt(total_icms, "nfe:vDesc")),
        "vNF": to_float(txt(total_icms, "nfe:vNF")),
        "vTotTrib": to_float(txt(total_icms, "nfe:vTotTrib")),
        "vBCIBSCBS": to_float(txt(total_ibs, "nfe:vBCIBSCBS")),
        "vIBS": to_float(txt(total_ibs, "nfe:gIBS/nfe:vIBS")),
        "vCBS": to_float(txt(total_ibs, "nfe:gCBS/nfe:vCBS")),
    }

    valor_produtos = to_float(txt(total_icms, "nfe:vProd"))
    valor_frete = impostos_nf["vFrete"]
    valor_desconto = impostos_nf["vDesc"]
    valor_nf = impostos_nf["vNF"]

    # --- transporte ---
    mod_frete = txt(transp, "nfe:modFrete")
    transportadora = None
    cnpj_transp = ""
    vol = transp.find("nfe:vol", NS) if transp is not None else None
    transporta = transp.find("nfe:transporta", NS) if transp is not None else None
    if transporta is not None:
        cnpj_transp = txt(transporta, "nfe:CNPJ") or txt(transporta, "nfe:CPF")
        transportadora = {
            "cnpj_cpf": cnpj_transp,
            "nome": txt(transporta, "nfe:xNome"),
            "uf": txt(transporta, "nfe:UF"),
        }
    peso_liquido = to_float(txt(vol, "nfe:pesoL")) if vol is not None else 0.0
    peso_bruto = to_float(txt(vol, "nfe:pesoB")) if vol is not None else 0.0
    qtd_volumes = txt(vol, "nfe:qVol") if vol is not None else ""

    # --- parcelas (cobr/dup) ---
    parcelas = []
    if cobr is not None:
        for dup in cobr.findall("nfe:dup", NS):
            dvenc = parse_date(txt(dup, "nfe:dVenc"))
            prazo_dias = (dvenc - data_emissao).days if (dvenc and data_emissao) else ""
            parcelas.append(
                {
                    "chave_nfe": chave,
                    "numero_duplicata": txt(dup, "nfe:nDup"),
                    "data_vencimento": dvenc.isoformat() if dvenc else "",
                    "valor": to_float(txt(dup, "nfe:vDup")),
                    "prazo_dias": prazo_dias,
                }
            )

    # prazo medio ponderado por valor
    prazo_medio = ""
    soma_val = sum(p["valor"] for p in parcelas if isinstance(p["prazo_dias"], int))
    if soma_val > 0:
        acumulado = sum(
            p["valor"] * p["prazo_dias"]
            for p in parcelas
            if isinstance(p["prazo_dias"], int)
        )
        prazo_medio = round(acumulado / soma_val, 1)

    # --- pagamento ---
    forma_pagto = ""
    if pag is not None:
        detpag = pag.find("nfe:detPag", NS)
        if detpag is not None:
            forma_pagto = txt(detpag, "nfe:tPag")

    # --- info adicional ---
    info_cpl = txt(infadic, "nfe:infCpl") or txt(infadic, "nfe:infAdFisco")

    # --- protocolo ---
    status_sefaz = txt(protnfe, "nfe:cStat")
    motivo_sefaz = txt(protnfe, "nfe:xMotivo")

    compra = {
        "chave_nfe": chave,
        "numero_nf": numero_nf,
        "serie": serie,
        "data_emissao": data_emissao.isoformat() if data_emissao else "",
        "data_saida_entrada": data_saida.isoformat() if data_saida else "",
        "cnpj_fornecedor": cnpj_forn,
        "nome_fornecedor": forn["razao_social"],
        "uf_fornecedor": uf_emit,
        "valor_produtos": valor_produtos,
        "valor_frete": valor_frete,
        "valor_desconto": valor_desconto,
        "valor_nf": valor_nf,
        "nat_operacao": nat_op,
        "cfop_predominante": cfop_predominante,
        "mod_frete": mod_frete,
        "cnpj_transportadora": cnpj_transp,
        "peso_liquido": peso_liquido,
        "peso_bruto": peso_bruto,
        "qtd_volumes": qtd_volumes,
        "status_sefaz": status_sefaz,
        "qtd_itens": len(itens),
        "qtd_parcelas": len(parcelas),
        "prazo_medio_dias": prazo_medio,
        "forma_pagamento": forma_pagto,
        "flag_interestadual": flag_interestadual,
        "finNFe": fin_nfe,
        "ano": data_emissao.year if data_emissao else "",
        "mes_ano": data_emissao.strftime("%Y-%m") if data_emissao else "",
        "trimestre": f"{data_emissao.year}-T{(data_emissao.month - 1) // 3 + 1}"
        if data_emissao
        else "",
        "info_complementar": info_cpl,
        "motivo_sefaz": motivo_sefaz,
    }

    return {
        "chave": chave,
        "data_emissao": data_emissao,
        "compra": compra,
        "fornecedor": forn,
        "transportadora": transportadora,
        "itens": itens,
        "parcelas": parcelas,
        "impostos_nf": impostos_nf,
        "valor_nf": valor_nf,
        "numero_nf": numero_nf,
        "serie": serie,
    }


# ----------------------------------------------------------------------------
# Escrita de CSV
# ----------------------------------------------------------------------------
def write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    xml_files = sorted(f for f in os.listdir(BASE_DIR) if f.lower().endswith(".xml"))
    print(f"Encontrados {len(xml_files)} XMLs em {BASE_DIR}")

    fornecedores = {}
    transportadoras = {}
    produtos = {}
    compras = []
    itens_all = []
    parcelas_all = []
    impostos_all = []
    master_rows = []
    manifest = []
    qualidade = []

    chaves_vistas = {}

    for fn in xml_files:
        xml_path = os.path.join(BASE_DIR, fn)
        try:
            data = extrair_nfe(xml_path)
        except Exception as exc:  # noqa: BLE001
            qualidade.append(
                {
                    "arquivo": fn,
                    "chave_nfe": "",
                    "tipo_alerta": "ERRO_PARSE",
                    "detalhe": str(exc),
                }
            )
            continue

        if data is None:
            qualidade.append(
                {
                    "arquivo": fn,
                    "chave_nfe": "",
                    "tipo_alerta": "SEM_INFNFE",
                    "detalhe": "infNFe nao encontrado",
                }
            )
            continue

        chave = data["chave"]

        # duplicata de chave
        if chave in chaves_vistas:
            qualidade.append(
                {
                    "arquivo": fn,
                    "chave_nfe": chave,
                    "tipo_alerta": "CHAVE_DUPLICADA",
                    "detalhe": f"Ja processada em {chaves_vistas[chave]}",
                }
            )
            continue
        chaves_vistas[chave] = fn

        # nome novo do arquivo
        forn = data["fornecedor"]
        slug = slugify(forn["razao_social"])
        valor_nf = data["valor_nf"]
        data_emi = data["data_emissao"]
        data_str = data_emi.isoformat() if data_emi else "0000-00-00"
        ano = data_emi.strftime("%Y") if data_emi else "0000"
        mes = data_emi.strftime("%m") if data_emi else "00"
        novo_nome = safe_filename(
            f"{data_str}_NF{data['numero_nf']}-S{data['serie']}_{slug}_R{valor_nf:.2f}_CH{chave}.xml"
        )
        destino_rel = os.path.join("xml_renomeados", ano, mes, novo_nome)
        data["compra"]["arquivo_xml_novo"] = destino_rel.replace("\\", "/")

        manifest.append(
            {
                "arquivo_original": fn,
                "arquivo_novo": novo_nome,
                "pasta_destino": f"{ano}/{mes}",
                "chave_nfe": chave,
                "numero_nf": data["numero_nf"],
                "data_emissao": data_str,
                "fornecedor": forn["razao_social"],
                "valor_nf": f"{valor_nf:.2f}",
            }
        )

        # entidades dedupe
        if forn["cnpj_cpf"] and forn["cnpj_cpf"] not in fornecedores:
            fornecedores[forn["cnpj_cpf"]] = forn
        transp = data["transportadora"]
        if transp and transp["cnpj_cpf"] and transp["cnpj_cpf"] not in transportadoras:
            transportadoras[transp["cnpj_cpf"]] = transp

        # produtos (chave = cnpj_fornecedor + codigo)
        for item in data["itens"]:
            pk = (item["cnpj_fornecedor"], item["codigo_produto_fornecedor"])
            if pk not in produtos:
                produtos[pk] = {
                    "cnpj_fornecedor": item["cnpj_fornecedor"],
                    "codigo_produto_fornecedor": item["codigo_produto_fornecedor"],
                    "descricao": item["descricao"],
                    "ncm": item["ncm"],
                    "unidade_padrao": item["unidade"],
                    "qtd_compras": 0,
                    "primeira_compra": data_str,
                    "ultima_compra": data_str,
                }
            p = produtos[pk]
            p["qtd_compras"] += 1
            if data_str < p["primeira_compra"]:
                p["primeira_compra"] = data_str
            if data_str > p["ultima_compra"]:
                p["ultima_compra"] = data_str

        compras.append(data["compra"])
        itens_all.extend(data["itens"])
        parcelas_all.extend(data["parcelas"])
        impostos_all.append(data["impostos_nf"])

        # master flat (1 linha por item)
        c = data["compra"]
        for item in data["itens"]:
            row = {
                "chave_nfe": chave,
                "numero_nf": c["numero_nf"],
                "serie": c["serie"],
                "data_emissao": c["data_emissao"],
                "ano": c["ano"],
                "mes_ano": c["mes_ano"],
                "trimestre": c["trimestre"],
                "cnpj_fornecedor": c["cnpj_fornecedor"],
                "nome_fornecedor": c["nome_fornecedor"],
                "uf_fornecedor": c["uf_fornecedor"],
                "flag_interestadual": c["flag_interestadual"],
                "nat_operacao": c["nat_operacao"],
                "nItem": item["nItem"],
                "codigo_produto_fornecedor": item["codigo_produto_fornecedor"],
                "descricao": item["descricao"],
                "ncm": item["ncm"],
                "cfop": item["cfop"],
                "unidade": item["unidade"],
                "quantidade": item["quantidade"],
                "valor_unitario": item["valor_unitario"],
                "preco_unitario_calc": item["preco_unitario_calc"],
                "valor_total_item": item["valor_total"],
                "cst_icms": item["cst_icms"],
                "valor_icms_item": item["valor_icms"],
                "valor_pis_item": item["valor_pis"],
                "valor_cofins_item": item["valor_cofins"],
                "valor_produtos_nf": c["valor_produtos"],
                "valor_frete_nf": c["valor_frete"],
                "valor_desconto_nf": c["valor_desconto"],
                "valor_nf": c["valor_nf"],
                "mod_frete": c["mod_frete"],
                "cnpj_transportadora": c["cnpj_transportadora"],
                "peso_liquido": c["peso_liquido"],
                "peso_bruto": c["peso_bruto"],
                "qtd_volumes": c["qtd_volumes"],
                "qtd_parcelas": c["qtd_parcelas"],
                "prazo_medio_dias": c["prazo_medio_dias"],
                "forma_pagamento": c["forma_pagamento"],
                "status_sefaz": c["status_sefaz"],
                "finNFe": c["finNFe"],
                "arquivo_xml_novo": c["arquivo_xml_novo"],
            }
            master_rows.append(row)

        # --- regras de qualidade ---
        if not data["parcelas"]:
            qualidade.append(
                {
                    "arquivo": fn,
                    "chave_nfe": chave,
                    "tipo_alerta": "SEM_PARCELAS",
                    "detalhe": f"forma_pagamento(tPag)={c['forma_pagamento']}",
                }
            )
        if c["finNFe"] == "4":
            qualidade.append(
                {
                    "arquivo": fn,
                    "chave_nfe": chave,
                    "tipo_alerta": "NF_AJUSTE",
                    "detalhe": "finNFe=4 (NF-e de ajuste)",
                }
            )
        # divergencia soma itens vs vProd
        soma_itens = round(sum(i["valor_total"] for i in data["itens"]), 2)
        if abs(soma_itens - round(c["valor_produtos"], 2)) > 0.05:
            qualidade.append(
                {
                    "arquivo": fn,
                    "chave_nfe": chave,
                    "tipo_alerta": "DIVERGENCIA_VPROD",
                    "detalhe": f"soma_itens={soma_itens} vs vProd={c['valor_produtos']}",
                }
            )

    print(f"NFs processadas: {len(compras)}")

    # ------------------------------------------------------------------
    # Gravacao dos CSVs
    # ------------------------------------------------------------------
    write_csv(
        os.path.join(CSV_DIR, "fornecedores.csv"),
        ["cnpj_cpf", "razao_social", "nome_fantasia", "uf", "municipio", "ie", "crt", "email", "fone"],
        sorted(fornecedores.values(), key=lambda x: x["razao_social"]),
    )

    write_csv(
        os.path.join(CSV_DIR, "transportadoras.csv"),
        ["cnpj_cpf", "nome", "uf"],
        sorted(transportadoras.values(), key=lambda x: x["nome"]),
    )

    write_csv(
        os.path.join(CSV_DIR, "produtos.csv"),
        [
            "cnpj_fornecedor",
            "codigo_produto_fornecedor",
            "descricao",
            "ncm",
            "unidade_padrao",
            "qtd_compras",
            "primeira_compra",
            "ultima_compra",
        ],
        sorted(produtos.values(), key=lambda x: (x["cnpj_fornecedor"], x["codigo_produto_fornecedor"])),
    )

    write_csv(
        os.path.join(CSV_DIR, "compras.csv"),
        [
            "chave_nfe", "numero_nf", "serie", "data_emissao", "data_saida_entrada",
            "cnpj_fornecedor", "nome_fornecedor", "uf_fornecedor", "valor_produtos",
            "valor_frete", "valor_desconto", "valor_nf", "nat_operacao",
            "cfop_predominante", "mod_frete", "cnpj_transportadora", "peso_liquido",
            "peso_bruto", "qtd_volumes", "status_sefaz", "qtd_itens", "qtd_parcelas",
            "prazo_medio_dias", "forma_pagamento", "flag_interestadual", "finNFe",
            "ano", "mes_ano", "trimestre", "info_complementar", "motivo_sefaz",
            "arquivo_xml_novo",
        ],
        compras,
    )

    write_csv(
        os.path.join(CSV_DIR, "compra_itens.csv"),
        [
            "chave_nfe", "nItem", "cnpj_fornecedor", "codigo_produto_fornecedor",
            "descricao", "ncm", "cfop", "unidade", "quantidade", "valor_unitario",
            "valor_total", "cst_icms", "valor_icms", "valor_pis", "valor_cofins",
            "preco_unitario_calc",
        ],
        itens_all,
    )

    write_csv(
        os.path.join(CSV_DIR, "compra_parcelas.csv"),
        ["chave_nfe", "numero_duplicata", "data_vencimento", "valor", "prazo_dias"],
        parcelas_all,
    )

    write_csv(
        os.path.join(CSV_DIR, "compra_impostos_nf.csv"),
        [
            "chave_nfe", "vBC", "vICMS", "vICMSDeson", "vST", "vIPI", "vPIS",
            "vCOFINS", "vOutro", "vFrete", "vSeg", "vDesc", "vNF", "vTotTrib",
            "vBCIBSCBS", "vIBS", "vCBS",
        ],
        impostos_all,
    )

    write_csv(
        os.path.join(CSV_DIR, "master_compras_flat.csv"),
        [
            "chave_nfe", "numero_nf", "serie", "data_emissao", "ano", "mes_ano",
            "trimestre", "cnpj_fornecedor", "nome_fornecedor", "uf_fornecedor",
            "flag_interestadual", "nat_operacao", "nItem",
            "codigo_produto_fornecedor", "descricao", "ncm", "cfop", "unidade",
            "quantidade", "valor_unitario", "preco_unitario_calc",
            "valor_total_item", "cst_icms", "valor_icms_item", "valor_pis_item",
            "valor_cofins_item", "valor_produtos_nf", "valor_frete_nf",
            "valor_desconto_nf", "valor_nf", "mod_frete", "cnpj_transportadora",
            "peso_liquido", "peso_bruto", "qtd_volumes", "qtd_parcelas",
            "prazo_medio_dias", "forma_pagamento", "status_sefaz", "finNFe",
            "arquivo_xml_novo",
        ],
        master_rows,
    )

    write_csv(
        os.path.join(OUT_DIR, "manifest_renomeacao.csv"),
        [
            "arquivo_original", "arquivo_novo", "pasta_destino", "chave_nfe",
            "numero_nf", "data_emissao", "fornecedor", "valor_nf",
        ],
        manifest,
    )

    write_csv(
        os.path.join(OUT_DIR, "relatorio_qualidade.csv"),
        ["arquivo", "chave_nfe", "tipo_alerta", "detalhe"],
        qualidade,
    )

    # ------------------------------------------------------------------
    # Copiar e renomear XMLs
    # ------------------------------------------------------------------
    copiados = 0
    for m in manifest:
        origem = os.path.join(BASE_DIR, m["arquivo_original"])
        ano, mes = m["pasta_destino"].split("/")
        dest_dir = os.path.join(RENAMED_DIR, ano, mes)
        os.makedirs(dest_dir, exist_ok=True)
        destino = os.path.join(dest_dir, m["arquivo_novo"])
        # colisao improvavel (chave garante unicidade) -> sufixo _v2
        if os.path.exists(destino):
            base, ext = os.path.splitext(destino)
            destino = base + "_v2" + ext
        shutil.copy2(origem, destino)
        copiados += 1

    print(f"XMLs copiados/renomeados: {copiados}")

    # ------------------------------------------------------------------
    # Resumo
    # ------------------------------------------------------------------
    total_valor = sum(c["valor_nf"] for c in compras)
    print("\n=== RESUMO ===")
    print(f"Fornecedores: {len(fornecedores)}")
    print(f"Transportadoras: {len(transportadoras)}")
    print(f"Produtos: {len(produtos)}")
    print(f"Compras (NFs): {len(compras)}")
    print(f"Itens: {len(itens_all)}")
    print(f"Parcelas: {len(parcelas_all)}")
    print(f"Valor total: R$ {total_valor:,.2f}")
    print(f"Alertas de qualidade: {len(qualidade)}")
    print(f"\nCSVs em: {CSV_DIR}")
    print(f"XMLs renomeados em: {RENAMED_DIR}")


if __name__ == "__main__":
    main()
