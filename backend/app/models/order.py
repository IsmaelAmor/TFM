"""Modelos de validacion de ordenes (T35).

Estructuras verificadas contra DUN684545 el 04/08/2026 con
scripts/sondea_ordenes.py. Dos hallazgos las condicionan:

  1. OrderState.status vale 'PreSubmitted' TAMBIEN en las ordenes que IB
     rechaza. El rechazo no viaja en el OrderState: llega como error 201
     por el canal de eventos. Fiarse de status daria por buena una orden
     tumbada, asi que aqui el veredicto del broker es un booleano propio
     calculado a partir del error, no una copia de status.
  2. IB usa 1.7976931348623157e+308 (el maximo de un double) para decir
     "sin dato" en commission, minCommission y maxCommission. Todos los
     importes opcionales viajan como None.

El instrumento se identifica por con_id y nunca por ticker: "AMZN" son
cinco cotizaciones en cinco divisas y el ticker no elige entre ellas.
"""

from typing import Literal
from datetime import datetime
from pydantic import BaseModel, Field, model_validator


class OrderRequest(BaseModel):
    """Orden que el usuario quiere comprobar antes de enviarla.

    Solo MKT y LMT por decision de alcance. IB admite decenas de tipos
    (stop, trailing, algoritmicas), pero ninguno aporta nada a la gestion
    de una cartera y todos habria que probarlos uno a uno.
    """

    con_id: int = Field(..., gt=0, description="Identificador del contrato en IB")
    action: Literal["BUY", "SELL"]
    order_type: Literal["MKT", "LMT"] = "MKT"
    quantity: float = Field(..., gt=0, description="Numero de titulos")
    limit_price: float | None = Field(None, gt=0, description="Solo en ordenes LMT")

    @model_validator(mode="after")
    def _coherencia(self):
        """Un tipo de orden y su precio no son campos independientes.

        Se valida aqui y no en el servicio para que la incoherencia salga
        como un 422 con el campo senalado, que es lo que el frontend puede
        pintar junto al input. En el servicio saldria como un 400 generico.
        """
        if self.order_type == "LMT" and self.limit_price is None:
            raise ValueError("Una orden limitada necesita limit_price")
        if self.order_type == "MKT" and self.limit_price is not None:
            raise ValueError("Una orden de mercado no lleva limit_price")
        return self


class BrokerPreview(BaseModel):
    """Lo que contesta IB a un whatIfOrder, ya traducido.

    Es un modelo propio y no un OrderState para que RNF-08 siga siendo
    cierto: ningun objeto de ib_async sale del paquete broker.
    """

    accepted_by_broker: bool = Field(
        ..., description="False si IB rechazo la orden o no contesto"
    )
    broker_status: str = Field("", description="status crudo de IB, informativo")
    broker_message: str = Field("", description="Motivo del rechazo, si lo hubo")
    error_code: int | None = Field(None, description="Codigo de error de IB")
    warning_text: str = Field("", description="Advertencia de IB sin rechazo")

    commission: float | None = Field(None, description="Comision estimada por IB")
    commission_currency: str = Field("", description="Divisa de la comision")

    # Informativos: son la magnitud del apalancamiento que la aplicacion
    # NO ofrece. Se exponen porque explican por que IB aceptaria ordenes
    # que nosotros rechazamos, y eso hay que poder ensenarlo.
    init_margin_change: float | None = None
    maint_margin_change: float | None = None
    equity_with_loan_change: float | None = None

    con_id: int = 0
    symbol: str = ""
    currency: str = ""
    exchange: str = ""


class OrderValidation(BaseModel):
    """Veredicto completo sobre una orden, antes de enviarla.

    Devuelve el porque y no solo el si o el no: los motivos y los avisos
    son texto para ensenar al usuario, y las cifras intermedias permiten
    que compruebe la cuenta por su cuenta. Un validador que solo dice "no"
    no sirve para decidir.
    """

    accepted: bool = Field(..., description="True si la orden puede enviarse")
    reasons: list[str] = Field(default_factory=list, description="Motivos del rechazo")
    warnings: list[str] = Field(default_factory=list, description="Avisos sin rechazo")

    # Que se ha validado
    con_id: int
    symbol: str
    action: str
    order_type: str
    quantity: float
    limit_price: float | None = None

    # Con que precio se ha calculado
    reference_price: float | None = Field(None, description="Precio usado en el calculo")
    price_source: str = Field("", description="ask, bid, last, close o limite")
    buffer_pct: float = Field(0.0, description="Colchon aplicado sobre el precio")

    # Cuentas, en divisa del instrumento y en divisa base
    currency: str = ""
    base_currency: str = ""
    fx_rate: float = 1.0
    estimated_cost: float = Field(0.0, description="Coste estimado en su divisa")
    estimated_cost_base: float = Field(0.0, description="Coste estimado en divisa base")
    commission: float | None = None
    commission_currency: str = ""
    commission_base: float = 0.0
    total_base: float = Field(0.0, description="Coste mas comision, en divisa base")

    # Contra que se ha comparado
    cash_available: float = Field(0.0, description="Efectivo, en divisa base")
    cash_after: float = Field(0.0, description="Efectivo estimado tras la orden")
    position_quantity: float = Field(0.0, description="Titulos en cartera del valor")

    broker: BrokerPreview | None = None

class OrderResult(BaseModel):
    """Resultado de enviar una orden al mercado (T36).

    Reune tres cosas en un solo cuerpo: el veredicto previo (validation),
    la identidad que IB asigna a la orden y el estado en que quedo tras el
    envio. El frontend decide que pintar mirando 'estado', no el codigo
    HTTP: la peticion siempre es correcta, lo que varia es el desenlace.

    'estado' es un vocabulario propio y no el status crudo de IB. IB
    distingue Submitted de PreSubmitted y expone Inactive, ApiCancelled y
    demas; nada de eso le dice al usuario si su orden se ejecuto, sigue
    viva o fue rechazada. La traduccion vive en mapper.estado_de_orden.
    """

    estado: Literal[
        "ejecutada", "activa", "rechazada", "cancelada", "no_enviada"
    ] = Field(..., description="Desenlace en lenguaje de la aplicacion")

    order_id: int = Field(0, description="Id de la orden en la sesion (para el GET)")
    perm_id: int = Field(0, description="Id global y estable que asigna IB")

    con_id: int
    symbol: str = ""
    action: str
    order_type: str
    quantity: float
    limit_price: float | None = None

    filled_quantity: float = Field(0.0, description="Titulos ya ejecutados")
    remaining_quantity: float = Field(0.0, description="Titulos pendientes")
    avg_fill_price: float | None = Field(None, description="Precio medio de ejecucion")

    # Comision REAL de la ejecucion, no la estimada del whatIfOrder.
    # Verificado el 04/08/2026 que llega con el fill, asi que en una MKT que
    # cruza ya esta aqui. En una limitada viva no hay ejecucion y es None.
    commission: float | None = None
    commission_currency: str = ""

    broker_status: str = Field("", description="status crudo de IB, informativo")
    broker_message: str = Field("", description="Motivo del rechazo, si lo hubo")
    error_code: int | None = None

    # El veredicto previo por el que la orden paso antes de enviarse. Se
    # incluye tambien cuando todo salio bien: lleva el desglose de coste y
    # comision que el formulario de compra necesita para el resumen final.
    validation: OrderValidation | None = None

    submitted_at: datetime | None = None