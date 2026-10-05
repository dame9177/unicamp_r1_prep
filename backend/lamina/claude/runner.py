"""Abstração do Claude Code CLI (via claude-agent-sdk) para a aplicação.

Princípios:
- Isolamento: `setting_sources=[]` e `strict_mcp_config=True` — nenhum plugin, hook, CLAUDE.md ou
  servidor MCP do usuário entra no contexto (economia de tokens e privacidade).
- Autenticação: usa o login salvo do CLI (`claude auth login`). Variáveis ANTHROPIC_*/CLAUDE_* herdadas
  do ambiente são removidas para que nenhum gateway/token alheio seja usado por engano.
- Toda chamada vira uma linha em `llm_jobs` (tokens, custo-equivalente, duração, erro).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from lamina import config
from lamina.db import conectar

_MANTER = {"CLAUDE_CODE_OAUTH_TOKEN"}


def sanitizar_ambiente() -> list[str]:
    """Remove do processo variáveis que redirecionariam o CLI para outra conta/gateway."""
    if os.environ.get("LAMINA_MANTER_AMBIENTE_CLAUDE") == "1":
        return []
    removidas = [
        k for k in list(os.environ)
        if (k.startswith("ANTHROPIC_") or k.startswith("CLAUDE")) and k not in _MANTER
    ]
    for k in removidas:
        os.environ.pop(k, None)
    return removidas


class ErroClaude(RuntimeError):
    pass


def mensagem_amigavel(erro: str) -> str:
    e = erro.lower()
    if "not logged in" in e or "/login" in e:
        return "O Claude CLI não está autenticado. Rode no terminal: claude auth login"
    if "401" in e or "authenticate" in e:
        return "Falha de autenticação no Claude CLI. Refaça o login: claude auth login"
    if "rate limit" in e or "usage limit" in e or "429" in e:
        return "Limite de uso do plano atingido. Tente de novo quando a janela reiniciar."
    return erro[:500]


@dataclass
class Pedido:
    papel: str
    prompt: str
    sistema: str
    modelo: str
    ferramentas: list[str] = field(default_factory=list)
    permitidas: list[str] = field(default_factory=list)
    mcp: dict[str, Any] | None = None
    esquema: dict | None = None
    esforco: str | None = None
    sem_raciocinio: bool = False
    retomar: str | None = None
    max_turnos: int | None = None
    ref: str | None = None
    diretorios_extras: list[str] = field(default_factory=list)
    cwd: str | None = None          # diretório de trabalho (caderno do agente); padrão: app_data/claude_cwd
    fundo: bool = False             # chamada do segundo plano (orçamento próprio, fila separada)
    timeout_seg: int | None = None


@dataclass
class Uso:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    custo_usd: float = 0.0
    duracao_ms: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read + self.cache_write


@dataclass
class Resultado:
    texto: str              # todos os textos da sessão (narração + resposta)
    estruturado: Any
    session_id: str | None
    uso: Uso
    job_id: int | None
    final: str = ""         # só a última mensagem (o relatório/resumo)


class Runner(Protocol):
    async def executar(self, pedido: Pedido) -> Resultado: ...

    def transmitir(self, pedido: Pedido) -> AsyncIterator[dict]: ...


# --------------------------------------------------------------------------------------------
# Registro de jobs
# --------------------------------------------------------------------------------------------


def _abrir_job(pedido: Pedido) -> int:
    with conectar() as conn:
        cur = conn.execute(
            "INSERT INTO llm_jobs (papel, modelo, ref, fundo) VALUES (?, ?, ?, ?)",
            (pedido.papel, pedido.modelo, pedido.ref, int(pedido.fundo)),
        )
        return cur.lastrowid


def _fechar_job(job_id: int, uso: Uso | None, erro: str | None = None, status: str | None = None) -> None:
    uso = uso or Uso()
    with conectar() as conn:
        conn.execute(
            """UPDATE llm_jobs SET status = ?, input_tokens = ?, output_tokens = ?, cache_read = ?,
                 cache_write = ?, custo_usd = ?, duracao_ms = ?, erro = ?,
                 finalizado_em = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
            (status or ("erro" if erro else "ok"), uso.input_tokens, uso.output_tokens, uso.cache_read, uso.cache_write,
             uso.custo_usd, uso.duracao_ms, erro, job_id),
        )


def _registrar_limite(info: Any) -> None:
    with conectar() as conn:
        conn.execute(
            """INSERT INTO limite_uso (id, status, utilizacao, reseta_em, tipo, atualizado_em)
               VALUES (1, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               ON CONFLICT(id) DO UPDATE SET status = excluded.status, utilizacao = excluded.utilizacao,
                 reseta_em = excluded.reseta_em, tipo = excluded.tipo, atualizado_em = excluded.atualizado_em""",
            (getattr(info, "status", None), getattr(info, "utilization", None),
             getattr(info, "resets_at", None), getattr(info, "rate_limit_type", None)),
        )


def _uso_de(resultado: Any) -> Uso:
    u = resultado.usage or {}
    return Uso(
        input_tokens=int(u.get("input_tokens") or 0),
        output_tokens=int(u.get("output_tokens") or 0),
        cache_read=int(u.get("cache_read_input_tokens") or 0),
        cache_write=int(u.get("cache_creation_input_tokens") or 0),
        custo_usd=float(resultado.total_cost_usd or 0.0),
        duracao_ms=int(resultado.duration_ms or 0),
    )


def _relativo(caminho: str) -> tuple[str, str]:
    """(onde, caminho relativo) para mostrar ao aluno o que o agente está consultando."""
    for onde, raiz in (("biblioteca", config.BIBLIOTECA_DIR), ("caderno", config.AGENTES_DIR),
                       ("banco", config.BANCO_DIR)):
        try:
            rel = os.path.relpath(caminho, raiz)
        except ValueError:
            continue
        if not rel.startswith(".."):
            if onde == "caderno":
                rel = rel.split(os.sep, 1)[-1]
            return onde, rel
    return "", os.path.basename(caminho)


def descrever_ferramenta(nome: str, entrada: dict) -> str:
    curto = nome.removeprefix("mcp__lamina__")
    match curto:
        case "WebSearch":
            return f"Pesquisando na web: {entrada.get('query', '')}"
        case "WebFetch":
            return f"Lendo na web: {entrada.get('url', '')}"
        case "Read":
            onde, rel = _relativo(entrada.get("file_path", ""))
            if onde == "banco":
                return "Examinando a imagem da questão" if rel.startswith("images") else f"Lendo o banco de questões: {rel}"
            return f"{'Biblioteca' if onde == 'biblioteca' else 'Caderno'}: lendo {rel}"
        case "Grep":
            onde, _ = _relativo(entrada.get("path", "") or "")
            return f"Procurando “{entrada.get('pattern', '')}”" + (f" na {onde}" if onde == "biblioteca" else "")
        case "Glob":
            return f"Listando arquivos: {entrada.get('pattern', '')}"
        case "Write" | "Edit":
            return f"Caderno: anotando em {_relativo(entrada.get('file_path', ''))[1]}"
        case "biblioteca_buscar":
            return f"Biblioteca: buscando “{entrada.get('consulta', '')}”"
        case "biblioteca_ler":
            onde = f" p. {entrada['pagina']}" if entrada.get("pagina") else ""
            return f"Biblioteca: lendo {entrada.get('id', '')}{onde}"
        case "biblioteca_capturar":
            return f"Biblioteca: baixando documento integral de {entrada.get('url', '')}"
        case "biblioteca_publicar_nota":
            return f"Biblioteca: publicando nota “{entrada.get('titulo', '')}”"
        case "biblioteca_catalogo":
            return "Biblioteca: consultando o catálogo"
        case "terminal":
            return f"Terminal: {str(entrada.get('comando', ''))[:80]}"
        case "historico_conversas":
            return f"Relendo conversas anteriores: {entrada.get('consulta', '')}"
    if nome.startswith("mcp__lamina__"):
        return f"Consultando seus dados: {curto}"
    return nome


# --------------------------------------------------------------------------------------------
# Implementação real (Agent SDK → claude CLI)
# --------------------------------------------------------------------------------------------

_MODELOS_SEM_ESFORCO = ("haiku",)


class SdkRunner:
    def __init__(self, concorrencia: int = 2, timeout_seg: int = 420):
        self._sem = asyncio.Semaphore(concorrencia)
        self._sem_fundo = asyncio.Semaphore(1)  # o segundo plano nunca ocupa a vez do aluno
        self._timeout = timeout_seg

    def _opcoes(self, p: Pedido, stream: bool):
        from claude_agent_sdk import ClaudeAgentOptions

        cwd = Path(p.cwd) if p.cwd else config.CLAUDE_CWD
        cwd.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = dict(
            cli_path=str(config.CLAUDE_CLI),
            cwd=str(cwd),
            setting_sources=[],
            strict_mcp_config=True,
            system_prompt=p.sistema,
            tools=p.ferramentas,
            allowed_tools=p.permitidas,
            permission_mode="dontAsk",
            model=p.modelo,
            include_partial_messages=stream,
        )
        if p.mcp:
            kwargs["mcp_servers"] = p.mcp
        if p.esquema:
            kwargs["output_format"] = {"type": "json_schema", "schema": p.esquema}
        if p.esforco and not any(m in p.modelo for m in _MODELOS_SEM_ESFORCO):
            kwargs["effort"] = p.esforco
        if p.sem_raciocinio and any(m in p.modelo for m in _MODELOS_SEM_ESFORCO):
            # Só modelos Haiku aceitam desligar o raciocínio; nos demais o controle é o esforço.
            kwargs["thinking"] = {"type": "disabled"}
        if p.retomar:
            kwargs["resume"] = p.retomar
        if p.max_turnos:
            kwargs["max_turns"] = p.max_turnos
        if p.diretorios_extras:
            kwargs["add_dirs"] = p.diretorios_extras
        return ClaudeAgentOptions(**kwargs)

    async def transmitir(self, pedido: Pedido) -> AsyncIterator[dict]:
        """Eventos: {tipo: texto|atividade|fim|erro, ...}. Sempre termina com 'fim' ou 'erro'."""
        from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, query

        job_id = _abrir_job(pedido)
        textos: list[str] = []
        final: dict | None = None
        t0 = time.monotonic()
        try:
            async with (self._sem_fundo if pedido.fundo else self._sem):
                async with asyncio.timeout(pedido.timeout_seg or self._timeout):
                    # Consome o gerador do SDK até o fim (sair no meio deixa o subprocesso mal encerrado).
                    async for m in query(prompt=pedido.prompt, options=self._opcoes(pedido, stream=True)):
                        if isinstance(m, StreamEvent):
                            ev = m.event
                            if (m.parent_tool_use_id is None and ev.get("type") == "content_block_delta"
                                    and ev.get("delta", {}).get("type") == "text_delta"):
                                yield {"tipo": "texto", "delta": ev["delta"]["text"]}
                        elif isinstance(m, AssistantMessage):
                            if m.parent_tool_use_id is not None:
                                continue
                            for b in m.content:
                                nome = type(b).__name__
                                if nome == "TextBlock":
                                    textos.append(b.text)
                                elif nome == "ToolUseBlock":
                                    yield {"tipo": "atividade", "ferramenta": b.name,
                                           "detalhe": descrever_ferramenta(b.name, b.input or {})}
                        elif type(m).__name__ == "RateLimitEvent":
                            _registrar_limite(m.rate_limit_info)
                        elif isinstance(m, ResultMessage) and final is None:
                            uso = _uso_de(m)
                            if m.is_error:
                                erro = "; ".join(m.errors or []) or (m.result or m.subtype)
                                _fechar_job(job_id, uso, erro)
                                final = {"tipo": "erro", "mensagem": mensagem_amigavel(erro), "job_id": job_id}
                            else:
                                _fechar_job(job_id, uso)
                                texto = "\n\n".join(t for t in textos if t.strip()) or (m.result or "")
                                final = {"tipo": "fim", "texto": texto, "final": m.result or texto,
                                         "session_id": m.session_id,
                                         "estruturado": m.structured_output, "job_id": job_id,
                                         "uso": uso.__dict__ | {"total_tokens": uso.total_tokens}}
        except asyncio.CancelledError:
            if final is None:
                _fechar_job(job_id, Uso(duracao_ms=int((time.monotonic() - t0) * 1000)), "interrompido", "cancelado")
            raise
        except Exception as exc:  # noqa: BLE001 — qualquer falha do CLI vira evento de erro
            if final is None:
                msg = str(exc) if not isinstance(exc, TimeoutError) else "Tempo esgotado esperando o Claude."
                _fechar_job(job_id, Uso(duracao_ms=int((time.monotonic() - t0) * 1000)), msg)
                final = {"tipo": "erro", "mensagem": mensagem_amigavel(msg), "job_id": job_id}
        if final is None:
            _fechar_job(job_id, Uso(duracao_ms=int((time.monotonic() - t0) * 1000)), "sem resultado")
            final = {"tipo": "erro", "mensagem": "O Claude encerrou sem resposta.", "job_id": job_id}
        yield final

    async def executar(self, pedido: Pedido) -> Resultado:
        fim: dict | None = None
        async for ev in self.transmitir(pedido):
            if ev["tipo"] == "erro":
                raise ErroClaude(ev["mensagem"])
            if ev["tipo"] == "fim":
                fim = ev
        assert fim is not None
        u = fim["uso"]
        return Resultado(
            texto=fim["texto"], estruturado=fim["estruturado"], session_id=fim["session_id"],
            uso=Uso(**{k: u[k] for k in Uso.__dataclass_fields__}), job_id=fim["job_id"], final=fim.get("final") or fim["texto"],
        )


# --------------------------------------------------------------------------------------------
# Runner falso para testes (zero tokens)
# --------------------------------------------------------------------------------------------


class FakeRunner:
    """Responde com saídas pré-programadas por papel. Registra os pedidos recebidos."""

    def __init__(self, respostas: dict[str, Callable[[Pedido], Any]] | None = None):
        self.respostas = respostas or {}
        self.pedidos: list[Pedido] = []

    async def transmitir(self, pedido: Pedido) -> AsyncIterator[dict]:
        self.pedidos.append(pedido)
        saida = self.respostas.get(pedido.papel, lambda p: "ok")(pedido)
        if isinstance(saida, Exception):
            yield {"tipo": "erro", "mensagem": str(saida), "job_id": None}
            return
        texto = saida if isinstance(saida, str) else json.dumps(saida, ensure_ascii=False)
        for i in range(0, len(texto), 40):
            yield {"tipo": "texto", "delta": texto[i:i + 40]}
        yield {"tipo": "fim", "texto": texto, "session_id": "sessao-fake",
               "estruturado": None if isinstance(saida, str) else saida, "job_id": None,
               "uso": Uso().__dict__ | {"total_tokens": 0}}

    async def executar(self, pedido: Pedido) -> Resultado:
        fim = None
        async for ev in self.transmitir(pedido):
            if ev["tipo"] == "erro":
                raise ErroClaude(ev["mensagem"])
            if ev["tipo"] == "fim":
                fim = ev
        return Resultado(texto=fim["texto"], estruturado=fim["estruturado"], session_id=fim["session_id"],
                         uso=Uso(), job_id=None, final=fim["texto"])


_runner: Runner | None = None


def obter_runner() -> Runner:
    global _runner
    if _runner is None:
        _runner = SdkRunner()
    return _runner


def definir_runner(r: Runner | None) -> None:
    global _runner
    _runner = r
