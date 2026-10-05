"""Terminal isolado (bubblewrap) para as instâncias do Claude.

O Claude lê páginas da web; uma página maliciosa poderia tentar induzi-lo a executar comandos.
Por isso o bash do app roda em um sandbox próprio:
- sem rede (--unshare-all), sem acesso à home do usuário;
- /trabalho gravável (persistente em app_data/terminal), /dados somente leitura com o banco de
  questões, a curadoria e um snapshot do banco de desempenho (lamina.db);
- tempo e saída limitados.
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import tempfile
from pathlib import Path

from lamina import config

LIMITE_SAIDA = 12_000
TEMPO_MAX = 60


def disponivel() -> bool:
    return shutil.which("bwrap") is not None


def _snapshot_banco(destino: Path) -> None:
    origem = sqlite3.connect(config.DB_PATH)
    copia = sqlite3.connect(destino)
    try:
        origem.backup(copia)
    finally:
        copia.close()
        origem.close()


def _comando_bwrap(trabalho: Path, banco: Path, comando: str) -> list[str]:
    args = ["bwrap", "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
            "--symlink", "usr/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for extra in ("/etc/alternatives", "/etc/ssl", "/etc/ld.so.cache", "/etc/localtime"):
        if Path(extra).exists():
            args += ["--ro-bind", extra, extra]
    args += [
        "--bind", str(trabalho), "/trabalho",
        "--ro-bind", str(config.BANCO_DIR), "/dados/banco_questoes",
        "--ro-bind", str(banco), "/dados/lamina.db",
    ]
    if config.CURADORIA_DIR.exists():
        args += ["--ro-bind", str(config.CURADORIA_DIR), "/dados/curadoria"]
    args += ["--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
             "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/trabalho", "--setenv", "LANG", "C.UTF-8",
             "--chdir", "/trabalho", "bash", "-c", comando]
    return args


async def executar(comando: str, tempo_max: int = 30) -> str:
    if not disponivel():
        return "Terminal indisponível: bubblewrap (bwrap) não está instalado."
    trabalho = config.APP_DATA / "terminal"
    trabalho.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lamina-") as tmp:
        banco = Path(tmp) / "lamina.db"
        _snapshot_banco(banco)
        proc = await asyncio.create_subprocess_exec(
            *_comando_bwrap(trabalho, banco, comando),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            saida, _ = await asyncio.wait_for(proc.communicate(), timeout=min(tempo_max, TEMPO_MAX))
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return f"(tempo esgotado após {tempo_max}s)"
    texto = saida.decode("utf-8", errors="replace")
    if len(texto) > LIMITE_SAIDA:
        texto = texto[:LIMITE_SAIDA] + f"\n… (saída truncada; {len(texto)} caracteres no total)"
    return f"{texto}\n[código de saída: {proc.returncode}]"


DESCRICAO = (
    "Executa um comando bash em um sandbox isolado (sem internet, sem acesso à máquina do usuário). "
    "Diretório de trabalho gravável: /trabalho. Somente leitura: /dados/banco_questoes (provas em JSON/Markdown e "
    "imagens; data/questoes.jsonl tem todas as questões), /dados/curadoria (temas e classificação) e /dados/lamina.db "
    "(SQLite com o desempenho do aluno: tabelas questoes, temas, tentativas, flashcards, blocos). "
    "Disponíveis: python3 (com sqlite3, json, statistics), grep, find, awk, sed. Use para cálculos, contagens, "
    "buscas no banco de questões e análises; para internet use WebSearch/WebFetch."
)
