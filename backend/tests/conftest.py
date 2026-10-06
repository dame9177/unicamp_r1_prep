import json
import shutil

import pytest
from fastapi.testclient import TestClient

from lamina import config, db, importer
from lamina.claude import runner as runner_mod


@pytest.fixture()
def ambiente(tmp_path, monkeypatch):
    """Banco, perfil e curadoria isolados em diretório temporário."""
    dados = tmp_path / "app_data"
    monkeypatch.setattr(config, "APP_DATA", dados)
    monkeypatch.setattr(config, "DB_PATH", dados / "lamina.db")
    monkeypatch.setattr(config, "PERFIL_PATH", dados / "perfil.json")
    monkeypatch.setattr(config, "CLAUDE_CWD", dados / "claude_cwd")
    monkeypatch.setattr(config, "AGENTES_DIR", dados / "agentes")
    monkeypatch.setattr(config, "BIBLIOTECA_DIR", dados / "biblioteca")
    monkeypatch.setattr(config, "MAESTRO_ATIVO", False)
    from lamina.biblioteca import conversor

    monkeypatch.setattr(conversor, "cli", lambda: None)  # sem GPU nos testes; test_upload usa um conversor falso
    cur = tmp_path / "curadoria"
    if config.CURADORIA_DIR.exists():
        shutil.copytree(config.CURADORIA_DIR, cur)
    else:
        cur.mkdir()
    monkeypatch.setattr(config, "CURADORIA_DIR", cur)
    config.salvar_perfil({"data_prova": "2026-11-15"})
    db.inicializar()
    with db.conectar() as conn:
        importer.importar(conn)
    yield tmp_path


@pytest.fixture()
def fake_runner():
    def juiz(pedido):
        if "juiz_lote" in pedido.ref or pedido.ref.startswith("lote:"):
            ids = [int(x.split("=")[1].split("\n")[0]) for x in pedido.prompt.split("### ITEM ")[1:]]
            return {"resultados": [{"id": i, "veredito": "correto", "justificativa": "ok", "faltou": "",
                                    "resposta_modelo": "x"} for i in ids]}
        if pedido.ref.endswith(":atualizacao"):
            return {"veredito": "correto", "justificativa": "vale a conduta atual", "faltou": "",
                    "resposta_modelo": "rifampicina", "verificar_atualizacao": False,
                    "adendo": "Gabarito da época: ceftriaxona. Atual: rifampicina (MS 2026)."}
        if "ATUALIZAR" in pedido.prompt:
            return {"veredito": "incorreto", "justificativa": "diverge", "faltou": "", "resposta_modelo": "",
                    "verificar_atualizacao": True, "adendo": ""}
        veredito = "correto" if "CERTO" in pedido.prompt else "incorreto"
        return {"veredito": veredito, "justificativa": "teste", "faltou": "" if veredito == "correto" else "tudo",
                "resposta_modelo": "resposta ideal"}

    fr = runner_mod.FakeRunner({
        "juiz": juiz,
        "flashcards": lambda p: {"cartoes": [{"frente": "F1?", "verso": "V1"}, {"frente": "F2?", "verso": "V2"}]},
        "tutor": lambda p: "Explicação **didática**.\n\nFontes: SBP 2025",
        "preceptor": lambda p: "Ronda feita: plano ajustado.",
        "bibliotecario": lambda p: "Relatório: capturei 1 documento.",
    })
    runner_mod.definir_runner(fr)
    yield fr
    runner_mod.definir_runner(None)


@pytest.fixture()
def cliente(ambiente, fake_runner, monkeypatch):
    from lamina import main

    monkeypatch.setattr(main, "sanitizar_ambiente", list)
    with TestClient(main.app) as c:
        yield c


def jsonl_questoes():
    return [json.loads(linha) for linha in config.QUESTOES_JSONL.read_text(encoding="utf-8").splitlines() if linha]
