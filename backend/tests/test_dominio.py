from datetime import UTC, datetime, timedelta

from lamina.domain import priority, srs
from lamina.domain.mastery import Estatistica, pontos_dominio


def est_com(*itens):
    e = Estatistica()
    for i, (v, c) in enumerate(itens):
        e.adicionar(f"q{i}", v, c, "2026-10-01T10:00:00Z" if v else None)
    return e


def test_chute_nao_conta_para_dominio_mas_conta_no_bruto():
    assert pontos_dominio("correto", "chute") == 0
    assert pontos_dominio("correto", "duvida") == 1
    assert pontos_dominio("parcial", "certeza") == 0.5
    e = est_com(("correto", "chute"), ("correto", "certeza"))
    assert e.aproveitamento_bruto == 1.0
    assert e.aproveitamento_firme == 0.5
    assert e.questoes_refazer == ["q0"]


def test_dominado_exige_80_porcento_e_cobertura_total():
    cinco_certas = [("correto", "certeza")] * 4 + [("incorreto", "certeza")]
    assert est_com(*cinco_certas).status() == "dominado"  # 80%
    tres_de_quatro = [("correto", "certeza")] * 3 + [("incorreto", "certeza")]
    assert est_com(*tres_de_quatro).status() == "em_progresso"  # 75%
    incompleto = [("correto", "certeza")] * 4 + [(None, None)]
    assert est_com(*incompleto).status() == "em_progresso"  # cobertura < 100%
    assert est_com((None, None)).status() == "nao_iniciado"


def test_override_manual_prevalece():
    e = est_com(("incorreto", "certeza"))
    assert e.status("dominado") == "dominado"
    e2 = est_com(*[("correto", "certeza")] * 3)
    assert e2.status() == "dominado"
    assert e2.status("nao_dominado") == "em_progresso"


def test_selo_revisar_apos_14_dias():
    e = est_com(("correto", "certeza"))
    agora = datetime(2026, 10, 1, 10, tzinfo=UTC) + timedelta(days=15)
    assert e.precisa_revisar("dominado", agora)
    assert not e.precisa_revisar("em_progresso", agora)


def test_prioridade_ordena_por_prevalencia_e_lacuna():
    alta_prev_ruim = priority.prioridade(1.0, 0.2)
    alta_prev_boa = priority.prioridade(1.0, 0.95)
    baixa_prev_ruim = priority.prioridade(0.3, 0.2)
    assert alta_prev_ruim > alta_prev_boa
    assert alta_prev_ruim > baixa_prev_ruim
    assert priority.prioridade(1.0, None) == 1.0
    assert priority.prioridade(0.5, None, peso_coach=2.0) == 1.0


def test_srs_respeita_data_da_prova():
    estado, due = srs.novo_cartao()
    agora = datetime(2026, 10, 5, tzinfo=UTC)
    for _ in range(8):
        estado, due = srs.revisar(estado, 4, dias_ate_prova=10, agora=agora)
        agora = datetime.fromisoformat(due)
    # Mesmo com "Fácil" repetido, nenhum intervalo passa de 9 dias.
    assert srs.agendador(10).maximum_interval == 9
