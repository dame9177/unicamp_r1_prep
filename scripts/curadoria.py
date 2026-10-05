"""Curadoria inicial com o Claude (roda uma vez; retomável).

  uv run --project backend python scripts/curadoria.py temas            # temas + classificação (1 chamada por área)
  uv run --project backend python scripts/curadoria.py adaptar          # múltipla escolha → discursiva (lotes de 20)
  uv run --project backend python scripts/curadoria.py temas --area Pediatria --refazer

Saídas versionadas em curadoria/*.json. Revise na página "Curadoria" do app.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from lamina import ajustes, config, db  # noqa: E402
from lamina.claude.runner import Pedido, SdkRunner, sanitizar_ambiente  # noqa: E402
from lamina.importer import slug  # noqa: E402

PREFIXO = {"Clínica Médica": "cm", "Cirurgia": "cir", "Pediatria": "ped",
           "Ginecologia e Obstetrícia": "go", "Saúde Coletiva": "sc"}
TIPOS = ["diagnostico", "conduta", "exame_complementar", "interpretacao_imagem", "fisiopatologia",
         "epidemiologia_prevencao", "etica_legislacao_gestao", "outro"]

SISTEMA_TEMAS = """Você organiza bancos de questões de residência médica em temas de estudo.
Você receberá todas as questões de UMA área da prova de Acesso Direto da Unicamp (2022–2026), numeradas Q1..Qn.

Tarefa:
1. Crie de 10 a 14 temas de estudo para esta área. Bons temas agrupam conteúdos que se estudam juntos
   (ex.: "Pneumonias e infecções respiratórias", "Neonatologia: sala de parto e icterícia"). Nome curto (≤ 48
   caracteres), descrição de 1 frase listando os assuntos. Cada tema deve ter pelo menos 4 questões; evite
   um tema "miscelânea" grande.
2. Classifique CADA questão: tema principal (índice do tema, começando em 0), até 2 temas secundários
   (índices; pode ser vazio), um subtópico específico em até 8 palavras (ex.: "Bronquiolite: critérios de
   internação") e o tipo cognitivo da pergunta.
Todas as questões Q1..Qn precisam aparecer exatamente uma vez na classificação."""

SISTEMA_ADAPTAR = """Você adapta questões de múltipla escolha da Unicamp para o formato atual da prova: resposta curta discursiva.
Para cada questão (Qk) você recebe o enunciado, as alternativas e a letra correta.

Devolva:
- pergunta_nova: vazio ("") se o final do enunciado já funciona como pergunta discursiva (ex.: "A CONDUTA É:",
  "A HIPÓTESE DIAGNÓSTICA É:"). Caso contrário (ex.: "É CORRETO AFIRMAR", "ASSINALE A ALTERNATIVA", matching,
  afirmações V/F), escreva uma nova pergunta final no estilo da banca, em CAIXA ALTA, cuja resposta curta seja
  o conceito central da alternativa correta (ex.: "QUAL A PROFILAXIA INDICADA PARA OS CONTACTANTES E ATÉ QUANDO
  INICIÁ-LA?").
- trecho_substituido: quando pergunta_nova não for vazia, copie LITERALMENTE o trecho final do enunciado que
  ela substitui (a frase-pergunta original). Senão, "".
- resposta_esperada: no estilo do gabarito oficial da Unicamp — a resposta essencial, sinônimos aceitos e,
  se útil, o que "não pontua". Ex.: "Mobilização precoce. Sinonímia: deambulação precoce. Não pontua: contenção
  física ou sedação."
- aceitaveis: lista curta de formas equivalentes que devem pontuar.
- obs: vazio, ou uma nota curta se a alternativa correta estiver desatualizada frente às recomendações atuais."""


def _esquema_temas() -> dict:
    return {
        "type": "object",
        "properties": {
            "temas": {"type": "array", "items": {
                "type": "object",
                "properties": {"nome": {"type": "string"}, "descricao": {"type": "string"}},
                "required": ["nome", "descricao"], "additionalProperties": False}},
            "classificacao": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "q": {"type": "integer"}, "t": {"type": "integer"},
                    "s": {"type": "array", "items": {"type": "integer"}},
                    "sub": {"type": "string"}, "tipo": {"type": "string", "enum": TIPOS}},
                "required": ["q", "t", "s", "sub", "tipo"], "additionalProperties": False}},
        },
        "required": ["temas", "classificacao"], "additionalProperties": False,
    }


ESQUEMA_ADAPTAR = {
    "type": "object",
    "properties": {"itens": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "q": {"type": "integer"}, "pergunta_nova": {"type": "string"}, "trecho_substituido": {"type": "string"},
            "resposta_esperada": {"type": "string"}, "aceitaveis": {"type": "array", "items": {"type": "string"}},
            "obs": {"type": "string"}},
        "required": ["q", "pergunta_nova", "trecho_substituido", "resposta_esperada", "aceitaveis", "obs"],
        "additionalProperties": False}}},
    "required": ["itens"], "additionalProperties": False,
}


def carregar_questoes() -> list[dict]:
    return [json.loads(x) for x in config.QUESTOES_JSONL.read_text(encoding="utf-8").splitlines() if x.strip()]


def ler(nome: str, padrao):
    p = config.CURADORIA_DIR / nome
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else padrao


def gravar(nome: str, dados) -> None:
    config.CURADORIA_DIR.mkdir(exist_ok=True)
    (config.CURADORIA_DIR / nome).write_text(
        json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def resumo_questao(q: dict) -> str:
    e = " ".join(q["enunciado"].split())
    trecho = e if len(e) <= 420 else f"{e[:220]} […] {e[-180:]}"
    if q["formato"] == "multipla_escolha" and q.get("alternativas"):
        resp = q["alternativas"].get((q["gabarito"].get("letra") or "").lower(), "")
    else:
        resp = q["gabarito"].get("resposta_esperada") or ""
    return f"{trecho} || Gabarito: {' '.join(resp.split())[:110]}"


async def temas(runner: SdkRunner, modelo: str, esforco: str | None, areas: list[str], refazer: bool) -> None:
    questoes = carregar_questoes()
    atuais = ler("temas.json", {"temas": []})
    classif = ler("questao_temas.json", {})
    for area in areas:
        prefixo = PREFIXO[area]
        if not refazer and any(t["area"] == area for t in atuais["temas"]):
            print(f"[temas] {area}: já existe (use --refazer)")
            continue
        qs = [q for q in questoes if q["area"] == area and not q.get("anulada")]
        linhas_q = "\n".join(f"Q{i + 1}. {resumo_questao(q)}" for i, q in enumerate(qs))
        print(f"[temas] {area}: {len(qs)} questões → Claude…", flush=True)
        r = await runner.executar(Pedido(
            papel="curadoria", modelo=modelo, esforco=esforco, sistema=SISTEMA_TEMAS, esquema=_esquema_temas(),
            ref=f"curadoria:temas:{prefixo}", prompt=f"ÁREA: {area}\n\n{linhas_q}"))
        dados = r.estruturado
        ids, novos = [], []
        for i, t in enumerate(dados["temas"]):
            tid = f"{prefixo}-{slug(t['nome'])}"[:56]
            while tid in ids:
                tid += "-2"
            ids.append(tid)
            novos.append({"id": tid, "area": area, "nome": t["nome"].strip(), "descricao": t["descricao"].strip(),
                          "ordem": i})
        faltando = set(range(1, len(qs) + 1))
        for c in dados["classificacao"]:
            if not (1 <= c["q"] <= len(qs)) or not (0 <= c["t"] < len(ids)):
                continue
            faltando.discard(c["q"])
            classif[qs[c["q"] - 1]["id"]] = {
                "tema": ids[c["t"]],
                "secundarios": [ids[s] for s in c["s"] if 0 <= s < len(ids) and s != c["t"]][:2],
                "subtopico": c["sub"].strip(),
                "tipo_cognitivo": c["tipo"],
            }
        atuais["temas"] = [t for t in atuais["temas"] if t["area"] != area] + novos
        gravar("temas.json", atuais)
        gravar("questao_temas.json", classif)
        print(f"   {len(novos)} temas; sem classificação: {len(faltando)}; tokens={r.uso.total_tokens} "
              f"custo-eq=US${r.uso.custo_usd:.3f}")


async def adaptar(runner: SdkRunner, modelo: str, esforco: str | None, tamanho: int, refazer: bool) -> None:
    adapt = ler("adaptacoes_mc.json", {})
    mc = [q for q in carregar_questoes() if q["formato"] == "multipla_escolha" and not q.get("anulada")]
    pendentes = [q for q in mc if refazer or q["id"] not in adapt]
    print(f"[adaptar] {len(pendentes)} de {len(mc)} pendentes")
    for i in range(0, len(pendentes), tamanho):
        lote = pendentes[i:i + tamanho]
        blocos = []
        for k, q in enumerate(lote, 1):
            alts = "\n".join(f"{a.upper()}) {t}" for a, t in q["alternativas"].items())
            blocos.append(f"### Q{k}\n{q['enunciado']}\n{alts}\nCorreta: {q['gabarito']['letra']}")
        r = await runner.executar(Pedido(
            papel="curadoria", modelo=modelo, esforco=esforco, sistema=SISTEMA_ADAPTAR, esquema=ESQUEMA_ADAPTAR,
            ref=f"curadoria:adaptar:{i}", prompt="\n\n".join(blocos)))
        for item in r.estruturado["itens"]:
            if not (1 <= item["q"] <= len(lote)):
                continue
            q = lote[item["q"] - 1]
            enunciado = q["enunciado"]
            nova = item["pergunta_nova"].strip()
            if nova:
                trecho = item["trecho_substituido"].strip()
                if trecho and trecho in enunciado:
                    pos = enunciado.rfind(trecho)
                    enunciado = enunciado[:pos].rstrip() + " " + nova
                else:
                    enunciado = enunciado.rstrip() + "\n\n" + nova
            adapt[q["id"]] = {
                "enunciado_discursivo": enunciado,
                "resposta_esperada": item["resposta_esperada"].strip(),
                "aceitaveis": [a.strip() for a in item["aceitaveis"] if a.strip()],
                "obs": item["obs"].strip(),
                "pergunta_reescrita": bool(nova),
            }
        gravar("adaptacoes_mc.json", adapt)
        print(f"   lote {i // tamanho + 1}: {len(lote)} questões; tokens={r.uso.total_tokens} "
              f"custo-eq=US${r.uso.custo_usd:.3f}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("etapa", choices=["temas", "adaptar"])
    ap.add_argument("--area", action="append", choices=config.AREAS)
    ap.add_argument("--refazer", action="store_true")
    ap.add_argument("--lote", type=int, default=20)
    args = ap.parse_args()

    sanitizar_ambiente()
    db.inicializar()
    with db.conectar() as conn:
        modelo, esforco = ajustes.modelo(conn, "curadoria"), ajustes.esforco(conn, "curadoria")
    runner = SdkRunner(concorrencia=1, timeout_seg=900)
    if args.etapa == "temas":
        asyncio.run(temas(runner, modelo, esforco, args.area or config.AREAS, args.refazer))
    else:
        asyncio.run(adaptar(runner, modelo, esforco, args.lote, args.refazer))


if __name__ == "__main__":
    main()
