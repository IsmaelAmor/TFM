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


# --- Agregación de cartera (el argumento diferencial del TFM) ------------
#
# El riesgo de una cartera NO es la suma de los riesgos de sus posiciones.
# Dos acciones que no se mueven a la vez se compensan en parte, y la
# volatilidad del conjunto queda por debajo de la suma ponderada de las
# individuales. Ese "beneficio de diversificación" es lo que distingue este
# módulo de un CRUD, y para medirlo hace falta la covarianza entre series,
# no solo la volatilidad de cada una.
#
# Identidad de Markowitz: la varianza diaria de una cartera con pesos w es
#   σ² = Σ_i Σ_j  w_i · w_j · Cov(r_i, r_j)
# es decir, la forma cuadrática wᵀ Σ w sobre la matriz de covarianzas Σ. La
# volatilidad anualizada es su raíz por √252, igual que en una posición.
#
# Las series de rendimientos que reciben estas funciones deben estar
# ALINEADAS por fecha y tener la misma longitud; de eso se encarga la capa
# que las construye a partir de los cierres. Aquí una longitud distinta es
# un error de programación, no un dato posible, y por eso se lanza en vez
# de devolver None.


def covarianza_muestral(r_a: list[float], r_b: list[float]) -> float | None:
    """Covarianza muestral (n-1) entre dos series de rendimientos alineadas."""
    if len(r_a) != len(r_b):
        raise ValueError("Las series de rendimientos deben tener la misma longitud")
    if len(r_a) < 2:
        return None
    return statistics.covariance(r_a, r_b)


def correlacion(r_a: list[float], r_b: list[float]) -> float | None:
    """Correlación de Pearson entre dos series, o None si alguna es plana.

    Se calcula como Cov(a,b) / (σ_a · σ_b). Una serie sin variación (precio
    congelado) no tiene correlación definida: dividir por su σ=0 sería un
    error, así que se devuelve None. El frontend lo pinta como "n/d", que
    es información distinta de una correlación de cero.
    """
    if len(r_a) != len(r_b):
        raise ValueError("Las series de rendimientos deben tener la misma longitud")
    if len(r_a) < 2:
        return None
    s_a = statistics.stdev(r_a)
    s_b = statistics.stdev(r_b)
    if s_a == 0 or s_b == 0:
        return None
    return statistics.covariance(r_a, r_b) / (s_a * s_b)


def matriz_correlacion(series: list[list[float]]) -> list[list[float | None]]:
    """Matriz de correlaciones entre N series de rendimientos.

    Simétrica y con 1 en la diagonal (una serie está perfectamente
    correlada consigo misma). Es lo que el frontend pinta como mapa de
    calor: verde donde dos posiciones se mueven juntas, rojo donde se
    compensan. Ese mapa es la lectura visual del beneficio de
    diversificación.
    """
    n = len(series)
    return [[correlacion(series[i], series[j]) for j in range(n)] for i in range(n)]


def volatilidad_cartera(
    pesos: list[float], series: list[list[float]]
) -> float | None:
    """Volatilidad anualizada de la cartera como conjunto (wᵀ Σ w).

    Los pesos son la fracción de cada posición sobre el valor total de la
    cartera y deben sumar aproximadamente 1; la capa que llama es la
    responsable de calcularlos. Si alguna serie es demasiado corta para
    tener covarianza, la métrica del conjunto no está definida y se
    devuelve None en lugar de un número a medias.
    """
    if len(pesos) != len(series):
        raise ValueError("Debe haber un peso por cada serie")
    n = len(pesos)
    if n == 0:
        return None

    varianza_diaria = 0.0
    for i in range(n):
        for j in range(n):
            cov = covarianza_muestral(series[i], series[j])
            if cov is None:
                return None
            varianza_diaria += pesos[i] * pesos[j] * cov

    # El redondeo de coma flotante puede dejar la varianza en un negativo
    # ínfimo cuando la cancelación es casi total (cartera perfectamente
    # cubierta). Matemáticamente una varianza no es negativa: se acota a 0
    # para no romper la raíz.
    if varianza_diaria < 0:
        varianza_diaria = 0.0

    return math.sqrt(varianza_diaria) * math.sqrt(DIAS_HABILES_ANO)


def volatilidad_suma_ponderada(
    pesos: list[float], series: list[list[float]]
) -> float | None:
    """Suma ponderada de las volatilidades individuales: Σ w_i · σ_i.

    Es el número INGENUO, el que se obtiene si se ignora la correlación
    entre posiciones. Sobreestima el riesgo porque supone que todo cae a la
    vez. No es la volatilidad de la cartera; se calcula a propósito para
    CONTRASTARLA con volatilidad_cartera(): la diferencia entre ambas es,
    exactamente, el beneficio de diversificación, y enseñarlas juntas es el
    argumento central de la memoria.
    """
    if len(pesos) != len(series):
        raise ValueError("Debe haber un peso por cada serie")
    total = 0.0
    for w, r in zip(pesos, series):
        v = volatilidad_anualizada(r)
        if v is None:
            return None
        total += w * v
    return total


# --- Rendimiento ajustado por riesgo y concentración (T45) ---------------
#
# La volatilidad sola no basta para juzgar una cartera: dos carteras que se
# mueven igual de bruscamente no son igual de buenas si una renta el doble.
# Y una cartera puede tener volatilidad baja y aun así estar mal repartida,
# con casi todo en dos valores. Las dos métricas de aquí abajo cubren esos
# dos huecos: una relativiza el riesgo contra el rendimiento, la otra mide
# el reparto con independencia de cómo se muevan los precios.


def rendimiento_anualizado(rendimientos: list[float]) -> float | None:
    """Rendimiento anualizado en términos CONTINUOS (logarítmicos).

    Es la media de los rendimientos diarios multiplicada por 252. Al ser
    logarítmicos se suman en el tiempo, así que anualizar es multiplicar y
    no componer: esa aditividad es justo la razón por la que se eligieron
    (D-19).

    El número que devuelve NO es el "ha subido un X %" de una ficha
    comercial: para leerlo así hay que pasarlo a rendimiento simple con
    exp(r) - 1. Se deja en continuo porque es lo que consume el ratio de
    Sharpe, y convertir de ida y vuelta solo añadiría redondeos.

    Una serie vacía devuelve None: sin ningún salto medido no hay
    rendimiento que anualizar.
    """
    if not rendimientos:
        return None
    return statistics.fmean(rendimientos) * DIAS_HABILES_ANO


def ratio_sharpe(
    rendimientos: list[float], tasa_libre_riesgo: float = 0.0
) -> float | None:
    """Rendimiento excedente por unidad de riesgo asumido.

    Sharpe = (rendimiento anualizado - tasa libre de riesgo) / volatilidad
    anualizada. Es la métrica que relativiza: un 20 % de volatilidad es
    caro si renta un 5 % y barato si renta un 30 %.

    La tasa se recibe como rendimiento SIMPLE anual (0,03 = 3 %) porque es
    como se publica, y se convierte a continua con ln(1 + tasa) antes de
    restarla. Mezclar un numerador logarítmico con una tasa simple no
    rompe nada: devuelve un número plausible pero equivocado, que es peor
    que un fallo ruidoso.

    El valor por defecto de 0 NO es una estimación de la tasa real: es un
    neutro deliberado para poder probar la función sin cablear un dato de
    mercado. Con tasa 0 el cociente es rendimiento entre volatilidad, no
    el Sharpe estricto. La tasa efectiva la pasa la capa que llama.

    Devuelve None cuando la volatilidad es None (serie demasiado corta) o
    cero (precio congelado): dividir por cero daría infinito, y un Sharpe
    infinito es un dato falso, no un dato excelente.
    """
    if tasa_libre_riesgo <= -1:
        raise ValueError("La tasa libre de riesgo no puede ser -100 % o menos")

    r = rendimiento_anualizado(rendimientos)
    vol = volatilidad_anualizada(rendimientos)
    if r is None or vol is None or vol == 0:
        return None
    return (r - math.log(1 + tasa_libre_riesgo)) / vol


def indice_herfindahl(pesos: list[float]) -> float | None:
    """Índice de concentración de Herfindahl-Hirschman: la suma de w².

    Mide cuánta cartera está en pocas manos. Vale 1 cuando todo el dinero
    está en una sola posición y 1/n cuando el reparto entre n posiciones es
    perfectamente uniforme, así que baja al diversificar.

    Es el complemento de la matriz de correlaciones y mide algo distinto:
    la matriz dice si las posiciones se mueven juntas, el índice dice si
    hay demasiado peso en pocas. Una cartera puede estar bien descorrelada
    y pésimamente repartida, y al revés.

    Los pesos son fracciones del valor total de la cartera y deben sumar
    aproximadamente 1; los calcula la capa que llama, igual que en
    volatilidad_cartera. La aplicación veta los cortos, así que todos los
    pesos son positivos.

    Una cartera vacía devuelve None: la concentración de nada no es cero,
    sencillamente no está definida.
    """
    if not pesos:
        return None
    return sum(w * w for w in pesos)


def posiciones_efectivas(pesos: list[float]) -> float | None:
    """Número equivalente de posiciones IGUALES: 1 / Herfindahl.

    Traduce el índice a algo legible sin saber qué es un Herfindahl: una
    cartera de ocho valores con 4,2 posiciones efectivas está, en cuanto a
    concentración, tan expuesta como si solo tuviera cuatro a partes
    iguales. Es la cifra que va al panel; el índice crudo se reserva para
    el detalle.

    Devuelve None si el índice no está definido o es cero, caso que solo se
    da con la lista de pesos vacía.
    """
    h = indice_herfindahl(pesos)
    if h is None or h == 0:
        return None
    return 1 / h
