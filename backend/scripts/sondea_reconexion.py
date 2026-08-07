"""
sondea_reconexion.py — Por que no converge la reconexion (T29).

RNF-04 dice que la app debe sobrevivir al reinicio diario del Gateway.
Hoy no lo hace: IB contesta error 326 ("client id already in use") y el
ciclo de reintentos se queda ahi. Antes de escribir el arreglo hay que
saber cual de las dos causas posibles es la de verdad.

  Hipotesis 1: el Gateway tarda en liberar el clientId de la sesion
  muerta. Si es esto, basta con esperar (backoff) o rotar el id.

  Hipotesis 2: nos lo hacemos nosotros. El dashboard sondea cada 5 s, asi
  que al caerse la sesion hay varias peticiones concurrentes llamando a
  ensure_connected() a la vez, todas sobre la MISMA instancia de IB y con
  el MISMO clientId. Si eso se pisa a si mismo, ningun backoff lo arregla:
  hace falta un candado.

Preguntas concretas que este sondeo tiene que contestar:

  a) Que excepcion exacta (tipo y mensaje) levanta connectAsync cuando IB
     responde 326, y si el 326 llega ademas por errorEvent.
  b) En que estado queda el objeto IB tras un connectAsync fallido. Si
     queda sucio, reintentar sobre el mismo objeto nunca converge y el
     arreglo pasa por limpiarlo antes de cada intento.
  c) Cuanto tarda IB en liberar un clientId tras una desconexion limpia.
     Ese numero decide si el backoff es viable o hay que rotar el id.
  d) Que ocurre con dos connectAsync concurrentes sobre la misma
     instancia. Esta es la reproduccion del escenario real de produccion.

Usa clientIds 80 y 81: el 1 lo ocupa uvicorn, el 74-77 los otros sondeos
y el 99 compara_posiciones. Puede correr con uvicorn levantado.

Ejecutar desde backend/ con el venv activado y el Gateway arrancado:
    python scripts/sondea_reconexion.py
"""

import asyncio
import os
import time

from dotenv import load_dotenv
from ib_async import IB

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))

ID_A = 80
ID_B = 81

# Ruido rutinario del arranque de sesion. OJO: aqui NO se silencian los
# 1100/1101/1102 (perdida y recuperacion de conectividad) como en los
# otros sondeos, porque en este son justamente el objeto de estudio.
CODIGOS_RUIDO = {2104, 2106, 2107, 2108, 2119, 2158, 10167}


def separador(titulo):
    print()
    print("=" * 72)
    print(titulo)
    print("=" * 72)


def vigilar(ib, etiqueta):
    """Suscribe los eventos que cuentan la verdad sobre la conexion.

    IB no lanza excepciones para casi nada: manda mensajes por errorEvent.
    Sin este manejador, un 326 se ve como un timeout mudo, que es
    exactamente el sintoma que tenemos en produccion.
    """

    def al_error(*args):
        # Firma variable a proposito: ib_async ha ido anadiendo parametros
        # a este evento entre versiones.
        req_id = args[0] if len(args) > 0 else None
        codigo = args[1] if len(args) > 1 else None
        mensaje = args[2] if len(args) > 2 else ""
        if codigo in CODIGOS_RUIDO:
            return
        print(f"    [evento {etiqueta}] error codigo={codigo} reqId={req_id}: {mensaje}")

    def al_desconectar():
        print(f"    [evento {etiqueta}] disconnectedEvent")

    def al_conectar():
        print(f"    [evento {etiqueta}] connectedEvent")

    ib.errorEvent += al_error
    ib.disconnectedEvent += al_desconectar
    ib.connectedEvent += al_conectar


def estado(ib, etiqueta):
    """Radiografia del objeto. connState es el estado interno del socket."""
    conn = getattr(ib.client, "connState", "?")
    cid = getattr(ib.client, "clientId", "?")
    print(f"    estado {etiqueta}: isConnected={ib.isConnected()} "
          f"connState={conn!r} clientId={cid!r}")


async def intentar(ib, client_id, etiqueta, timeout=8):
    """Un intento de conexion, cronometrado y sin abortar el sondeo."""
    t0 = time.monotonic()
    try:
        await ib.connectAsync(HOST, PORT, clientId=client_id, timeout=timeout)
        dt = time.monotonic() - t0
        print(f"    CONECTA en {dt:.2f}s (clientId={client_id})")
        estado(ib, etiqueta)
        return True
    except Exception as e:  # noqa: BLE001
        dt = time.monotonic() - t0
        print(f"    FALLA en {dt:.2f}s (clientId={client_id}) -> "
              f"{type(e).__name__}: {e or '(sin mensaje)'}")
        estado(ib, etiqueta)
        # Los mensajes de IB llegan por un canal aparte y pueden tardar un
        # instante mas que la excepcion. Sin esta espera, la causa real
        # apareceria impresa dentro de la seccion siguiente.
        await asyncio.sleep(1.5)
        return False


async def main():
    print(f"Gateway en {HOST}:{PORT}")

    # ------------------------------------------------------------------
    separador("1) Conexion sana de referencia (A, clientId=80)")
    ib_a = IB()
    vigilar(ib_a, "A")
    if not await intentar(ib_a, ID_A, "A"):
        print("  No hay linea con el Gateway. Nada mas que sondear.")
        return
    print(f"    serverVersion={ib_a.client.serverVersion()} "
          f"cuentas={ib_a.managedAccounts()}")

    # ------------------------------------------------------------------
    separador("2) El 326: segundo objeto, MISMO clientId")
    print("  Esto reproduce a voluntad el fallo de produccion.")
    ib_b = IB()
    vigilar(ib_b, "B")
    await intentar(ib_b, ID_A, "B")

    # ------------------------------------------------------------------
    separador("3) Reintento sobre el MISMO objeto ya fallido")
    print("  Si el objeto queda sucio tras fallar, reintentar sobre el")
    print("  nunca converge y el arreglo pasa por limpiarlo antes.")
    await intentar(ib_b, ID_A, "B")

    # ------------------------------------------------------------------
    separador("4) El mismo objeto fallido, pero rotando el clientId")
    print("  Si esto conecta, rotar el id es una salida valida.")
    rotacion_ok = await intentar(ib_b, ID_B, "B")
    if rotacion_ok:
        print("    Desconectando B para no dejar sesiones vivas.")
        ib_b.disconnect()
        await asyncio.sleep(1)

    # ------------------------------------------------------------------
    separador("5) Cuanto tarda IB en liberar un clientId tras desconectar")
    print("  Este numero decide si el backoff basta o hay que rotar.")
    ib_a.disconnect()
    t_desc = time.monotonic()
    print(f"    A desconectado. isConnected={ib_a.isConnected()}")
    await asyncio.sleep(1)

    ib_c = IB()
    vigilar(ib_c, "C")
    for intento in range(1, 6):
        transcurrido = time.monotonic() - t_desc
        print(f"\n  Intento {intento}, a los {transcurrido:.2f}s de la desconexion:")
        if await intentar(ib_c, ID_A, "C"):
            print(f"    >>> El clientId {ID_A} se libero en menos de "
                  f"{time.monotonic() - t_desc:.2f}s")
            break
        await asyncio.sleep(3)
    else:
        print(f"    >>> El clientId {ID_A} NO se libero en 5 intentos.")

    if ib_c.isConnected():
        ib_c.disconnect()
        await asyncio.sleep(1)

    # ------------------------------------------------------------------
    separador("6) La carrera: dos connectAsync concurrentes, MISMA instancia")
    print("  Reproduccion del escenario real: el dashboard sondea cada 5 s,")
    print("  la sesion se cae y varias peticiones entran a reconectar a la")
    print("  vez sobre el mismo objeto _ib. Si esto se pisa a si mismo, el")
    print("  arreglo necesita un candado y no solo reintentos.")
    ib_r = IB()
    vigilar(ib_r, "R")
    resultados = await asyncio.gather(
        intentar(ib_r, ID_A, "R1"),
        intentar(ib_r, ID_A, "R2"),
        return_exceptions=True,
    )
    print(f"\n    Resultados de la carrera: {resultados}")
    print(f"    Estado final tras la carrera:")
    estado(ib_r, "R")

    # ------------------------------------------------------------------
    separador("7) Limpieza")
    for nombre, ib in (("A", ib_a), ("B", ib_b), ("C", ib_c), ("R", ib_r)):
        if ib.isConnected():
            print(f"  Desconectando {nombre}")
            ib.disconnect()
    await asyncio.sleep(1)
    print("  Sesiones vivas al terminar: "
          f"{[n for n, ib in (('A', ib_a), ('B', ib_b), ('C', ib_c), ('R', ib_r)) if ib.isConnected()]}")

    print("\nSondeo terminado.")


if __name__ == "__main__":
    asyncio.run(main())
