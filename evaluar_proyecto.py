import os
from decimal import Decimal
from comun import (dynamodb, NO_AUTORIZADO, PESOS_DEFAULT, VALOR_NEUTRO, respuesta,
                   autenticar, buscar_proyecto, cargar_pesos, guardar_puntaje, publicar)

def lambda_handler(event, context):
    # Proteger el Lambda
    sesion = autenticar(event)
    if not sesion:
        return NO_AUTORIZADO
    tenant_id = sesion['tenant_id']
    # Entrada (json): valores = {valor, urgencia, costo, riesgo}, cada uno de 1 a 5
    body = event.get('body') or {}
    proyecto_id = body.get('proyecto_id')
    entrada = body.get('valores') or {}
    if not proyecto_id or not entrada:
        return respuesta(400, mensaje='Falta proyecto_id o valores')
    # Proceso 1: el proyecto es de ms-proyectos (de ahi sale su portafolio_id)
    proyecto = buscar_proyecto(event, proyecto_id)
    if not proyecto:
        return respuesta(404, mensaje='El proyecto no existe')
    # Proceso 2: los criterios que no se envian conservan su valor anterior (o 3 si es la primera vez)
    actual = dynamodb.Table('t_puntajes').get_item(
        Key={'tenant_id': tenant_id, 'proyecto_id': proyecto_id}).get('Item', {})
    valores = dict(actual.get('valores', {}))
    for criterio in PESOS_DEFAULT:
        if criterio in entrada:
            try:
                v = Decimal(str(entrada[criterio]))
            except Exception:
                v = Decimal('0')
            if v < 1 or v > 5:
                return respuesta(400, mensaje=f'{criterio} debe ser un numero entre 1 y 5')
            valores[criterio] = v
        else:
            valores.setdefault(criterio, VALOR_NEUTRO)
    # Proceso 3: puntaje con los pesos del tenant
    item = guardar_puntaje(tenant_id, proyecto_id, proyecto.get('portafolio_id'),
                           valores, cargar_pesos(tenant_id))
    # Evento para Proyectos (actualiza prioridad)
    publicar(os.environ['TOPIC_PRIORIZACION_ARN'], 'PuntajeActualizado', tenant_id,
             {'proyecto_id': proyecto_id, 'puntaje': item['puntaje'],
              'prioridad': item['prioridad']})
    # Salida (json)
    return respuesta(200, puntaje=item)
