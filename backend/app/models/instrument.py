"""Modelo de instrumento negociable.

Los campos salen de lo que devuelve de verdad reqMatchingSymbols, verificado
contra DUN684545 el 04/08/2026 con scripts/sondea_instrumentos.py.

El identificador que importa es con_id, no symbol. Una busqueda de "AMZN"
devuelve cinco cotizaciones distintas de la misma empresa: NASDAQ en dolares,
MEXI en pesos, TSE en dolares canadienses, EBS en francos y LSEETF en libras.
El ticker no identifica nada por si solo; el conId si, y es lo que hay que
pasar despues para pedir precio o para cursar una orden.
"""

from pydantic import BaseModel, Field


class Instrument(BaseModel):
    """Un instrumento localizado en la busqueda."""

    con_id: int = Field(..., description="Identificador unico de IB")
    symbol: str = Field(..., description="Ticker, p. ej. AMZN")
    name: str = Field("", description="Nombre del emisor, p. ej. AMAZON.COM INC")
    sec_type: str = Field(..., description="Tipo IB: STK cubre acciones y ETFs")
    currency: str = Field(..., description="Divisa en que cotiza")
    exchange: str = Field("", description="Mercado principal, p. ej. NASDAQ")