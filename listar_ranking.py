from boto3.dynamodb.conditions import Key
from comun import dynamodb, NO_AUTORIZADO, respuesta, autenticar, parametros_lista

def lambda_handler(event, context):
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
