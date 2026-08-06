import { Routes } from '@angular/router';

import { Cartera } from './pages/cartera/cartera';
import { Operar } from './pages/operar/operar';

export const routes: Routes = [
  { path: 'cartera', component: Cartera, title: 'Cartera' },
  { path: 'operar', component: Operar, title: 'Operar' },
  { path: '', pathMatch: 'full', redirectTo: 'cartera' },
  { path: '**', redirectTo: 'cartera' },
];