"""Métricas de riesgo de la cartera (Fase 5).

Funciones PURAS sobre series de precios de cierre: reciben listas de
números y devuelven números. No hablan con IB ni con HTTP, así que se
prueban con pytest sin Gateway, igual que el mapper y las reglas de
órdenes. No importan fastapi ni ib_async.

La serie de entrada es 1 año de cierres diarios (~251 barras medidas en
DUN684545 el 07/08/2026 con scripts/sondea_historico.py). Se obtiene con
whatToShow=ADJUSTED_LAST, que corrige splits y dividendos: sin ajustar, la
fecha ex-dividendo mete una caída que no es movimiento real de precio, y un
split de 4:1 mete un salto del -75 %; ambos dispararían la volatilidad
medida sin que el precio real se moviera (D-18).

Convenciones de las métricas:
  - Rendimientos LOGARÍTMICOS: r_t = ln(p_t / p_{t-1}). Son aditivos en el
    tiempo y simétricos, lo estándar para estimar volatilidad; para los
    saltos diarios pequeños coinciden casi con los rendimientos simples.
  - Volatilidad ANUALIZADA: desviación típica MUESTRAL (n-1, el estimador
    insesgado) de los rendimientos diarios, escalada por raíz de 252 (los
    días hábiles de un año). Se devuelve como fracción: 0,28 = 28 %.
  - Máximo drawdown: la mayor caída de pico a valle de la serie, como
    fracción POSITIVA: 0,34 = una caída del 34 % desde el máximo.

Sin dependencias numéricas externas: math y statistics del stdlib bastan.
"""

import math
import statistics

# Días hábiles de un año bursátil. Es la constante de anualización y no
# depende del tamaño de la muestra: 251 barras se anualizan igual con 252.
DIAS_HABILES_ANO = 252


def rendimientos_log(cierres: list[float]) -> list[float]:
    """Rendimientos logarítmicos día a día.

    Devuelve n-1 valores para n cierres. Con menos de dos cierres no hay
    ningún salto que medir y devuelve lista vacía en vez de fallar: una
    posición recién abierta puede no tener aún dos sesiones.
    """
    if len(cierres) < 2:
        return []
    return [math.log(cierres[i] / cierres[i - 1]) for i in range(1, len(cierres))]


def volatilidad_anualizada(rendimientos: list[float]) -> float | None:
    """Volatilidad anualizada, o None si no hay rendimientos suficientes.

    La desviación típica muestral necesita al menos dos puntos; con menos,
    la volatilidad no está definida y se devuelve None en lugar de inventar
    un cero. El frontend puede pintar None como "sin datos suficientes",
    que es información distinta de "volatilidad nula".
    """
    if len(rendimientos) < 2:
        return None
    return statistics.stdev(rendimientos) * math.sqrt(DIAS_HABILES_ANO)


def maximo_drawdown(cierres: list[float]) -> float | None:
    """Mayor caída de pico a valle, como fracción positiva.

    Recorre la serie una sola vez llevando el máximo visto hasta cada punto
    (el "pico") y quedándose con la peor caída relativa desde ese pico. Una
    serie que solo sube tiene drawdown 0. Una serie vacía devuelve None.
    """
    if not cierres:
        return None
    pico = cierres[0]
    peor = 0.0
    for c in cierres:
        if c > pico:
            pico = c
        caida = (pico - c) / pico
        if caida > peor:
            peor = caida
    return peor
