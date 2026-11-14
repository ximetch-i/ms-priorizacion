# Lambda Criterios (ms-priorizacion). Una sola Lambda atiende varios endpoints.
# API Gateway (integration: lambda) manda en "requestPath" la ruta del recurso.
from comun import NO_AUTORIZADO, INVERTIDOS, respuesta, autenticar, cargar_pesos, dynamodb, PESOS_DEFAULT
from decimal import Decimal


def listar_criterios(event, context):
    # Proteger el Lambda
    sesion = autenticar(event)
    if not sesion:
        return NO_AUTORIZADO
    tenant_id = sesion['tenant_id']
    # Proceso: pesos guardados del tenant, o los por defecto si nunca los cambio
    pesos = cargar_pesos(tenant_id)
    criterios = [{'criterio_id': c, 'peso': p, 'invertido': c in INVERTIDOS}
                 for c, p in pesos.items()]
    # Salida (json)
    return respuesta(200, items=criterios, suma_pesos=sum(pesos.values()))


def modificar_criterio(event, context):
    # Proteger el Lambda
    sesion = autenticar(event)
    if not sesion:
        return NO_AUTORIZADO
    tenant_id = sesion['tenant_id']
    # Entrada (json)
    body = event.get('body') or {}
    criterio_id = body.get('criterio_id')
    if criterio_id not in PESOS_DEFAULT:
        return respuesta(400, mensaje='criterio_id debe ser uno de: ' + ', '.join(PESOS_DEFAULT))
    try:
        peso = Decimal(str(body.get('peso')))
    except Exception:
        return respuesta(400, mensaje='peso debe ser un numero entre 0 y 1')
    if peso < 0 or peso > 1:
        return respuesta(400, mensaje='peso debe ser un numero entre 0 y 1')
    # Proceso: update_item crea el criterio si el tenant aun no lo habia modificado
    r = dynamodb.Table('t_criterios').update_item(
        Key={'tenant_id': tenant_id, 'criterio_id': criterio_id},
        UpdateExpression='SET peso = :p, invertido = :i',
        ExpressionAttributeValues={':p': peso, ':i': criterio_id in INVERTIDOS},
        ReturnValues='ALL_NEW'
    )
    # Salida (json): los puntajes ya calculados no se recalculan; los nuevos usan este peso
    return respuesta(200, criterio=r['Attributes'])


RUTAS = {
    '/criterios/listar': listar_criterios,
    '/criterios/modificar': modificar_criterio,
}

def lambda_handler(event, context):
    ruta = (event or {}).get('requestPath')
    funcion = RUTAS.get(ruta)
    if funcion is None:
        return {'statusCode': 404, 'mensaje': 'Ruta no encontrada: %s' % ruta}
    return funcion(event, context)
