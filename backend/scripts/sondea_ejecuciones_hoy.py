"""
sondea_ejecuciones_hoy.py — reqExecutions solo alcanza el dia en curso? (T38)

Medido el 07/08: reqExecutions devuelve CERO con filtros de hasta 90 dias
atras, y reqCompletedOrders tambien. Pero la cuenta tiene cinco posiciones
abiertas con coste medio, asi que ejecuciones hubo. Conclusion provisional:
IB solo sirve las del dia en curso por este canal, y filtrar hacia atras no
amplia la ventana, solo acota dentro de ella.

Este script lo comprueba de la unica forma concluyente: crea una ejecucion
HOY y la busca acto seguido.

  - Si aparece: la ventana es la causa. RF-13 es implementable pero
    ACOTADO al dia en curso, y eso hay que declararlo.
  - Si no aparece: la causa esta en nuestra llamada y hay que mirar ahi
    antes de escribir el endpoint.

De paso, si aparece contesta las preguntas del sondeo original que se
quedaron sin respuesta por falta de datos: formato de execution.time, si
la comision llega poblada o tarde, y que clientId consta.

ENVIA UNA ORDEN REAL contra DUN684545: 1 titulo, ~230 USD. Pide
confirmacion antes. Requiere mercado ABIERTO (15:30-22:00 hora de Madrid);
con el mercado cerrado la orden de mercado no cruza y el script lo dice.

    python scripts/sondea_ejecuciones_hoy.py

clientId 70.
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from ib_async import IB, ExecutionFilter, MarketOrder, Stock

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))
CLIENT_ID = 70

SIMBOLO = "AMZN"
CANTIDAD = 1


def separador(titulo):
    print("\n" + "=" * 70)
    print(titulo)
    print("=" * 70)


def campos(obj, saltar=("contract",)):
    salida = {}
    for nombre in dir(obj):
        if nombre.startswith("_") or nombre in saltar:
            continue
        valor = getattr(obj, nombre)
        if callable(valor):
            continue
        salida[nombre] = valor
    return salida


def volcar(obj, sangria="    ", saltar=("contract",)):
    for k, v in sorted(campos(obj, saltar=saltar).items()):
        print(f"{sangria}{k} = {v!r}  ({type(v).__name__})")


def al_error(reqId, errorCode, errorString, contract):
    if errorCode in (2104, 2106, 2107, 2119, 2158, 10167, 2174):
        return
    print(f"  errorEvent  reqId={reqId} code={errorCode} :: {errorString}")


def resumir(res, etiqueta):
    print(f"  {etiqueta}: {len(res)} ejecuciones")
    for f in res[:10]:
        e = f.execution
        print(f"    {e.time}  {e.side} {e.shares} {f.contract.symbol} "
              f"@ {e.price}  orderId={e.orderId} clientId={e.clientId}")
    return res


def main():
    print(f"Este script COMPRA {CANTIDAD} {SIMBOLO} de verdad en DUN684545.")
    if input("Escribe SI para continuar: ").strip().upper() != "SI":
        print("Cancelado.")
        return

    ib = IB()
    ib.RequestTimeout = 30
    ib.errorEvent += al_error

    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    print(f"Conectado. Ahora: {datetime.now()}")
    ib.sleep(2)

    # ------------------------------------------------------------------
    separador("1) Linea base ANTES de operar")
    antes = resumir(ib.reqExecutions(ExecutionFilter()), "reqExecutions")

    # ------------------------------------------------------------------
    separador("2) Enviando la orden")
    contrato = Stock(SIMBOLO, "SMART", "USD")
    ib.qualifyContracts(contrato)
    trade = ib.placeOrder(contrato, MarketOrder("BUY", CANTIDAD))
    print(f"  Enviada. orderId={trade.order.orderId}")

    for _ in range(30):
        ib.sleep(1)
        if trade.isDone():
            break
    print(f"  Estado final: {trade.orderStatus.status}")
    print(f"  Ejecutado: {trade.orderStatus.filled} de {CANTIDAD}")

    if trade.orderStatus.filled == 0:
        print("\n  NO HA CRUZADO. Con el mercado cerrado este script no")
        print("  concluye nada: hay que repetirlo entre 15:30 y 22:00.")
        ib.cancelOrder(trade.order)
        ib.sleep(2)
        ib.disconnect()
        return

    # ------------------------------------------------------------------
    separador("3) reqExecutions DESPUES de una ejecucion de hoy")
    ib.sleep(3)
    despues = resumir(ib.reqExecutions(ExecutionFilter()), "reqExecutions")

    print(f"\n  ANTES: {len(antes)}   DESPUES: {len(despues)}")
    if len(despues) > len(antes):
        print("  -> CONFIRMADO: reqExecutions SI funciona; lo que no")
        print("     sobrevive es el historico de dias anteriores.")
    else:
        print("  -> La ejecucion NO aparece pese a acabar de ocurrir. El")
        print("     problema esta en la llamada, no en la ventana.")

    # ------------------------------------------------------------------
    separador("4) Anatomia de la ejecucion (preguntas pendientes del sondeo)")
    nuestras = [f for f in despues if f.execution.orderId == trade.order.orderId]
    if nuestras:
        f = nuestras[0]
        print("  -- Fill.execution --")
        volcar(f.execution, saltar=())
        print("\n  -- Fill.commissionReport --")
        volcar(f.commissionReport, saltar=())
        t = f.execution.time
        print(f"\n  execution.time es {type(t).__name__}, tzinfo={getattr(t,'tzinfo',None)}")
        print("  CLAVE: commissionReport sin currency = comision NO llegada,")
        print("  no comision cero (leccion de T36).")

    # ------------------------------------------------------------------
    separador("5) fills() frente a reqExecutions")
    print(f"  ib.fills(): {len(ib.fills())}   reqExecutions: {len(despues)}")

    ib.disconnect()
    print("\nSondeo terminado.")


if __name__ == "__main__":
    main()
