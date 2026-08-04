"""
sondea_ordenes.py — Que devuelve de verdad whatIfOrder, antes de escribir T35.

Mismo espiritu que compara_posiciones.py, sondea_divisas.py y
sondea_instrumentos.py: no nos fiamos de la documentacion, le preguntamos al
objeto real que campos trae y con que nombre exacto.

Preguntas que este sondeo tiene que contestar:

  1. Como se llaman HOY los campos de OrderState. La API de TWS renombro
     commission a commissionAndFees en la 10.30, asi que el nombre depende
     de la version del Gateway y no puede escribirse de memoria.
  2. Con que valor representa IB "no hay dato" en OrderState.
  3. Si whatIfOrder rechaza por si solo una orden que no cabe en la cuenta o
     si solo informa del margen. De eso depende cuanta logica hay en T35.
  4. Que una orden whatIf NO deja rastro: no debe aparecer en openOrders()
     ni en trades().
  5. Que pasa al vender lo que no se tiene. La cuenta es de margen y admite
     cortos; si IB lo acepta, el veto tendra que ponerlo nuestro codigo.

Aprendido el 04/08/2026 a base de golpes:

  - Las llamadas sincronas de ib_async pasan por IB._run, que respeta
    IB.RequestTimeout, y ese atributo vale 0 de fabrica, o sea esperar
    indefinidamente. Se fija a mano mas abajo.
  - IB NO lanza excepciones cuando rechaza algo: manda un mensaje por
    errorEvent, un canal aparte. Quien no se suscribe a ese evento solo ve
    un timeout y se queda sin saber la causa. Por eso el manejador de
    errores de aqui abajo: es la diferencia entre "no responde" y "no
    responde PORQUE el API esta en modo solo lectura".
  - Confirmado que UNSET_DOUBLE (1.7976931348623157e+308) aparece de verdad:
    es el lmtPrice de una orden de mercado. El mapper tendra que traducirlo.

Ejecutar desde backend/ con el venv activado y el Gateway arrancado:
    python scripts/sondea_ordenes.py

Requiere que el Gateway NO tenga marcado "Read-Only API" en
Configure > Settings > API > Settings. Con esa casilla puesta, todo lo de
consulta funciona y todo lo de ordenes caduca sin respuesta.

Usa clientId 75: el 1 lo ocupa uvicorn, el 76 sondea_instrumentos, el 77
sondea_divisas y el 99 compara_posiciones.
"""

import os

from dotenv import load_dotenv
from ib_async import IB, LimitOrder, MarketOrder, Stock

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))
TIPO_DATO = int(os.getenv("IB_MARKET_DATA_TYPE", "3"))
CLIENT_ID = 75

SIMBOLO = "AMZN"
CANTIDAD = 10
CANTIDAD_DESMESURADA = 100_000

# Solo sirve para construir una orden limitada cuando el mercado esta
# cerrado y no hay precio. No entra en ningun calculo.
PRECIO_FALLBACK = 220.0

# Por encima de esto no es un importe, es el centinela de "sin dato" de IB.
UMBRAL_CENTINELA = 1e300

# Codigos que IB manda como informacion rutinaria al conectar (estado de
# las granjas de datos). Se silencian para que no tapen los mensajes que si
# importan; el 10167 tambien, que es el aviso de datos retrasados y ya lo
# conocemos de T34.
CODIGOS_RUIDO = {2104, 2106, 2107, 2108, 2119, 2158, 10167}


def separador(titulo):
    print()
    print("=" * 72)
    print(titulo)
    print("=" * 72)


def anota(valor):
    """Marca los valores que no son un dato sino un hueco disfrazado."""
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return ""
    if n != n:  # nan
        return "   <-- nan (sin dato)"
    if abs(n) > UMBRAL_CENTINELA:
        return "   <-- CENTINELA de IB (sin dato)"
    return ""


def muestra_estado(estado):
    """Vuelca un OrderState entero, con el tipo real de cada campo."""
    if estado is None:
        print("  OrderState = None")
        return
    for nombre in sorted(dir(estado)):
        if nombre.startswith("_"):
            continue
        valor = getattr(estado, nombre)
        if callable(valor):
            continue
        print(f"  {nombre:24} = {valor!r:<28} ({type(valor).__name__}){anota(valor)}")


def prueba(ib, titulo, contrato, orden, cuenta):
    """Lanza un whatIf y ensena el resultado sin abortar el sondeo si falla."""
    separador(titulo)
    # La cuenta se fija explicitamente aunque solo haya una: si manana
    # hubiera dos, IB rechazaria la orden sin ella.
    orden.account = cuenta
    print(f"  Orden: {orden.action} {orden.totalQuantity} {contrato.symbol} "
          f"tipo={orden.orderType} lmtPrice={getattr(orden, 'lmtPrice', None)!r}")
    try:
        estado = ib.whatIfOrder(contrato, orden)
    except Exception as e:
        print(f"  EXCEPCION: {type(e).__name__}: {e or '(sin mensaje)'}")
        # Los mensajes de IB llegan por el canal de errores y pueden tardar
        # un instante mas que el timeout. Sin esta espera, la causa real
        # apareceria impresa dentro de la seccion siguiente.
        ib.sleep(2)
        return
    muestra_estado(estado)
    ib.sleep(1)


def main():
    ib = IB()

    def al_error(*args):
        """Imprime lo que IB tenga que decir.

        Firma variable a proposito: ib_async ha ido anadiendo parametros a
        este evento entre versiones, y un manejador con firma fija dejaria
        de recibir eventos sin avisar.
        """
        req_id = args[0] if len(args) > 0 else None
        codigo = args[1] if len(args) > 1 else None
        mensaje = args[2] if len(args) > 2 else ""
        if codigo in CODIGOS_RUIDO:
            return
        print(f"  [IB] codigo={codigo} reqId={req_id}: {mensaje}")

    ib.errorEvent += al_error

    print(f"Conectando a {HOST}:{PORT} (clientId={CLIENT_ID})...")
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=10)
    except Exception as e:
        print(f"  ERROR: {e}")
        print("  Gateway arrancado? Puerto correcto? Prueba otro CLIENT_ID.")
        return

    cuentas = ib.managedAccounts()
    cuenta = cuentas[0] if cuentas else ""
    print(f"  Conectado. Cuenta: {cuenta}  "
          f"serverVersion={ib.client.serverVersion()}")

    # ib_async trae RequestTimeout a 0, que significa esperar indefinidamente.
    ib.RequestTimeout = 20

    # ------------------------------------------------------------------
    separador("1) El contrato: que sabemos del instrumento antes de operar")
    contrato = Stock(SIMBOLO, "SMART", "USD")
    ib.qualifyContracts(contrato)
    print(f"  conId={contrato.conId}  exchange={contrato.exchange}  "
          f"primary={contrato.primaryExchange}  currency={contrato.currency}")

    detalles = ib.reqContractDetails(contrato)
    if detalles:
        d = detalles[0]
        # stockType distingue accion de ETF, cosa que secType no hace.
        print(f"  stockType={getattr(d, 'stockType', None)!r}  "
              f"minTick={getattr(d, 'minTick', None)!r}  "
              f"longName={getattr(d, 'longName', None)!r}")

    # ------------------------------------------------------------------
    separador("2) Contra que vamos a validar: efectivo y tipo de cambio")
    # El coste de comprar AMZN sale en USD y el efectivo esta en EUR. Sin
    # convertir, comparar los dos numeros no significa nada.
    base = ""
    efectivo = {}
    tipos = {}
    for v in ib.accountValues(cuenta):
        if v.tag == "NetLiquidation" and v.currency not in ("", "BASE"):
            base = v.currency
        if v.tag == "TotalCashValue" and v.currency not in ("", "BASE"):
            efectivo[v.currency] = v.value
        if v.tag == "ExchangeRate" and v.currency not in ("", "BASE"):
            tipos[v.currency] = v.value
    print(f"  divisa base = {base!r}")
    print(f"  TotalCashValue por divisa = {efectivo}")
    print(f"  ExchangeRate = {tipos}")

    # ------------------------------------------------------------------
    separador("3) Precio de referencia para construir la orden limitada")
    ib.reqMarketDataType(TIPO_DATO)
    ultimo = None
    try:
        ticker = ib.reqMktData(contrato, "", snapshot=True)
        ib.sleep(5)
        print(f"  last={ticker.last!r}  close={ticker.close!r}  "
              f"bid={ticker.bid!r}  ask={ticker.ask!r}  "
              f"marketDataType={ticker.marketDataType!r}")
        for candidato in (ticker.last, ticker.close, ticker.ask, ticker.bid):
            try:
                n = float(candidato)
            except (TypeError, ValueError):
                continue
            if n == n and n > 0:
                ultimo = n
                break
    except Exception as e:
        print(f"  EXCEPCION pidiendo precio: {type(e).__name__}: {e}")

    if ultimo is None:
        ultimo = PRECIO_FALLBACK
        print("  Sin precio de IB (mercado cerrado). Se usa el de reserva.")
    print(f"  precio de referencia elegido = {ultimo!r}")

    # ------------------------------------------------------------------
    separador("3bis) El API admite ordenes, o esta en modo solo lectura?")
    # reqIds pide el siguiente identificador de orden valido. Es inofensivo
    # y no envia nada, pero solo contesta si el canal de ordenes esta
    # habilitado: sirve de prueba de fuego antes de las cuatro de abajo.
    try:
        siguiente = ib.client.getReqId()
        print(f"  Siguiente orderId disponible = {siguiente}")
    except Exception as e:
        print(f"  EXCEPCION: {type(e).__name__}: {e}")
    print("  Si las pruebas 4-7 caducan sin mensaje de IB, revisa")
    print("  Configure > Settings > API > Settings > Read-Only API.")

    # ------------------------------------------------------------------
    prueba(ib, "4) whatIf de una orden de MERCADO que si cabe",
           contrato, MarketOrder("BUY", CANTIDAD), cuenta)

    # Limite un 1% por debajo: una orden que no se ejecutaria de inmediato,
    # para ver si IB calcula distinto margen que en la de mercado.
    limite = round(ultimo * 0.99, 2)
    prueba(ib, "5) whatIf de una orden LIMITADA que si cabe",
           contrato, LimitOrder("BUY", CANTIDAD, limite), cuenta)

    prueba(ib, "6) whatIf de una compra que NO cabe en la cuenta",
           contrato, MarketOrder("BUY", CANTIDAD_DESMESURADA), cuenta)

    prueba(ib, "7) whatIf de una VENTA de lo que no se tiene (corto)",
           contrato, MarketOrder("SELL", CANTIDAD_DESMESURADA), cuenta)

    # ------------------------------------------------------------------
    separador("8) Comprobacion de seguridad: whatIf no deja rastro")
    ib.sleep(2)
    print(f"  openOrders() = {ib.openOrders()}")
    print(f"  trades()     = {ib.trades()}")
    print("  (ambas listas deben estar vacias; si no, whatIf esta enviando algo)")

    ib.disconnect()
    print("\nSondeo terminado.")


if __name__ == "__main__":
    main()