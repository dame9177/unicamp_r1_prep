"""Importa o banco de questões (somente leitura) + curadoria versionada para o SQLite.

Idempotente: roda a cada inicialização. Só reescreve colunas derivadas das fontes; nada do
progresso do usuário (tentativas, notas, flashcards) é tocado.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from lamina import config

PESO_PROCESSO = {2026: 1.0, 2025: 0.9, 2024: 0.8, 2023: 0.6, 2022: 0.5}
PESO_MC = 0.8

# Questões de múltipla escolha cujo enunciado só faz sentido com as alternativas.
_PRECISA_ALTERNATIVAS = re.compile(r"(CORRETO AFIRMAR|ASSINALE|VERDADEIR|INCORRET|EXCETO|FALSA)", re.IGNORECASE)


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def tema_geral_id(area: str) -> str:
    return f"{slug(area)}--geral"


def _ler_json(path: Path, padrao):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return padrao


def carregar_curadoria(curadoria_dir: Path | None = None) -> tuple[list[dict], dict, dict]:
    d = curadoria_dir or config.CURADORIA_DIR
    temas = _ler_json(d / "temas.json", {"temas": []})["temas"]
    classif = _ler_json(d / "questao_temas.json", {})
    adapt = _ler_json(d / "adaptacoes_mc.json", {})
    return temas, classif, adapt


def precisa_alternativas(enunciado: str) -> bool:
    return bool(_PRECISA_ALTERNATIVAS.search(enunciado[-220:]))


def peso_prevalencia(q: dict) -> float:
    if q.get("anulada"):
        return 0.0
    peso = PESO_PROCESSO.get(q["processo_seletivo"], 0.5)
    if q["formato"] == "multipla_escolha":
        peso *= PESO_MC
    return peso


def importar(
    conn: sqlite3.Connection,
    questoes_jsonl: Path | None = None,
    curadoria_dir: Path | None = None,
) -> dict:
    jsonl = questoes_jsonl or config.QUESTOES_JSONL
    questoes = [json.loads(linha) for linha in jsonl.read_text(encoding="utf-8").splitlines() if linha.strip()]
    temas, classif, adapt = carregar_curadoria(curadoria_dir)

    # Temas: curados + um "geral" por área para questões ainda sem classificação.
    ids_temas = set()
    for i, area in enumerate(config.AREAS):
        temas_area = [t for t in temas if t["area"] == area]
        gerais = [{"id": tema_geral_id(area), "area": area, "nome": f"{area} — não classificadas",
                   "descricao": "Questões ainda sem tema fino.", "ordem": 999}]
        for j, t in enumerate(temas_area + gerais):
            ids_temas.add(t["id"])
            conn.execute(
                """INSERT INTO temas (id, area, nome, descricao, ordem) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET area=excluded.area, nome=excluded.nome,
                   descricao=excluded.descricao, ordem=excluded.ordem""",
                (t["id"], area, t["nome"], t.get("descricao"), t.get("ordem", j) + i * 1000),
            )

    n_adaptadas = 0
    for q in questoes:
        mc = q["formato"] == "multipla_escolha"
        alternativas = q.get("alternativas")
        letra = q["gabarito"].get("letra")
        enunciado = q["enunciado"]
        resposta = q["gabarito"].get("resposta_esperada")
        aceitaveis: list[str] = []
        adaptada = 0
        obs = None

        if mc:
            a = adapt.get(q["id"])
            if a:
                enunciado = a["enunciado_discursivo"]
                resposta = a["resposta_esperada"]
                aceitaveis = a.get("aceitaveis", [])
                obs = a.get("obs") or None
                adaptada = 1
                n_adaptadas += 1
            elif letra and alternativas:
                # Adaptação automática provisória: a alternativa correta vira a resposta esperada.
                resposta = alternativas.get(letra.lower())

        c = classif.get(q["id"], {})
        tema_id = c.get("tema") if c.get("tema") in ids_temas else tema_geral_id(q["area"])

        conn.execute(
            """INSERT INTO questoes (
                 id, prova_id, processo, turno, tipo_prova, numero, area, formato_original,
                 enunciado_compartilhado, enunciado, enunciado_original, alternativas_json, letra_original,
                 resposta_esperada, aceitaveis_json, ampliado, anulada, adaptada, obs_curadoria, imagens_json, fonte_json,
                 tema_id, temas_secundarios_json, subtopico, tipo_cognitivo, peso_prevalencia)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 prova_id=excluded.prova_id, processo=excluded.processo, turno=excluded.turno,
                 tipo_prova=excluded.tipo_prova, numero=excluded.numero, area=excluded.area,
                 formato_original=excluded.formato_original,
                 enunciado_compartilhado=excluded.enunciado_compartilhado, enunciado=excluded.enunciado,
                 enunciado_original=excluded.enunciado_original, alternativas_json=excluded.alternativas_json,
                 letra_original=excluded.letra_original, resposta_esperada=excluded.resposta_esperada,
                 aceitaveis_json=excluded.aceitaveis_json, ampliado=excluded.ampliado,
                 anulada=excluded.anulada, adaptada=excluded.adaptada, obs_curadoria=excluded.obs_curadoria, imagens_json=excluded.imagens_json,
                 fonte_json=excluded.fonte_json, tema_id=excluded.tema_id,
                 temas_secundarios_json=excluded.temas_secundarios_json, subtopico=excluded.subtopico,
                 tipo_cognitivo=excluded.tipo_cognitivo, peso_prevalencia=excluded.peso_prevalencia""",
            (
                q["id"], q["prova_id"], q["processo_seletivo"], q.get("turno"), q.get("tipo"), q.get("numero"),
                q["area"], q["formato"], q.get("enunciado_compartilhado"), enunciado, q["enunciado"],
                json.dumps(alternativas, ensure_ascii=False) if alternativas else None, letra, resposta,
                json.dumps(aceitaveis, ensure_ascii=False), int(q["gabarito"].get("ampliado", False)),
                int(q.get("anulada", False)), adaptada, obs, json.dumps(q.get("imagens", []), ensure_ascii=False),
                json.dumps(q.get("fonte"), ensure_ascii=False), tema_id,
                json.dumps([s for s in c.get("secundarios", []) if s in ids_temas], ensure_ascii=False),
                c.get("subtopico"), c.get("tipo_cognitivo"), peso_prevalencia(q),
            ),
        )

    # Temas que saíram da curadoria ficam no banco (podem ter blocos/flashcards ligados),
    # mas sem questões eles não aparecem nas listagens.
    return {
        "questoes": len(questoes),
        "temas": len(ids_temas),
        "classificadas": sum(1 for q in questoes if q["id"] in classif),
        "mc_adaptadas": n_adaptadas,
    }
