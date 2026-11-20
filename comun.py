import json
import time
import boto3
from datetime import datetime
from decimal import Decimal
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
_sns = boto3.client('sns')

NO_AUTORIZADO = {'statusCode': 403, 'mensaje': 'Forbidden - Acceso No Autorizado'}

# Criterios por defecto (si el tenant no ha modificado los pesos)
PESOS_DEFAULT = {'valor': Decimal('0.4'), 'urgencia': Decimal('0.3'),
                 'costo': Decimal('0.2'), 'riesgo': Decimal('0.1')}
# En estos criterios un valor ALTO es MALO, asi que se invierten (6 - valor)
INVERTIDOS = ('costo', 'riesgo')
VALOR_NEUTRO = Decimal('3')


def limpiar(obj):
    """DynamoDB devuelve Decimal; el JSON de salida necesita int/float."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: limpiar(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [limpiar(v) for v in obj]
    return obj


def respuesta(codigo, **campos):
    return {'statusCode': codigo, **limpiar(campos)}


def _token(event):
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    return headers.get('authorization')


# Cache en memoria del contenedor: evita leer t_tokens_acceso en cada peticion
_CACHE_TOKENS = {}
TTL_TOKEN = 60


def autenticar(event):
    """Valida el token leyendo t_tokens_acceso directo (sin invocar otra Lambda: cada
    peticion usa 1 sola Lambda). Devuelve {'tenant_id', 'usuario_id', 'rol'} o None."""
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    token = headers.get('authorization')
    if not token:
        return None
    ahora = time.time()
    guardado = _CACHE_TOKENS.get(token)
    if guardado and guardado[0] > ahora:
        return guardado[1]
    item = dynamodb.Table('t_tokens_acceso').get_item(Key={'token': token}).get('Item')
    if not item or datetime.now().strftime('%Y-%m-%d %H:%M:%S') > item['expires']:
        return None
    datos = {'statusCode': 200, 'tenant_id': item['tenant_id'],
             'usuario_id': item['usuario_id'], 'rol': item['rol']}
    if len(_CACHE_TOKENS) > 200:
        _CACHE_TOKENS.clear()
    _CACHE_TOKENS[token] = (ahora + TTL_TOKEN, datos)
    return datos


def buscar_proyecto(event, proyecto_id):
    """Lee el proyecto de t_proyectos (mismo tenant del token), sin invocar otra Lambda. Devuelve el dict o None."""
    sesion = autenticar(event)
    if not sesion:
        return None
    r = dynamodb.Table('t_proyectos').get_item(
        Key={'tenant_id': sesion['tenant_id'], 'proyecto_id': proyecto_id})
    return r.get('Item')


def parametros_lista(body):
    """Limit y ExclusiveStartKey para paginar un Query."""
    try:
        limit = max(1, min(int(body.get('limit', 20)), 100))
    except (TypeError, ValueError):
        limit = 20
    kwargs = {'Limit': limit}
    if body.get('last_key'):
        kwargs['ExclusiveStartKey'] = body['last_key']
    return kwargs


def publicar(topic_arn, tipo_evento, tenant_id, datos):
    """Publica un evento en SNS. Si falla, no tumba la operacion principal."""
    mensaje = {'tipo_evento': tipo_evento, 'tenant_id': tenant_id, **datos}
    try:
        _sns.publish(
            TopicArn=topic_arn,
            Message=json.dumps(limpiar(mensaje)),
            MessageAttributes={
                'tipo_evento': {'DataType': 'String', 'StringValue': tipo_evento},
                'tenant_id': {'DataType': 'String', 'StringValue': tenant_id}
            }
        )
    except Exception as e:
        print('Error publicando evento:', str(e))


# ---------- Calculo del puntaje ----------

def cargar_pesos(tenant_id):
    """Pesos del tenant: los guardados en t_criterios, o los por defecto."""
    pesos = dict(PESOS_DEFAULT)
    r = dynamodb.Table('t_criterios').query(KeyConditionExpression=Key('tenant_id').eq(tenant_id))
    for item in r['Items']:
        if item['criterio_id'] in pesos:
            pesos[item['criterio_id']] = item['peso']
    return pesos


def calcular_puntaje(valores, pesos):
    """puntaje = suma(peso x valor) / suma(pesos). Costo y riesgo se invierten (6 - valor)."""
    total = sum(pesos.values())
    if total <= 0:
        return Decimal('0')
    suma = Decimal('0')
    for criterio, peso in pesos.items():
        v = Decimal(str(valores[criterio]))
        if criterio in INVERTIDOS:
            v = 6 - v
        suma += peso * v
    return (suma / total).quantize(Decimal('0.01'))


def prioridad_de(puntaje):
    if puntaje >= Decimal('3.5'):
        return 'ALTA'
    if puntaje >= Decimal('2.5'):
        return 'MEDIA'
    return 'BAJA'


def guardar_puntaje(tenant_id, proyecto_id, portafolio_id, valores, pesos):
    """Calcula y guarda el puntaje del proyecto. Devuelve el item guardado."""
    puntaje = calcular_puntaje(valores, pesos)
    item = {
        'tenant_id': tenant_id,
        'proyecto_id': proyecto_id,
        # clave para el ranking por portafolio (siempre presente para que el indice lo incluya)
        'portafolio_clave': f'{tenant_id}#{portafolio_id or "SIN_PORTAFOLIO"}',
        'puntaje': puntaje,
        'prioridad': prioridad_de(puntaje),
        'valores': {k: Decimal(str(v)) for k, v in valores.items()},
        'evaluado_en': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    if portafolio_id:
        item['portafolio_id'] = portafolio_id
    dynamodb.Table('t_puntajes').put_item(Item=item)
    return item
