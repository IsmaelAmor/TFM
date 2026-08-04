"""
sondea_ordenes_envio.py — Que ocurre de verdad al ENVIAR una orden (T36).

En T35 sondeamos whatIfOrder, que no deja rastro. Esto es lo contrario:
aqui se envian ordenes DE VERDAD contra la cuenta paper DUN684545. Dejan
posiciones y aparecen en el historial. Por eso el script pide confirmacion
antes de empezar.

Preguntas que este script tiene que responder, y que determinan la forma
del endpoint POST /api/orders:

  1. Que secuencia exacta de estados recorre una MKT que cruza, y en que
     orden llegan los eventos (status, fill, commissionReport). Si la
     comision llega DESPUES del fill, el endpoint no puede prometerla.
  2. Si un rechazo posterior al envio aparece en trade.log. Si aparece,
     leer el log es mas limpio que la escucha de errorEvent de T35.
  3. Que identificador sirve para la URL del recurso: orderId (lo asigna
     el cliente, se reinicia) o permId (lo asigna IB, sobrevive).
  4. Si openTrades() recupera una orden viva tras reconectar con el mismo
     clientId, o si hace falta reqAllOpenOrders(). Esto decide si el
     backend puede reiniciarse sin perder de vista lo que hay en el aire.
  5. Como se ve una cancelacion: que estado final y con que evento.

Ejecutar desde ~/TFM/backend con el venv activado, el Gateway arrancado y
el mercado ABIERTO (15:30-22:00 hora de Madrid para valores USA). Con el
mercado cerrado la MKT se queda dormida y no se ve ni la mitad.

    python scripts/sondea_ordenes_envio.py

clientId 74: el 75 lo usa sondea_ordenes.py, el 76 instrumentos, el 77
divisas y el 99 compara_posiciones.py. IB no admite dos conexiones con el
mismo clientId.
"""

import os
import time
from datetime import datetime

from dotenv import load_dotenv
from ib_async import IB, LimitOrder, MarketOrder, Stock

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))
CLIENT_ID = 74

SIMBOLO = "AMZN"
CANTIDAD = 1              # una accion: ~250 USD, ruido despreciable en la cuenta
CANTIDAD_ABSURDA = 500_000  # para provocar el rechazo por margen

ib = IB()
T0 = time.perf_counter()


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------

def separador(titulo):
    print("\n" + "=" * 70)
    print(titulo)
    print("=" * 70)


def marca(texto):
    """Imprime con el tiempo transcurrido desde el ultimo reloj a cero.

    El objetivo del script no es solo ver QUE llega, sino CUANDO. La
    diferencia entre que la comision llegue a la vez que el fill o dos
    segundos despues cambia lo que puede devolver el endpoint.
    """
    print(f"  [{time.perf_counter() - T0:6.2f}s] {texto}")


def reloj_a_cero():
    global T0
    T0 = time.perf_counter()


def campos(obj, saltar=("contract",)):
    """Devuelve los atributos de datos de un objeto de ib_async.

    Mismo helper que en las sondas anteriores: preguntamos al objeto real
    que campos trae y con que nombre exacto, en vez de fiarnos de la
    documentacion.
    """
    salida = {}
    for nombre in dir(obj):
        if nombre.startswith("_") or nombre in saltar:
            continue
        valor = getattr(obj, nombre)
        if callable(valor):
            continue
        salida[nombre] = valor
    return salida


def volcar(obj, sangria="    ", saltar=("contract",), solo_no_vacios=False):
    for k, v in sorted(campos(obj, saltar=saltar).items()):
        if solo_no_vacios and v in ("", 0, 0.0, [], None, False):
            continue
        print(f"{sangria}{k} = {v!r}")


def al_error(reqId, errorCode, errorString, contract):
    """Escucha de errorEvent.

    En T35 descubrimos que IB no lanza excepciones al rechazar: el rechazo
    viaja por aqui. Se deja puesto todo el script para no perderse nada.
    """
    marca(f"errorEvent  reqId={reqId} code={errorCode} :: {errorString}")


# ----------------------------------------------------------------------
# Vigilancia de un Trade
# ----------------------------------------------------------------------

def vigilar(trade, etiqueta):
    """Engancha los eventos del Trade para ver el ORDEN de llegada.

    Es la parte importante del script. El bucle de sondeo de mas abajo ve
    los cambios de estado, pero no distingue si status y fill llegaron
    juntos o separados. Los eventos si.
    """

    def _status(t):
        marca(f"[{etiqueta}] statusEvent -> {t.orderStatus.status}")

    def _fill(t, fill):
        marca(
            f"[{etiqueta}] fillEvent -> {fill.execution.shares} @ "
            f"{fill.execution.price} (execId={fill.execution.execId})"
        )

    def _comision(t, fill, report):
        marca(
            f"[{etiqueta}] commissionReportEvent -> "
            f"commission={report.commission} {report.currency} "
            f"realizedPNL={report.realizedPNL}"
        )

    def _lleno(t):
        marca(f"[{etiqueta}] filledEvent (orden completada)")

    def _cancelado(t):
        marca(f"[{etiqueta}] cancelEvent")

    trade.statusEvent += _status
    trade.fillEvent += _fill
    trade.commissionReportEvent += _comision
    trade.filledEvent += _lleno
    trade.cancelEvent += _cancelado


def seguir(trade, segundos=20, margen_tras_final=5):
    """Sondea el Trade e imprime cada cambio de estado.

    Cuando isDone() se pone a True NO se corta: se siguen escuchando unos
    segundos mas. Esa es justamente la pregunta 1 del script, si llega
    algo (la comision) despues de que la orden se de por terminada.
    """
    fin = time.time() + segundos
    limite_tras_final = None
    ultimo = None

    while time.time() < fin:
        ib.waitOnUpdate(timeout=1)

        e = trade.orderStatus
        actual = (e.status, e.filled, e.remaining, e.avgFillPrice)
        if actual != ultimo:
            marca(
                f"orderStatus: status={e.status} filled={e.filled} "
                f"remaining={e.remaining} avgFillPrice={e.avgFillPrice}"
            )
            ultimo = actual

        if trade.isDone():
            if limite_tras_final is None:
                marca(f"isDone() = True (status={e.status})")
                limite_tras_final = time.time() + margen_tras_final
            elif time.time() > limite_tras_final:
                break

    marca("fin del seguimiento")


def volcar_trade(trade, titulo):
    print(f"\n  --- {titulo}")
    print("  trade.order:")
    volcar(trade.order, sangria="      ", solo_no_vacios=True)
    print("  trade.orderStatus:")
    volcar(trade.orderStatus, sangria="      ")
    print("  trade.log (historial de estados que guarda ib_async):")
    for entrada in trade.log:
        print(
            f"      {entrada.time} status={entrada.status!r} "
            f"errorCode={entrada.errorCode!r} message={entrada.message!r}"
        )
    print(f"  trade.fills: {len(trade.fills)}")
    for f in trade.fills:
        print("      .execution:")
        volcar(f.execution, sangria="          ", solo_no_vacios=True)
        print("      .commissionReport:")
        volcar(f.commissionReport, sangria="          ")


# ----------------------------------------------------------------------
def main():
    print("\nEste script ENVIA ordenes reales a la cuenta paper.")
    print(f"Comprara {CANTIDAD} {SIMBOLO} a mercado y dejara la posicion abierta.")
    if input("Escribe SI para continuar: ").strip().upper() != "SI":
        print("Cancelado.")
        return

    # RequestTimeout viene a 0 en ib_async, que significa esperar para
    # siempre. Con el mercado cerrado eso cuelga el script sin decir por
    # que. En el backend no pasa porque todo va con asyncio.wait_for.
    ib.RequestTimeout = 20
    ib.errorEvent += al_error

    print(f"\nConectando a {HOST}:{PORT} (clientId={CLIENT_ID})...")
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    except Exception as e:
        print(f"  ERROR: {e}")
        print("  Gateway arrancado y logueado? Puerto correcto? clientId libre?")
        return

    print(f"  Conectado. serverVersion={ib.client.serverVersion()} "
          f"cuentas={ib.managedAccounts()}")

    # Datos retrasados, igual que en T34: la cuenta paper no tiene
    # suscripcion en tiempo real.
    ib.reqMarketDataType(3)

    contrato = Stock(SIMBOLO, "SMART", "USD")
    ib.qualifyContracts(contrato)
    print(f"  Contrato resuelto: conId={contrato.conId} "
          f"exchange={contrato.exchange} primary={contrato.primaryExchange}")

    ticker = ib.reqTickers(contrato)[0]
    referencia = next(
        (p for p in (ticker.last, ticker.close, ticker.marketPrice())
         if p and p == p and p > 0),
        None,
    )
    print(f"  Precio de referencia (delayed): {referencia}")
    if not referencia:
        print("  Sin precio no se puede calcular la limitada. Abortando.")
        ib.disconnect()
        return

    # ------------------------------------------------------------------
    separador("1) MKT BUY que cruza: secuencia completa de eventos")
    # La pregunta: en que orden llegan status, fill y commissionReport, y
    # cuanto tarda cada uno desde el placeOrder.
    orden = MarketOrder("BUY", CANTIDAD)
    reloj_a_cero()
    trade_mkt = ib.placeOrder(contrato, orden)
    marca("placeOrder ha devuelto")
    marca(f"orderId={trade_mkt.order.orderId} permId={trade_mkt.order.permId} "
          f"status inicial={trade_mkt.orderStatus.status!r}")
    vigilar(trade_mkt, "MKT")
    seguir(trade_mkt, segundos=25)
    volcar_trade(trade_mkt, "Trade MKT ya terminado")
    marca(f"permId despues de ejecutarse = {trade_mkt.order.permId}")

    # ------------------------------------------------------------------
    separador("2) LMT que NO cruza: orden viva, reconexion y cancelacion")
    # Limitada un 30% por debajo del mercado: no se ejecutara. Sirve para
    # ver el estado de una orden en el aire y para probar si sobrevive a
    # un reinicio del backend.
    precio_lejano = round(referencia * 0.70, 2)
    reloj_a_cero()
    trade_lmt = ib.placeOrder(contrato, LimitOrder("BUY", CANTIDAD, precio_lejano))
    marca(f"placeOrder LMT a {precio_lejano} USD (mercado ~{referencia})")
    vigilar(trade_lmt, "LMT")
    seguir(trade_lmt, segundos=10)

    print("\n  openTrades() con la conexion actual:")
    for t in ib.openTrades():
        print(f"      orderId={t.order.orderId} permId={t.order.permId} "
              f"{t.order.action} {t.order.totalQuantity} {t.contract.symbol} "
              f"status={t.orderStatus.status}")

    print("\n  --- Desconectando y reconectando con el MISMO clientId ---")
    # Simula el reinicio de uvicorn. Si openTrades() vuelve a traer la
    # orden, el backend puede recuperarse solo; si no, hay que llamar a
    # reqAllOpenOrders() al arrancar.
    ib.disconnect()
    time.sleep(3)
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    ib.sleep(3)

    print(f"  Reconectado. openTrades(): {len(ib.openTrades())} elementos")
    for t in ib.openTrades():
        print(f"      orderId={t.order.orderId} permId={t.order.permId} "
              f"status={t.orderStatus.status}")

    print(f"  openOrders(): {len(ib.openOrders())} elementos")
    print("  reqAllOpenOrders() (incluye ordenes de otros clientId):")
    # Verificado el 04/08/2026: reqAllOpenOrders() devuelve objetos Trade,
    # igual que openTrades(), no objetos Order. El campo esta en t.order.
    for t in ib.reqAllOpenOrders():
        print(f"      orderId={t.order.orderId} permId={t.order.permId} "
              f"clientId={t.order.clientId} {t.order.action} "
              f"{t.order.totalQuantity} {t.contract.symbol}")

    vivas = [t for t in ib.openTrades()
             if t.contract.symbol == SIMBOLO and not t.isDone()]
    if vivas:
        objetivo = vivas[0]
        print(f"\n  Cancelando orderId={objetivo.order.orderId}...")
        reloj_a_cero()
        vigilar(objetivo, "CANCEL")
        ib.cancelOrder(objetivo.order)
        seguir(objetivo, segundos=15)
        volcar_trade(objetivo, "Trade LMT tras cancelar")
    else:
        print("  No queda ninguna orden viva que cancelar (revisar por que).")

    # ------------------------------------------------------------------
    separador("3) Rechazo POSTERIOR al envio: aparece en trade.log?")
    # Cantidad imposible para el efectivo de la cuenta. En T35 el rechazo
    # llego como error 201 por errorEvent y despues del OrderState. La
    # pregunta ahora: ib_async lo anota ademas en trade.log, que seria una
    # fuente mucho mas limpia que una escucha global de errores.
    # Se manda como limitada lejana: si por lo que fuera IB la aceptase,
    # no cruzaria y la cancelamos.
    reloj_a_cero()
    trade_malo = ib.placeOrder(
        contrato, LimitOrder("BUY", CANTIDAD_ABSURDA, precio_lejano)
    )
    marca(f"placeOrder de {CANTIDAD_ABSURDA} titulos enviado")
    vigilar(trade_malo, "RECHAZO")
    seguir(trade_malo, segundos=15)
    volcar_trade(trade_malo, "Trade que deberia estar rechazado")

    if not trade_malo.isDone():
        print("  IB no lo ha rechazado. Cancelando para no dejarlo vivo.")
        ib.cancelOrder(trade_malo.order)
        ib.sleep(5)

    # ------------------------------------------------------------------
    separador("4) Limpieza: no dejar nada en el aire")
    pendientes = [t for t in ib.openTrades() if not t.isDone()]
    for t in pendientes:
        print(f"  Cancelando orderId={t.order.orderId} ({t.orderStatus.status})")
        ib.cancelOrder(t.order)
    if pendientes:
        ib.sleep(5)
    print(f"  Ordenes vivas al terminar: "
          f"{len([t for t in ib.openTrades() if not t.isDone()])}")
    print(f"  Recuerda: la compra de {CANTIDAD} {SIMBOLO} sigue en cartera.")

    ib.disconnect()
    print(f"\nDesconectado. {datetime.now():%H:%M:%S}")


if __name__ == "__main__":
    main()
