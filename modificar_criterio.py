from decimal import Decimal
from comun import (dynamodb, NO_AUTORIZADO, PESOS_DEFAULT, INVERTIDOS, respuesta,
                   autenticar)

def lambda_handler(event, context):
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
