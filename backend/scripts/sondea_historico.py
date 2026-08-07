"""
sondea_historico.py — Que devuelve de verdad reqHistoricalData, antes de
escribir el modulo de riesgo (Fase 5, T44+).

Mismo espiritu que los sondeos anteriores: no nos fiamos de la
documentacion, le preguntamos al objeto real. El modulo de riesgo calcula
volatilidad, drawdown y correlaciones sobre una serie de precios de 1 ano
diario (~252 barras); antes de codificar nada hay que saber la forma exacta
de esa serie.

Preguntas que este sondeo tiene que contestar:

  1. Que campos trae cada BarData y de que TIPO es 'date' con barSize
     '1 day': date, datetime o str. De eso depende como se calculan los
     rendimientos diarios y si hay que parsear fechas.
  2. Si reqHistoricalData funciona con dato RETRASADO (IB_MARKET_DATA_TYPE=3),
     lo unico que tiene DUN684545. El historico no suele depender de
     suscripcion en tiempo real, pero hay que verlo, no suponerlo.
  3. Que whatToShow es el correcto para acciones. Se comparan TRADES y
     ADJUSTED_LAST sobre el mismo instrumento: ADJUSTED_LAST corrige splits
     y dividendos, y usar el equivocado mete ruido en la volatilidad. Es
     una decision que hay que justificar en la memoria.
  4. Cuantas barras devuelve al pedir '1 Y' y como trata festivos y fines
     de semana (los huecos afectan al calculo de rendimientos).
  5. A que ritmo se puede pedir. reqHistoricalData tiene pacing estricto en
     IB, mas agresivo que el 1 req/s de reqMatchingSymbols. El modulo pedira
     historico de N posiciones seguidas: hay que medir el ritmo antes de
     escribir el bucle. Se lanzan 3 peticiones cronometradas para verlo.

Usa clientId 82: el 1 lo ocupa uvicorn, el 74-77 y 80-81 los otros sondeos
y el 99 compara_posiciones. Puede correr con uvicorn levantado.

Ejecutar desde backend/ con el venv activado y el Gateway arrancado:
    python scripts/sondea_historico.py
"""

import os
import time
from datetime import datetime

from dotenv import load_dotenv
from ib_async import IB, Stock

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))
TIPO_DATO = int(os.getenv("IB_MARKET_DATA_TYPE", "3"))
CLIENT_ID = 82

# Tres instrumentos para la prueba de pacing: son los que el modulo de
# riesgo pediria en fila al analizar una cartera de varias posiciones.
SIMBOLOS = ["AAPL", "MSFT", "AMZN"]

CODIGOS_RUIDO = {2104, 2106, 2107, 2108, 2119, 2158, 10167}


def separador(titulo):
    print()
    print("=" * 72)
    print(titulo)
    print("=" * 72)


def pedir(ib, contrato, what_to_show, etiqueta):
    """Una peticion de historico, cronometrada, sin abortar el sondeo."""
    t0 = time.monotonic()
    try:
        barras = ib.reqHistoricalData(
            contrato,
            endDateTime="",          # vacio = hasta ahora
            durationStr="1 Y",
            barSizeSetting="1 day",
            whatToShow=what_to_show,
            useRTH=True,             # solo horario regular de negociacion
            formatDate=1,            # 1 = fecha legible; 2 = epoch
        )
        dt = time.monotonic() - t0
        print(f"  {etiqueta}: {len(barras)} barras en {dt:.2f}s "
              f"(whatToShow={what_to_show})")
        return barras
    except Exception as e:  # noqa: BLE001
        dt = time.monotonic() - t0
        print(f"  {etiqueta}: EXCEPCION en {dt:.2f}s -> "
              f"{type(e).__name__}: {e or '(sin mensaje)'}")
        return []


def main():
    ib = IB()

    def al_error(*args):
        codigo = args[1] if len(args) > 1 else None
        mensaje = args[2] if len(args) > 2 else ""
        if codigo in CODIGOS_RUIDO:
            return
        print(f"    [IB] codigo={codigo}: {mensaje}")

    ib.errorEvent += al_error

    print(f"Conectando a {HOST}:{PORT} (clientId={CLIENT_ID})...")
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=10)
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    ib.RequestTimeout = 60  # el historico puede tardar mas que una cotizacion
    # Dato retrasado, lo unico que tiene la cuenta paper. La pregunta 2 es
    # justamente si el historico sale igual con esto puesto.
    ib.reqMarketDataType(TIPO_DATO)
    print(f"  Conectado. serverVersion={ib.client.serverVersion()} "
          f"marketDataType={TIPO_DATO}")

    # ------------------------------------------------------------------
    separador("1) Una serie de 1 ano: cuantas barras y de que forma")
    contrato = Stock(SIMBOLOS[0], "SMART", "USD")
    ib.qualifyContracts(contrato)
    barras = pedir(ib, contrato, "TRADES", f"{SIMBOLOS[0]} TRADES")

    if barras:
        b = barras[0]
        print(f"\n  Campos de una BarData:")
        for nombre in sorted(dir(b)):
            if nombre.startswith("_"):
                continue
            valor = getattr(b, nombre)
            if callable(valor):
                continue
            print(f"    {nombre:12} = {valor!r:<24} ({type(valor).__name__})")

        print(f"\n  Primera barra: date={barras[0].date!r} "
              f"close={barras[0].close!r}")
        print(f"  Ultima barra:  date={barras[-1].date!r} "
              f"close={barras[-1].close!r}")
        print(f"\n  >>> tipo de 'date' = {type(barras[0].date).__name__}")
        print(f"  >>> total de barras en 1 Y = {len(barras)} "
              f"(los dias habiles de un ano son ~252)")

        # Continuidad: si hay huecos raros ademas de fines de semana y
        # festivos, el calculo de rendimientos tiene que preverlo.
        print(f"\n  Primeras 5 fechas: {[str(x.date) for x in barras[:5]]}")

    # ------------------------------------------------------------------
    separador("2) TRADES vs ADJUSTED_LAST sobre el mismo instrumento")
    print("  Si las series difieren, hay split o dividendo en el ano y la")
    print("  eleccion de whatToShow cambia la volatilidad medida.")
    barras_adj = pedir(ib, contrato, "ADJUSTED_LAST", f"{SIMBOLOS[0]} ADJUSTED_LAST")
    if barras and barras_adj:
        t_close = barras[0].close
        a_close = barras_adj[0].close
        print(f"  Primer close  TRADES={t_close!r}  ADJUSTED_LAST={a_close!r}  "
              f"{'IGUALES' if t_close == a_close else 'DISTINTOS (hay ajuste)'}")

    # ------------------------------------------------------------------
    separador("3) Pacing: 3 peticiones seguidas, cronometradas")
    print("  Mide el ritmo real al que el modulo podra pedir historico de")
    print("  varias posiciones. Si IB frena (error 162 'pacing violation'),")
    print("  aparecera arriba y el bucle del modulo tendra que espaciar.")
    t_serie = time.monotonic()
    for i, simbolo in enumerate(SIMBOLOS, 1):
        c = Stock(simbolo, "SMART", "USD")
        ib.qualifyContracts(c)
        t_antes = time.monotonic()
        b = pedir(ib, c, "TRADES", f"[{i}/{len(SIMBOLOS)}] {simbolo}")
        print(f"      (transcurrido desde la peticion anterior: "
              f"{time.monotonic() - t_antes:.2f}s)")
    print(f"\n  Total de las {len(SIMBOLOS)} peticiones: "
          f"{time.monotonic() - t_serie:.2f}s")

    # ------------------------------------------------------------------
    separador("4) Comprobacion de seguridad: historico no deja ordenes")
    print(f"  openOrders() = {ib.openOrders()}")
    print(f"  trades()     = {ib.trades()}")

    ib.disconnect()
    print(f"\nSondeo terminado. {datetime.now():%H:%M:%S}")


if __name__ == "__main__":
    main()
