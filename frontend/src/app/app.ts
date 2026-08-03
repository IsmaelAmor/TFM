/**
 * Armazon de la aplicacion.
 *
 * Solo tiene una responsabilidad propia: mostrar si hay sesion con IB
 * Gateway y con que cuenta. Va aqui y no en la pantalla de cartera porque
 * afecta a toda la aplicacion, y porque /session responde precisamente
 * cuando el resto de endpoints no pueden.
 */

import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { SessionInfo } from './models/api.models';
import { ApiService } from './services/api.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);

  readonly sesion = signal<SessionInfo | null>(null);

  private temporizador?: ReturnType<typeof setInterval>;

  ngOnInit(): void {
    this.comprobar();
    this.temporizador = setInterval(() => this.comprobar(), 15_000);
  }

  ngOnDestroy(): void {
    clearInterval(this.temporizador);
  }

  /** Cuenta activa, o cadena vacia si aun no hay sesion. */
  cuentaActiva(): string {
    return this.sesion()?.accounts[0] ?? '';
  }

  private comprobar(): void {
    this.api.getSession().subscribe({
      next: (s) => this.sesion.set(s),
      error: () => this.sesion.set(null),
    });
  }
}
