import json

from lamina import config, importer
from lamina.db import conectar, linha, linhas


def test_importa_todas_as_questoes_e_e_idempotente(ambiente):
    with conectar() as conn:
        assert linha(conn, "SELECT COUNT(*) AS n FROM questoes")["n"] == 650
        r = importer.importar(conn)
        assert r["questoes"] == 650
        assert linha(conn, "SELECT COUNT(*) AS n FROM questoes")["n"] == 650
        assert linha(conn, "SELECT COUNT(*) AS n FROM questoes WHERE anulada = 1")["n"] == 3
        assert linha(conn, "SELECT COUNT(*) AS n FROM questoes WHERE formato_original = 'multipla_escolha'")["n"] == 160


def test_toda_questao_tem_tema_e_resposta(ambiente):
    with conectar() as conn:
        assert linha(conn, "SELECT COUNT(*) AS n FROM questoes WHERE tema_id IS NULL")["n"] == 0
        sem_resposta = linhas(conn, "SELECT id FROM questoes WHERE resposta_esperada IS NULL AND anulada = 0")
        assert sem_resposta == []


def test_mc_sem_adaptacao_usa_alternativa_correta(ambiente):
    (config.CURADORIA_DIR / "adaptacoes_mc.json").write_text("{}", encoding="utf-8")
    with conectar() as conn:
        importer.importar(conn)
        q = linha(conn, "SELECT * FROM questoes WHERE id = 'unicamp-2022-ad-p1-q05'")
        assert q["resposta_esperada"] == "Síndrome do intestino irritável."
        assert q["adaptada"] == 0


def test_overlay_de_curadoria(ambiente):
    (config.CURADORIA_DIR / "temas.json").write_text(json.dumps({"temas": [
        {"id": "cm-gastro", "area": "Clínica Médica", "nome": "Gastro", "descricao": "x"}]}), encoding="utf-8")
    (config.CURADORIA_DIR / "questao_temas.json").write_text(json.dumps({
        "unicamp-2022-ad-p1-q05": {"tema": "cm-gastro", "subtopico": "SII", "tipo_cognitivo": "diagnostico"}}),
        encoding="utf-8")
    (config.CURADORIA_DIR / "adaptacoes_mc.json").write_text(json.dumps({
        "unicamp-2022-ad-p1-q05": {"enunciado_discursivo": "QUAL A HIPÓTESE?", "resposta_esperada": "SII",
                                   "aceitaveis": ["síndrome do intestino irritável"]}}), encoding="utf-8")
    with conectar() as conn:
        importer.importar(conn)
        q = linha(conn, "SELECT * FROM questoes WHERE id = 'unicamp-2022-ad-p1-q05'")
    assert q["tema_id"] == "cm-gastro"
    assert q["enunciado"] == "QUAL A HIPÓTESE?"
    assert q["adaptada"] == 1
    assert json.loads(q["aceitaveis_json"]) == ["síndrome do intestino irritável"]


def test_prevalencia_pondera_ano_e_formato():
    base = {"anulada": False, "formato": "resposta_curta"}
    assert importer.peso_prevalencia({**base, "processo_seletivo": 2026}) == 1.0
    assert importer.peso_prevalencia({**base, "processo_seletivo": 2022, "formato": "multipla_escolha"}) == 0.4
    assert importer.peso_prevalencia({**base, "processo_seletivo": 2026, "anulada": True}) == 0.0
