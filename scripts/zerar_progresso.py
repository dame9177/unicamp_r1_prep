"""Zera o progresso de estudo (com backup antes), mantendo perfil, ajustes, questões e curadoria.

Uso (com o servidor parado):
    uv run --project backend python scripts/zerar_progresso.py [--manter-biblioteca] [--pausar-ate HH:MM]

Apaga: respostas, blocos, flashcards e revisões, conversas, missões/rondas/ações do Preceptor, agenda,
avisos, tarefas, registro de uso do Claude, explicações fixadas, pesos e marcações manuais dos temas e
os cadernos dos agentes. A biblioteca também, salvo --manter-biblioteca.
O backup fica em app_data/backup/zerado-<data-hora>/.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from lamina import config, db  # noqa: E402

TABELAS = ["revisoes", "flashcards", "tentativas", "bloco_questoes", "blocos", "mensagens", "chats",
           "coach_acoes", "coach_insights", "questao_notas", "agenda", "avisos", "tarefas", "estado",
           "llm_jobs", "limite_uso"]
TABELAS_BIBLIOTECA = ["biblioteca_fts", "biblioteca"]


def servidor_rodando(porta: int = 8765) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", porta)) == 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manter-biblioteca", action="store_true")
    ap.add_argument("--pausar-ate", metavar="HH:MM",
                    help="pausa o segundo plano do Preceptor até este horário (do dia seguinte, se já passou)")
    args = ap.parse_args()
    # Com LAMINA_DATA_DIR apontando para outro lugar, os dados não são os do servidor em execução.
    if servidor_rodando() and "LAMINA_DATA_DIR" not in os.environ:
        sys.exit("Pare o servidor antes (systemctl --user stop lamina ou ./scripts/parar.sh).")

    destino = config.APP_DATA / "backup" / f"zerado-{datetime.now():%Y-%m-%d-%H%M%S}"
    destino.mkdir(parents=True)
    origem = sqlite3.connect(config.DB_PATH)
    copia = sqlite3.connect(destino / "lamina.db")
    origem.backup(copia)
    copia.close()
    origem.close()
    pastas = ["agentes"] + ([] if args.manter_biblioteca else ["biblioteca"])
    for nome in pastas:
        if (config.APP_DATA / nome).exists():
            shutil.copytree(config.APP_DATA / nome, destino / nome)
    print(f"Backup em {destino}")

    db.inicializar()
    tabelas = TABELAS + ([] if args.manter_biblioteca else TABELAS_BIBLIOTECA)
    with db.conectar() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in tabelas:
            conn.execute(f"DELETE FROM {t}")
        conn.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({','.join('?' * len(tabelas))})", tabelas)
        conn.execute("UPDATE temas SET peso_coach = 1.0, peso_motivo = NULL, status_manual = NULL, "
                     "status_manual_em = NULL")
        if args.pausar_ate:
            h, m = (int(x) for x in args.pausar_ate.split(":"))
            alvo = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
            if alvo <= datetime.now():
                alvo += timedelta(days=1)
            db.salvar_estado(conn, "pausa_fundo_ate", alvo.astimezone(UTC).isoformat())
            print(f"Segundo plano pausado até {alvo:%d/%m %H:%M}")
    for nome in pastas + ["terminal"]:
        shutil.rmtree(config.APP_DATA / nome, ignore_errors=True)
    con = sqlite3.connect(config.DB_PATH)
    con.execute("VACUUM")
    con.close()
    print("Progresso zerado. Perfil, ajustes, questões e curadoria mantidos.")


if __name__ == "__main__":
    main()
