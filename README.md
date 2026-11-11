# ms-priorizacion

Microservicio de Priorizacion de proyectos del SaaS PPM. Calcula un puntaje por proyecto
(criterios con pesos) y arma el ranking.

## Despliegue (va AL FINAL)

1. Desplegados antes: `ms-auth`, `ms-proyectos`, `ms-presupuestos` (y `ms-tareas`, `ms-recursos`).
   Se suscribe a los temas `tema-proyectos` y `tema-presupuestos`, y a la cola `cola-proyectos-eventos`.
2. `serverless deploy`

Crea: 6 Lambdas, tablas `t_criterios` y `t_puntajes` (2 GSI), tema `tema-priorizacion`,
cola `cola-priorizacion-eventos` (+ DLQ) y 3 suscripciones SNS -> SQS con filtro.

## Rutas (todas piden la cabecera `Authorization`)

| Ruta | Lambda | Cuerpo |
| --- | --- | --- |
| POST /criterios/listar | ListarCriterios | (vacio) |
| PUT /criterios/modificar | ModificarCriterio | criterio_id (valor, urgencia, costo, riesgo), peso (0 a 1) |
| POST /priorizacion/evaluar | EvaluarProyecto | proyecto_id, valores: {valor, urgencia, costo, riesgo} (1 a 5) |
| POST /puntajes/buscar | BuscarPuntaje | proyecto_id |
| POST /puntajes/ranking | ListarRanking | portafolio_id?, limit?, last_key? |

## Como se calcula

Pesos por defecto: valor 0.4, urgencia 0.3, costo 0.2, riesgo 0.1 (cada tenant puede cambiarlos).
Costo y riesgo se INVIERTEN (6 - valor) porque un valor alto es malo.

    puntaje = suma(peso x valor) / suma(pesos)

Ejemplo: valor 5, urgencia 4, costo 3, riesgo 2
-> 0.4x5 + 0.3x4 + 0.2x(6-3) + 0.1x(6-2) = 2 + 1.2 + 0.6 + 0.4 = 4.2

Prioridad: puntaje >= 3.5 ALTA, >= 2.5 MEDIA, menor BAJA.
Si cambias los pesos, los puntajes ya guardados no se recalculan hasta evaluar de nuevo.

## Eventos

- Consume `ProyectoCreado` (tema-proyectos): crea el puntaje inicial con valores 3 (prioridad MEDIA).
- Consume `PresupuestoExcedido` (tema-presupuestos): pone el criterio costo en 5, recalcula y
  publica `PuntajeActualizado`.
- Publica `PuntajeActualizado` (tema-priorizacion) al evaluar o recalcular. Proyectos lo consume
  y actualiza el campo `prioridad` del proyecto.

## Prueba rapida

1. Login y poner el token en `Authorization`.
2. `POST /priorizacion/evaluar` con
   `{"proyecto_id": "<id>", "valores": {"valor": 5, "urgencia": 4, "costo": 3, "riesgo": 2}}`
   -> puntaje 4.2, prioridad ALTA.
3. `POST /proyectos/buscar` en ms-proyectos: `prioridad` = ALTA (unos segundos despues).
4. `POST /puntajes/ranking` con `{}`.
5. Exceder el presupuesto del proyecto (ver ms-presupuestos): su puntaje baja por el criterio costo.
