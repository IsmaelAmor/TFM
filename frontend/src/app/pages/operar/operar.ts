/**
 * Pantalla de operativa (T58, T59).
 *
 * Reune en un solo flujo el buscador de instrumentos (T58) y el ticket de
 * compra/venta (T59) sobre los endpoints que el backend ya expone. No
 * añade reglas de negocio: la decision de si una orden es admisible vive
 * en el backend (order_service), y aqui solo se pinta su veredicto. Eso es
 * deliberado: la misma validacion protege la API la use quien la use, y
 * duplicarla en el cliente crearia un segundo sitio donde equivocarse.
 *
 * El flujo es una maquina de cuatro fases que se recorren en orden:
 *
 *   buscando   -> el usuario escribe y elige un instrumento
 *   componiendo-> fija accion, tipo, cantidad y (si LMT) precio limite
 *   validada   -> se ha pedido el veredicto y se muestran motivos y avisos
 *   enviada    -> la orden se curso y se sigue su estado hasta que resuelve
 *
 * Invariante que hace del panel una garantia y no un adorno: el envio solo
 * es posible desde 'validada' con accepted=true, y CUALQUIER cambio en los
 * campos vuelve la fase a 'componiendo' e invalida el veredicto anterior.
 * Asi no se puede enviar una orden distinta de la que el backend aprobo.
 */

import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DecimalPipe } from '@angular/common';
import { Subject, Subscription, of } from 'rxjs';
import {
  catchError,
  debounceTime,
  distinctUntilChanged,
  switchMap,
} from 'rxjs/operators';

import {
  Instrument,
  OrderRequest,
  OrderResult,
  OrderValidation,
  Quote,
} from '../../models/api.models';
import { ApiService } from '../../services/api.service';

/** Fase del flujo de operativa. Ver el bloque de cabecera del fichero. */
type Fase = 'buscando' | 'componiendo' | 'validada' | 'enviada';

@Component({
  selector: 'app-operar',
  imports: [FormsModule, DecimalPipe],
  templateUrl: './operar.html',
  styleUrl: './operar.scss',
})
export class Operar implements OnDestroy {
  private readonly api = inject(ApiService);

  // ---- Estado del flujo
  readonly fase = signal<Fase>('buscando');

  // ---- Buscador (T58)
  readonly termino = signal('');
  readonly resultados = signal<Instrument[]>([]);
  readonly buscando = signal(false);
  readonly seleccionado = signal<Instrument | null>(null);
  readonly precio = signal<Quote | null>(null);

  // ---- Formulario de orden (T59)
  readonly accion = signal<'BUY' | 'SELL'>('BUY');
  readonly tipo = signal<'MKT' | 'LMT'>('MKT');
  readonly cantidad = signal<number | null>(null);
  readonly limite = signal<number | null>(null);

  // ---- Veredicto y envio
  readonly validacion = signal<OrderValidation | null>(null);
  readonly validando = signal(false);
  readonly resultado = signal<OrderResult | null>(null);
  readonly enviando = signal(false);
  readonly error = signal<string | null>(null);

  /**
   * El termino escrito pasa por aqui antes de llegar a la API.
   *
   * debounceTime(700) agrupa las pulsaciones: no se busca por cada tecla,
   * sino tras 700 ms de silencio. Es una eleccion informada por un limite
   * real de IB, que solo admite una peticion de reqMatchingSymbols por
   * segundo; sin esta espera, escribir rapido dispararia una rafaga que IB
   * cortaria. distinctUntilChanged evita repetir la busqueda si el texto
   * acaba igual que la ultima vez (p. ej. escribir y borrar una letra).
   *
   * NOTA (limitacion conocida, para la memoria): el debounce protege a un
   * usuario que teclea, no de dos pestañas a la vez. Un espaciado duro de
   * las llamadas tendria que vivir en el backend; queda fuera de T58.
   */
  private readonly consulta = new Subject<string>();
  private readonly sub: Subscription;

  constructor() {
    this.sub = this.consulta
      .pipe(
        debounceTime(700),
        distinctUntilChanged(),
        switchMap((q) => {
          const limpio = q.trim();
          if (limpio.length === 0) {
            this.buscando.set(false);
            return of<Instrument[]>([]);
          }
          this.buscando.set(true);
          // catchError DENTRO del switchMap: un fallo de una busqueda no
          // debe matar el flujo, o el buscador dejaria de responder tras
          // el primer error de red. Se traga el error y devuelve vacio.
          return this.api.searchInstruments(limpio).pipe(
            catchError(() => {
              this.error.set('No se pudo buscar. Reintenta en un momento.');
              return of<Instrument[]>([]);
            }),
          );
        }),
      )
      .subscribe((lista) => {
        this.buscando.set(false);
        this.resultados.set(lista);
      });
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }

  // -------------------------------------------------------------------
  // Buscador
  // -------------------------------------------------------------------

  /** Cada tecla del buscador entra por aqui. */
  alEscribir(texto: string): void {
    this.termino.set(texto);
    this.error.set(null);
    this.consulta.next(texto);
  }

  /**
   * El usuario elige un instrumento de la lista.
   *
   * Se pasa a 'componiendo' y se pide el precio en paralelo. El precio es
   * informativo: ayuda a decidir, pero el coste real de la orden lo calcula
   * el backend en la validacion, con su propio colchon sobre datos
   * retrasados. No se bloquea el formulario si el precio tarda o falla.
   */
  elegir(inst: Instrument): void {
    this.seleccionado.set(inst);
    this.resultados.set([]);
    this.termino.set(`${inst.symbol} · ${inst.name}`);
    this.precio.set(null);
    this.fase.set('componiendo');
    this.invalidar();

    this.api.getQuote(inst.con_id).subscribe({
      next: (q) => this.precio.set(q),
      error: () => this.precio.set(null),
    });
  }

  /** Vuelve al buscador desde cualquier punto, dejando el formulario limpio. */
  reiniciar(): void {
    this.seleccionado.set(null);
    this.precio.set(null);
    this.termino.set('');
    this.resultados.set([]);
    this.cantidad.set(null);
    this.limite.set(null);
    this.accion.set('BUY');
    this.tipo.set('MKT');
    this.validacion.set(null);
    this.resultado.set(null);
    this.error.set(null);
    this.fase.set('buscando');
  }

  // -------------------------------------------------------------------
  // Formulario: cualquier cambio invalida el veredicto anterior
  // -------------------------------------------------------------------

  /**
   * Descarta el veredicto y devuelve el flujo a 'componiendo'.
   *
   * Es el corazon de la garantia: se llama desde cada campo del formulario,
   * de modo que el boton de enviar (que solo aparece en 'validada') se
   * esfuma en cuanto el usuario cambia algo. Lo que se envie sera siempre
   * lo que se valido.
   */
  private invalidar(): void {
    this.validacion.set(null);
    this.error.set(null);
    if (this.fase() === 'validada') {
      this.fase.set('componiendo');
    }
  }

  ponAccion(a: 'BUY' | 'SELL'): void {
    this.accion.set(a);
    this.invalidar();
  }

  ponTipo(t: 'MKT' | 'LMT'): void {
    this.tipo.set(t);
    // Al volver a mercado, el precio limite deja de tener sentido.
    if (t === 'MKT') {
      this.limite.set(null);
    }
    this.invalidar();
  }

  ponCantidad(valor: string): void {
    const n = valor === '' ? null : Number(valor);
    this.cantidad.set(n !== null && Number.isFinite(n) ? n : null);
    this.invalidar();
  }

  ponLimite(valor: string): void {
    const n = valor === '' ? null : Number(valor);
    this.limite.set(n !== null && Number.isFinite(n) ? n : null);
    this.invalidar();
  }

  /**
   * ¿Estan los campos minimamente completos para pedir validacion?
   *
   * Es una comprobacion de forma, no de fondo: que haya cantidad positiva y,
   * si es limitada, un precio positivo. No decide si la orden es admisible
   * (eso es del backend); solo evita llamar a la API con un formulario a
   * medias.
   */
  readonly puedeValidar = computed(() => {
    const c = this.cantidad();
    if (c === null || c <= 0) {
      return false;
    }
    if (this.tipo() === 'LMT') {
      const l = this.limite();
      if (l === null || l <= 0) {
        return false;
      }
    }
    return this.seleccionado() !== null;
  });

  /** Arma el cuerpo de la peticion a partir del formulario. */
  private ordenActual(): OrderRequest {
    return {
      con_id: this.seleccionado()!.con_id,
      action: this.accion(),
      order_type: this.tipo(),
      quantity: this.cantidad()!,
      limit_price: this.tipo() === 'LMT' ? this.limite() : null,
    };
  }

  // -------------------------------------------------------------------
  // Validacion y envio
  // -------------------------------------------------------------------

  /** Pide el veredicto previo. No envia nada. */
  validar(): void {
    if (!this.puedeValidar()) {
      return;
    }
    this.validando.set(true);
    this.error.set(null);
    this.api.validateOrder(this.ordenActual()).subscribe({
      next: (v) => {
        this.validacion.set(v);
        this.fase.set('validada');
        this.validando.set(false);
      },
      error: (e: HttpErrorResponse) => {
        this.error.set(this.mensaje(e));
        this.validando.set(false);
      },
    });
  }

  /**
   * Envia la orden. Solo es alcanzable con un veredicto accepted=true.
   *
   * El backend la vuelve a validar antes de cursarla, asi que esto no es un
   * atajo. Tras enviar, si la orden queda viva (estado 'activa'), se sondea
   * su estado hasta que resuelve.
   */
  enviar(): void {
    const v = this.validacion();
    if (!v || !v.accepted) {
      return;
    }
    this.enviando.set(true);
    this.error.set(null);
    this.api.submitOrder(this.ordenActual()).subscribe({
      next: (r) => {
        this.resultado.set(r);
        this.fase.set('enviada');
        this.enviando.set(false);
        if (r.estado === 'activa' && r.order_id) {
          this.seguir(r.order_id);
        }
      },
      error: (e: HttpErrorResponse) => {
        this.error.set(this.mensaje(e));
        this.enviando.set(false);
      },
    });
  }

  /**
   * Sondea el estado de una orden viva hasta que deja de estarlo.
   *
   * Una limitada que no cruza queda 'activa'; este sondeo la sigue por si
   * se ejecuta o se cancela. Se detiene sola cuando el estado ya no es
   * 'activa'. Un intervalo de 2 s es de sobra: no es dato de mercado, es el
   * ciclo de vida de una orden, que cambia despacio.
   */
  private seguir(orderId: number): void {
    const t = setInterval(() => {
      this.api.getOrder(orderId).subscribe({
        next: (r) => {
          this.resultado.set(r);
          if (r.estado !== 'activa') {
            clearInterval(t);
          }
        },
        error: () => clearInterval(t),
      });
    }, 2000);
    this.seguimientos.push(t);
  }

  private seguimientos: ReturnType<typeof setInterval>[] = [];

  /** Traduce el fallo HTTP a algo accionable para el usuario. */
  private mensaje(e: HttpErrorResponse): string {
    if (e.status === 0) {
      return 'No hay conexión con el backend. ¿Está arrancado en el puerto 8000?';
    }
    if (e.status === 404) {
      return 'El instrumento o la orden no existe.';
    }
    if (e.status === 503) {
      return 'IB Gateway no está disponible. Revisa que esté arrancado.';
    }
    if (e.error?.detail) {
      return String(e.error.detail);
    }
    return `Error ${e.status}. Reintenta en un momento.`;
    
  }

  /**
   * Traduce el estado interno de la orden a una etiqueta legible.
   *
   * El backend usa un vocabulario propio (ejecutada, activa, rechazada,
   * cancelada, no_enviada) que es preciso pero seco. Aqui se humaniza para
   * la pantalla sin perder el matiz: 'no_enviada' no es lo mismo que
   * 'rechazada' —la primera la paro yo antes de llegar a IB, la segunda la
   * tumba IB— y las dos etiquetas lo dicen.
   */
  etiquetaEstado(estado: OrderResult['estado']): string {
    const etiquetas: Record<OrderResult['estado'], string> = {
      ejecutada: 'Ejecutada',
      activa: 'Activa en el mercado',
      rechazada: 'Rechazada por IB',
      cancelada: 'Cancelada',
      no_enviada: 'No enviada (bloqueada por la validación)',
    };
    return etiquetas[estado];
  }

}