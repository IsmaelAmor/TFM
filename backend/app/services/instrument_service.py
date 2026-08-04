"""Logica de aplicacion relativa a instrumentos y precios.

Hoy es una capa fina, igual que portfolio_service en su momento. Existe
porque es donde iran las reglas que no son de IB ni de HTTP: ordenar los
resultados de busqueda por relevancia, cachear precios para no repetir
peticiones al pedir la cotizacion de las diez posiciones de la cartera, y
marcar como preferida la cotizacion que coincide con la divisa base.
"""

from app.broker import ib_gateway
from app.models.instrument import Instrument
from app.models.quote import Quote


async def search_instruments(query: str, limit: int = 20) -> list[Instrument]:
    return await ib_gateway.search_instruments(query, limit)


async def get_quote(con_id: int) -> Quote:
    return await ib_gateway.get_quote(con_id)