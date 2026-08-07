"""Modelos del histórico de operaciones (RF-13).

Los campos salen de lo observado de verdad en un objeto Fill de ib_async,
verificado contra DUN684545 el 07/08/2026 con scripts/sondea_ejecuciones_hoy.py.
No de la documentación.

ALCANCE, y es una limitación declarada y no un descuido: la fuente es
reqExecutions, que solo sirve las ejecuciones del día en curso, contadas
desde medianoche del servidor de IB. Medido: con filtros de 1, 3, 7, 30 y
90 días atrás devuelve cero, mientras que una compra hecha ese mismo día
aparece al instante. Los filtros de fecha acotan DENTRO de la ventana, no
la amplían.

La causa no es la API sino la elección de IB Gateway: la ventana se puede
ampliar a siete días con el ajuste "Show trades for..." del Trade Log de
TWS, y el Gateway, al no tener interfaz gráfica, no puede modificarlo. Es
la contrapartida de haber elegido un cliente headless. Las vías para
superarlo (persistencia propia y Flex Web Service) van en líneas futuras.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Execution(BaseModel):
    """Una ejecución: un trozo de orden que cruzó de verdad en el mercado.

    Una orden puede producir VARIAS ejecuciones si el mercado la trocea,
    así que esto no es "una operación" sino "un cruce". La agrupación por
    orden, si hace falta, es cosa de la capa de arriba.
    """

    exec_id: str = Field(
        ...,
        description="Identificador único de la ejecución asignado por IB",
    )
    order_id: int = Field(..., description="Orden que originó esta ejecución")
    perm_id: int = Field(
        0,
        description="Identificador estable de la orden en IB; aquí sí viene poblado",
    )

    symbol: str = Field(..., description="Ticker, p. ej. AMZN")
    sec_type: str = Field("", description="Tipo IB: STK cubre acciones y ETFs")
    currency: str = Field("", description="Divisa en que cotiza el instrumento")
    exchange: str = Field("", description="Mercado donde cruzó, p. ej. ARCA")

    action: str = Field(
        ...,
        description="BUY o SELL, ya traducido del BOT/SLD que usa IB",
    )
    quantity: float = Field(..., description="Títulos cruzados en ESTA ejecución")
    price: float = Field(..., description="Precio al que cruzó, en su divisa")
    amount: float = Field(0.0, description="quantity * price, en su divisa")

    commission: float | None = Field(
        None,
        description="Comisión, o None si IB aún no la ha enviado",
    )
    commission_currency: str = Field("", description="Divisa de la comisión")

    time: datetime = Field(
        ...,
        description="Momento del cruce, en UTC tal como lo sella IB",
    )
    account_id: str = Field("", description="Cuenta a la que se imputa")


class ExecutionHistory(BaseModel):
    """Las ejecuciones del día con su contexto de alcance.

    Lleva la ventana declarada DENTRO de la respuesta y no solo en la
    documentación: un cliente que reciba una lista vacía tiene que poder
    distinguir "no has operado hoy" de "no hay datos". Una lista pelada no
    permite esa distinción, y el frontend acabaría inventándose el aviso.
    """

    account_id: str = ""
    executions: list[Execution] = Field(default_factory=list)
    window: str = Field(
        "current_day",
        description="Ventana cubierta. Hoy siempre 'current_day' (ver módulo)",
    )
    retrieved_at: datetime = Field(
        ...,
        description="Momento de la consulta, en UTC",
    )
