# Lambda Puntajes (ms-priorizacion). Una sola Lambda atiende varios endpoints.
# API Gateway (integration: lambda) manda en "requestPath" la ruta del recurso.
import os
from boto3.dynamodb.conditions import Key
from comun import dynamodb, NO_AUTORIZADO, PESOS_DEFAULT, VALOR_NEUTRO, respuesta, autenticar, buscar_proyecto, cargar_pesos, guardar_puntaje, publicar, parametros_lista
from decimal import Decimal


def evaluar_proyecto(event, context):
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


def buscar_puntaje(event, context):
    # Proteger el Lambda
    sesion = autenticar(event)
    if not sesion:
        return NO_AUTORIZADO
    tenant_id = sesion['tenant_id']
    # Entrada (json)
    proyecto_id = (event.get('body') or {}).get('proyecto_id')
    if not proyecto_id:
        return respuesta(400, mensaje='Falta proyecto_id')
    # Proceso
    r = dynamodb.Table('t_puntajes').get_item(
        Key={'tenant_id': tenant_id, 'proyecto_id': proyecto_id})
    # Salida (json)
    if 'Item' not in r:
        return respuesta(404, mensaje='El proyecto no tiene puntaje')
    return respuesta(200, puntaje=r['Item'])


def listar_ranking(event, context):
    # Proteger el Lambda
    sesion = autenticar(event)
    if not sesion:
        return NO_AUTORIZADO
    tenant_id = sesion['tenant_id']
    # Entrada (json): portafolio_id, limit y last_key son opcionales
    body = event.get('body') or {}
    # Proceso: el indice esta ordenado por puntaje; ScanIndexForward=False = de mayor a menor
    kwargs = parametros_lista(body)
    kwargs['ScanIndexForward'] = False
    if body.get('portafolio_id'):
        kwargs['IndexName'] = 'gsi_portafolio_puntaje'
        kwargs['KeyConditionExpression'] = Key('portafolio_clave').eq(f"{tenant_id}#{body['portafolio_id']}")
    else:
        kwargs['IndexName'] = 'gsi_ranking'
        kwargs['KeyConditionExpression'] = Key('tenant_id').eq(tenant_id)
    r = dynamodb.Table('t_puntajes').query(**kwargs)
    # Salida (json)
    return respuesta(200, items=r['Items'], count=r['Count'],
                     last_key=r.get('LastEvaluatedKey'))


RUTAS = {
    '/priorizacion/evaluar': evaluar_proyecto,
    '/puntajes/buscar': buscar_puntaje,
    '/puntajes/ranking': listar_ranking,
}

def lambda_handler(event, context):
    ruta = (event or {}).get('requestPath')
    funcion = RUTAS.get(ruta)
    if funcion is None:
        return {'statusCode': 404, 'mensaje': 'Ruta no encontrada: %s' % ruta}
    return funcion(event, context)
