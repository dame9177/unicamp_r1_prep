"""Agentes da Lâmina e seus diretórios de trabalho persistentes ("cadernos").

Cada agente tem `app_data/agentes/<nome>/`, que é o diretório de trabalho (cwd) das suas instâncias
do Claude Code. Ali ele escreve livremente (Write/Edit), organiza subpastas e mantém `MEMORIA.md`,
um índice curto que o app injeta no prompt de sistema de toda nova sessão. É assim que o mesmo
agente acumula conhecimento entre conversas.
"""

from __future__ import annotations

from pathlib import Path

from lamina import config

AGENTES: dict[str, dict] = {
    "tutor": {"nome": "Tutor", "descricao": "Explica questões e dúvidas; mesmo agente em todas as conversas."},
    "preceptor": {"nome": "Preceptor", "descricao": "Orquestrador em segundo plano: estratégia, agenda, avisos, "
                                                    "tarefas para outros agentes. Só conversa com o aluno."},
    "bibliotecario": {"nome": "Bibliotecário", "descricao": "Busca, captura e organiza documentos brasileiros "
                                                            "oficiais na biblioteca; escreve notas verificadas."},
    "juiz": {"nome": "Juiz", "descricao": "Corrige respostas; o estágio 2 verifica a recomendação vigente."},
    "flashcards": {"nome": "Flashcards", "descricao": "Gera cartões de revisão."},
}

# Papel do runner → agente dono do diretório (o juiz de revisão usa o caderno do juiz).
PAPEL_AGENTE = {"juiz_revisao": "juiz"}

MEMORIA_LIMITE = 6000

_MODELO_MEMORIA = """# Memória do {nome}

Este arquivo é seu índice permanente: o app o inclui no seu prompt em toda nova sessão.
Mantenha-o curto (até ~60 linhas) e atualizado: o que você sabe, onde guardou, o que falta.
Detalhes vão em outros arquivos deste diretório (crie pastas à vontade); aqui ficam só ponteiros.

## Organização do caderno
- (nada ainda)

## Aprendizados sobre o aluno
- (nada ainda)

## Pendências
- (nada ainda)
"""


def agente_de(papel: str) -> str:
    return PAPEL_AGENTE.get(papel, papel)


def workspace(agente: str) -> Path:
    if agente not in AGENTES:
        raise KeyError(agente)
    pasta = config.AGENTES_DIR / agente
    pasta.mkdir(parents=True, exist_ok=True)
    mem = pasta / "MEMORIA.md"
    if not mem.exists():
        mem.write_text(_MODELO_MEMORIA.format(nome=AGENTES[agente]["nome"]), encoding="utf-8")
    return pasta


def memoria(agente: str) -> str:
    texto = (workspace(agente) / "MEMORIA.md").read_text(encoding="utf-8").strip()
    if len(texto) > MEMORIA_LIMITE:
        texto = texto[:MEMORIA_LIMITE] + "\n… (MEMORIA.md truncada: enxugue-a)"
    return texto


def _seguro(agente: str, relativo: str) -> Path:
    raiz = workspace(agente).resolve()
    alvo = (raiz / relativo).resolve()
    if not alvo.is_relative_to(raiz):
        raise PermissionError(relativo)
    return alvo


def listar_arquivos(agente: str, limite: int = 500) -> list[dict]:
    raiz = workspace(agente)
    itens = []
    for p in sorted(raiz.rglob("*")):
        if p.is_file() and not any(parte.startswith(".") for parte in p.relative_to(raiz).parts):
            st = p.stat()
            itens.append({"caminho": str(p.relative_to(raiz)), "bytes": st.st_size, "modificado": st.st_mtime})
            if len(itens) >= limite:
                break
    return itens


def ler_arquivo(agente: str, relativo: str, limite: int = 400_000) -> str:
    alvo = _seguro(agente, relativo)
    if not alvo.is_file():
        raise FileNotFoundError(relativo)
    return alvo.read_text(encoding="utf-8", errors="replace")[:limite]
