/**
 * Pantalla de cartera.
 *
 * Refresca sola cada environment.refrescoMs. El canal reqAccountUpdates de
 * IB no empuja mas rapido que eso, asi que bajar el intervalo daria mas
 * peticiones pero no datos mas frescos.
 *
 * Cuando un precio cambia entre dos refrescos, la celda destella en verde
 * o rojo durante un instante: es la convencion de las terminales de
 * contratacion y es lo que convierte una tabla estatica en algo que merece
 * la pena tener abierto.
 */

import { CurrencyPipe, DatePipe, DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';

import { environment } from '../../../environments/environment';
import { AccountSummary, Portfolio, Position } from '../../models/api.models';
import { ApiService } from '../../services/api.service';

/** Sentido de un cambio de precio, para el destello de la celda. */
type Sentido = 'sube' | 'baja';

@Component({
  selector: 'app-cartera',
  imports: [CurrencyPipe, DatePipe, DecimalPipe],
  templateUrl: './cartera.html',
  styleUrl: './cartera.scss',
})
export class Cartera implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);

  readonly cuenta = signal<AccountSummary | null>(null);
  readonly cartera = signal<Portfolio | null>(null);
  readonly cargando = signal(true);
  readonly error = signal<string | null>(null);
  readonly actualizado = signal<Date | null>(null);

  /** Ticker -> sentido del ultimo cambio de precio. Se vacia solo. */
  readonly destellos = signal<Record<string, Sentido>>({});

  /** Divisa base de la cuenta. Todos los totales estan en ella. */
  readonly divisaBase = computed(() => this.cartera()?.base_currency ?? '');

  /**
   * Divisa en que cotizan las posiciones, si es unica.
   *
   * Encabeza las columnas de precio. Si hubiera varias queda vacia y la
   * divisa pasa a mostrarse fila a fila, que es el unico sitio donde
   * entonces significa algo.
   */
  readonly divisaPrecios = computed(() => {
    const divisas = new Set((this.cartera()?.positions ?? []).map((p) => p.currency));
    return divisas.size === 1 ? [...divisas][0]! : '';
  });

  readonly variasDivisas = computed(
    () => new Set((this.cartera()?.positions ?? []).map((p) => p.currency)).size > 1,
  );

  /** Hay al menos una posicion que no cotiza en la divisa base. */
  readonly hayConversion = computed(() =>
    (this.cartera()?.positions ?? []).some((p) => p.fx_rate !== 1),
  );

  /** Rentabilidad no realizada sobre el coste, en porcentaje. */
  readonly rentabilidad = computed(() => {
    const c = this.cartera();
    if (!c || c.total_cost === 0) {
      return 0;
    }
    return (c.total_unrealized_pnl / c.total_cost) * 100;
  });

  private temporizador?: ReturnType<typeof setInterval>;
  private apagados: ReturnType<typeof setTimeout>[] = [];

  ngOnInit(): void {
    this.cargar();
    this.temporizador = setInterval(() => this.cargar(), environment.refrescoMs);
  }

  ngOnDestroy(): void {
    clearInterval(this.temporizador);
    this.apagados.forEach(clearTimeout);
  }

  /**
   * Peso de una posicion sobre el valor total, en porcentaje.
   *
   * Se calcula sobre los importes ya convertidos a divisa base: con
   * posiciones en monedas distintas, los pesos calculados sobre importes
   * nativos estarian mal.
   *
   * Vive en el cliente porque hoy solo alimenta la cinta de asignacion.
   * Cuando llegue el analisis de concentracion pasara a portfolio_service,
   * que es donde puede contrastarse con un limite.
   */
  peso(p: Position): number {
    const total = this.cartera()?.total_market_value ?? 0;
    return total === 0 ? 0 : (p.market_value_base / total) * 100;
  }

  /** Clase de destello activa para un ticker, si la hay. */
  destello(symbol: string): string {
    return this.destellos()[symbol] ?? '';
  }

  cargar(): void {
    this.error.set(null);
    forkJoin({
      cuenta: this.api.getAccount(),
      cartera: this.api.getPortfolio(),
    }).subscribe({
      next: ({ cuenta, cartera }) => {
        this.marcarCambios(cartera);
        this.cuenta.set(cuenta);
        this.cartera.set(cartera);
        this.actualizado.set(new Date());
        this.cargando.set(false);
      },
      error: (e: HttpErrorResponse) => {
        this.error.set(this.mensaje(e));
        this.cargando.set(false);
      },
    });
  }

  /** Compara con la cartera anterior y enciende el destello donde toque. */
  private marcarCambios(nueva: Portfolio): void {
    const anterior = this.cartera();
    if (!anterior) {
      return;
    }

    const previos = new Map(anterior.positions.map((p) => [p.symbol, p.market_price]));
    const encendidos: Record<string, Sentido> = {};

    for (const p of nueva.positions) {
      const antes = previos.get(p.symbol);
      if (antes === undefined || antes === p.market_price) {
        continue;
      }
      encendidos[p.symbol] = p.market_price > antes ? 'sube' : 'baja';
    }

    if (Object.keys(encendidos).length === 0) {
      return;
    }

    this.destellos.set(encendidos);
    this.apagados.push(setTimeout(() => this.destellos.set({}), 900));
  }

  /**
   * Traduce el fallo HTTP a algo que el usuario pueda accionar.
   *
   * El 503 no es un fallo del programa: es el caso previsto de Gateway
   * caido, que ocurre a diario por su reinicio automatico. Merece un
   * mensaje que diga que hacer.
   */
  private mensaje(e: HttpErrorResponse): string {
    if (e.status === 503) {
      return 'IB Gateway no responde. Arráncalo e inicia sesión: la cartera se recuperará sola.';
    }
    if (e.status === 0) {
      return 'No se alcanza el backend. Comprueba que uvicorn está levantado en el puerto 8000.';
    }
    return `El backend respondió ${e.status}. Revisa su consola.`;
  }
}
