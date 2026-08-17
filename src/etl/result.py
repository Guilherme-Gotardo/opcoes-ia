"""Resultado estruturado comum aos coletores, sem dependência de I/O."""
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class EstadoColeta(StrEnum):
    SUCESSO = "sucesso"
    PARCIAL = "parcial"
    FALHA = "falha"
    BLOQUEADO = "bloqueado"
    PULADO = "pulado"


class EstadoAlvo(StrEnum):
    SUCESSO = "sucesso"
    FALHA = "falha"
    BLOQUEADO = "bloqueado"
    NAO_EXECUTADO = "nao_executado"


@dataclass(frozen=True)
class DetalheAlvo:
    ticker: str
    estado: EstadoAlvo
    registros_persistidos: int = 0
    codigo_motivo: str | None = None
    detalhe: str | None = None
    tentado: bool = True

    def __post_init__(self) -> None:
        if not self.ticker.strip():
            raise ValueError("ticker do resultado não pode ser vazio")
        if self.registros_persistidos < 0:
            raise ValueError("registros_persistidos não pode ser negativo")
        if self.estado != EstadoAlvo.SUCESSO and self.registros_persistidos:
            raise ValueError("alvo sem sucesso não pode ter registros persistidos")
        if self.estado == EstadoAlvo.NAO_EXECUTADO and self.tentado:
            raise ValueError("alvo não executado não pode estar marcado como tentado")

    def como_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "estado": self.estado.value,
            "registros_persistidos": self.registros_persistidos,
            "codigo_motivo": self.codigo_motivo,
            "detalhe": self.detalhe,
            "tentado": self.tentado,
        }


@dataclass(frozen=True)
class ResultadoColeta:
    coletor: str
    fonte: str
    estado: EstadoColeta
    detalhes: tuple[DetalheAlvo, ...] = ()
    motivo: str | None = None
    contexto: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.coletor.strip() or not self.fonte.strip():
            raise ValueError("coletor e fonte são obrigatórios")
        if self.estado == EstadoColeta.PULADO and self.detalhes:
            raise ValueError("coleta pulada não pode conter alvos")
        if self.estado != EstadoColeta.PULADO and not self.detalhes:
            raise ValueError("coleta executada precisa conter detalhe por alvo")
        object.__setattr__(self, "contexto", MappingProxyType(dict(self.contexto)))

    @classmethod
    def de_detalhes(
        cls,
        coletor: str,
        fonte: str,
        detalhes: list[DetalheAlvo] | tuple[DetalheAlvo, ...],
        *,
        contexto: Mapping[str, Any] | None = None,
    ) -> "ResultadoColeta":
        itens = tuple(detalhes)
        if not itens:
            raise ValueError("use ResultadoColeta.pulado() quando não houver alvos")
        estados = {item.estado for item in itens}
        if estados == {EstadoAlvo.SUCESSO}:
            estado = EstadoColeta.SUCESSO
        elif estados == {EstadoAlvo.BLOQUEADO}:
            estado = EstadoColeta.BLOQUEADO
        elif EstadoAlvo.SUCESSO in estados:
            estado = EstadoColeta.PARCIAL
        else:
            estado = EstadoColeta.FALHA
        return cls(coletor, fonte, estado, itens, contexto=contexto or {})

    @classmethod
    def pulado(
        cls,
        coletor: str,
        fonte: str,
        motivo: str,
        *,
        contexto: Mapping[str, Any] | None = None,
    ) -> "ResultadoColeta":
        if not motivo:
            raise ValueError("resultado pulado exige motivo")
        return cls(
            coletor, fonte, EstadoColeta.PULADO, motivo=motivo,
            contexto=contexto or {},
        )

    @property
    def alvos_total(self) -> int:
        return len(self.detalhes)

    @property
    def alvos_tentados(self) -> int:
        return sum(item.tentado for item in self.detalhes)

    @property
    def alvos_com_sucesso(self) -> int:
        return sum(item.estado == EstadoAlvo.SUCESSO for item in self.detalhes)

    @property
    def alvos_falhos(self) -> int:
        return sum(item.estado == EstadoAlvo.FALHA for item in self.detalhes)

    @property
    def alvos_nao_executados(self) -> int:
        return sum(item.estado == EstadoAlvo.NAO_EXECUTADO for item in self.detalhes)

    @property
    def registros_persistidos(self) -> int:
        return sum(item.registros_persistidos for item in self.detalhes)

    def como_dict(self) -> dict[str, Any]:
        return {
            "coletor": self.coletor,
            "fonte": self.fonte,
            "estado": self.estado.value,
            "alvos_total": self.alvos_total,
            "alvos_tentados": self.alvos_tentados,
            "alvos_com_sucesso": self.alvos_com_sucesso,
            "alvos_falhos": self.alvos_falhos,
            "alvos_nao_executados": self.alvos_nao_executados,
            "registros_persistidos": self.registros_persistidos,
            "motivo": self.motivo,
            "contexto": dict(self.contexto),
            "detalhes": [item.como_dict() for item in self.detalhes],
        }
