"""Política versionada que agrega resultados sem conhecer providers."""
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from src.etl.result import EstadoColeta, ResultadoColeta

POLICY_FILE = Path(__file__).with_name("policy.yaml")


@dataclass(frozen=True)
class FluxoPolicy:
    obrigatorias: frozenset[str]
    opcionais: frozenset[str]

    def __post_init__(self) -> None:
        repetidas = self.obrigatorias & self.opcionais
        if repetidas:
            raise ValueError(f"fontes obrigatórias e opcionais repetidas: {sorted(repetidas)}")


@dataclass(frozen=True)
class PoliticaColeta:
    versao: str
    fluxos: Mapping[str, FluxoPolicy]

    def __post_init__(self) -> None:
        if not self.versao:
            raise ValueError("política de coleta exige versão")
        object.__setattr__(self, "fluxos", MappingProxyType(dict(self.fluxos)))


@dataclass(frozen=True)
class ResultadoEtapa:
    fluxo: str
    estado: EstadoColeta
    policy_version: str
    resultados: tuple[ResultadoColeta, ...]
    fontes_ausentes: tuple[str, ...] = ()

    def como_dict(self) -> dict[str, Any]:
        return {
            "fluxo": self.fluxo,
            "estado": self.estado.value,
            "policy_version": self.policy_version,
            "fontes_ausentes": list(self.fontes_ausentes),
            "resultados": [resultado.como_dict() for resultado in self.resultados],
        }


def carregar(path: Path = POLICY_FILE) -> PoliticaColeta:
    bruto = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    fluxos = {
        nome: FluxoPolicy(
            obrigatorias=frozenset(config.get("required") or []),
            opcionais=frozenset(config.get("optional") or []),
        )
        for nome, config in (bruto.get("flows") or {}).items()
    }
    return PoliticaColeta(str(bruto.get("version") or ""), fluxos)


def agregar(
    fluxo: str,
    resultados: list[ResultadoColeta] | tuple[ResultadoColeta, ...],
    politica: PoliticaColeta | None = None,
) -> ResultadoEtapa:
    politica = politica or carregar()
    if fluxo not in politica.fluxos:
        raise ValueError(f"fluxo sem política de coleta: {fluxo}")
    regra = politica.fluxos[fluxo]
    itens = tuple(resultados)
    por_coletor = {resultado.coletor: resultado for resultado in itens}
    if len(por_coletor) != len(itens):
        raise ValueError("resultado duplicado para o mesmo coletor")

    esperadas = regra.obrigatorias | regra.opcionais
    ausentes = tuple(sorted(esperadas - por_coletor.keys()))
    obrigatorias_ausentes = regra.obrigatorias - por_coletor.keys()

    if itens and not ausentes and all(
        item.estado == EstadoColeta.PULADO and item.motivo == "universo_vazio"
        for item in itens
    ):
        estado = EstadoColeta.PULADO
    elif obrigatorias_ausentes:
        estado = EstadoColeta.FALHA
    elif any(
        por_coletor[nome].estado == EstadoColeta.FALHA
        for nome in regra.obrigatorias
    ):
        estado = EstadoColeta.FALHA
    elif any(
        por_coletor[nome].estado == EstadoColeta.BLOQUEADO
        for nome in regra.obrigatorias
    ):
        estado = EstadoColeta.BLOQUEADO
    elif ausentes or any(
        item.estado != EstadoColeta.SUCESSO for item in itens
    ):
        estado = EstadoColeta.PARCIAL
    else:
        estado = EstadoColeta.SUCESSO

    return ResultadoEtapa(
        fluxo=fluxo,
        estado=estado,
        policy_version=politica.versao,
        resultados=itens,
        fontes_ausentes=ausentes,
    )
