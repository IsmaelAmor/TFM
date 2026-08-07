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
from datetime import date

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


# ---------------------------------------------------------------------
# Valor en riesgo (VaR)
# ---------------------------------------------------------------------
#
# Los dos VaR responden a la misma pregunta —cuánto puedo perder en un día
# con una confianza dada— por dos caminos distintos, y se publican juntos
# a propósito: al 95 % suelen parecerse y al 99 % el paramétrico sale MÁS
# BAJO que el histórico. No es un error de cálculo. La normal no tiene
# colas gordas y los mercados sí, así que la hipótesis de normalidad
# infravalora justo los días que importan. Enseñar la divergencia y
# explicarla vale más que elegir uno de los dos y callar el otro.
#
# Convención de signo: el VaR se devuelve como PÉRDIDA POSITIVA en tanto
# por uno (0,032 = 3,2 % del valor de la cartera). Devolverlo negativo
# obligaría a recordar el signo en cada sitio donde se consuma.


def _z_de_confianza(confianza: float) -> float | None:
    """Cuantil de la normal estándar para la cola izquierda.

    Se saca de statistics.NormalDist en vez de fijar 1,645 y 2,326 a mano
    porque así la función admite cualquier nivel de confianza sin tocar
    código, y sin arrastrar scipy como dependencia por dos constantes.
    """
    if not 0.0 < confianza < 1.0:
        return None
    return statistics.NormalDist().inv_cdf(1.0 - confianza)


def _perdida_desde_log(cuantil_log: float) -> float:
    """Traduce un cuantil de rendimiento logarítmico a pérdida real.

    Esta conversión es la hermana de D-21 y la misma trampa: la serie es
    logarítmica, pero el dinero no. Un cuantil log de -0,05 NO es una
    pérdida del 5 %, es del 4,88 %. Publicar el cuantil tal cual da un
    número plausible y equivocado, que es la peor clase de error porque
    nadie lo mira dos veces.

    Se acota en cero: si el cuantil sale positivo (muestra sin apenas días
    malos), la lectura correcta es que a ese nivel de confianza no se
    espera pérdida, no una "pérdida negativa".
    """
    return max(0.0, -math.expm1(cuantil_log))


def var_historico(rendimientos: list[float], confianza: float = 0.95) -> float | None:
    """VaR histórico a un día: cuantil empírico de la muestra.

    No supone ninguna distribución. Ordena los rendimientos observados y
    lee directamente el peor de cada cien (al 99 %) o de cada veinte (al
    95 %). Si en el año hubo un desplome del 9 %, ese desplome está en el
    cálculo con su tamaño real, no aplanado por una campana de Gauss.

    Se interpola linealmente entre las dos observaciones que rodean la
    posición buscada, en vez de redondear a la más cercana: con 251 barras
    la posición del 99 % cae en 2,5, y quedarse con la 2 o con la 3 cambia
    el resultado por un artefacto de redondeo.

    Exige al menos una observación en la cola (n >= 1/(1-confianza)): al
    99 % son 100 días. Por debajo de eso el cuantil lo decidiría el peor
    dato suelto de la muestra, y eso no es una estimación. Devuelve None,
    no cero: un cero diría "no hay riesgo", que es lo contrario de "no hay
    datos suficientes para medirlo".
    """
    if _z_de_confianza(confianza) is None:
        return None

    n = len(rendimientos)
    if n < 2 or n < math.ceil(1.0 / (1.0 - confianza)):
        return None

    ordenados = sorted(rendimientos)
    posicion = (1.0 - confianza) * (n - 1)
    bajo = math.floor(posicion)
    alto = math.ceil(posicion)

    if bajo == alto:
        cuantil = ordenados[bajo]
    else:
        peso = posicion - bajo
        cuantil = ordenados[bajo] * (1.0 - peso) + ordenados[alto] * peso

    return _perdida_desde_log(cuantil)


def var_parametrico(rendimientos: list[float], confianza: float = 0.95) -> float | None:
    """VaR paramétrico a un día suponiendo rendimientos normales.

    Estima media y desviación típica muestrales (n-1, coherente con
    volatilidad_anualizada) y lee el cuantil de la normal. La media se
    incluye en vez de suponerla cero: a un día es casi irrelevante, pero
    suponerla cero es una hipótesis gratuita cuando el dato está ahí.

    Aquí NO se exige muestra en la cola, al contrario que en el histórico,
    y la razón es la diferencia de fondo entre los dos métodos: este no
    mira la cola, la extrapola de la campana. Puede dar un VaR al 99 % con
    treinta observaciones, lo cual es a la vez su ventaja (funciona con
    series cortas) y su peligro (contesta con la misma seguridad tenga o
    no fundamento). Basta con que la desviación sea calculable.
    """
    z = _z_de_confianza(confianza)
    if z is None or len(rendimientos) < 2:
        return None

    desviacion = statistics.stdev(rendimientos)
    # Sin dispersion el VaR NO es cero: es la perdida cierta. Una serie
    # que cae un 2 % todos los dias tiene riesgo aunque no tenga
    # incertidumbre. Aqui habia un atajo que devolvia cero en ese caso,
    # confundiendo 'no se mueve' con 'no pierde'. Lo destapo la prueba
    # test_el_var_es_una_perdida_positiva.

    media = statistics.fmean(rendimientos)
    return _perdida_desde_log(media + z * desviacion)


# ---------------------------------------------------------------------
# Alineacion de series (T47)
# ---------------------------------------------------------------------


def alinear_series(series: list[dict[date, float]]) -> list[list[float]]:
    """Recorta N series de cierres a las fechas que TODAS comparten.

    Las funciones de agregacion (covarianza, correlacion, volatilidad de
    cartera) exigen series de igual longitud, y hasta aqui esa exigencia se
    cumplia por casualidad: dos instrumentos del mismo mercado suelen tener
    el mismo numero de sesiones. Pero no siempre. Una plaza tiene festivos
    que otra no, un valor puede haber estado suspendido, y una accion que
    salio a bolsa hace ocho meses tiene menos barras que un ano.

    Emparejar por POSICION en la lista cuando las fechas no coinciden es un
    error silencioso y grave: se calcularian correlaciones entre el martes
    de un valor y el miercoles de otro. El numero sale, parece razonable y
    esta mal. Por eso se cruza por fecha y se conserva solo la
    interseccion.

    Devuelve una lista por serie, todas de la misma longitud y en orden
    cronologico. Si no hay ninguna fecha comun, devuelve listas vacias: es
    la respuesta honesta, y la capa de arriba la traduce a "sin datos
    suficientes" en vez de inventarse una metrica.
    """
    if not series:
        return []

    comunes = set(series[0])
    for s in series[1:]:
        comunes &= set(s)

    fechas = sorted(comunes)
    return [[s[f] for f in fechas] for s in series]
