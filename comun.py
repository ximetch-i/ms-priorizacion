import json
import boto3
from datetime import datetime
from decimal import Decimal
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
_lambda = boto3.client('lambda')
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


def autenticar(event):
    """Valida el token con ValidarTokenAcceso.
    Devuelve {'tenant_id', 'usuario_id', 'rol', ...} o None si no es valido."""
    token = _token(event)
    if not token:
        return None
    r = _lambda.invoke(FunctionName='ValidarTokenAcceso',
                       InvocationType='RequestResponse',
                       Payload=json.dumps({'token': token}))
    datos = json.loads(r['Payload'].read())
    if datos.get('statusCode') != 200:
        return None
    return datos


def buscar_proyecto(event, proyecto_id):
    """Pide el proyecto a ms-proyectos (Lambda BuscarProyecto). Devuelve el dict o None."""
    payload = {'headers': {'Authorization': _token(event)},
               'body': {'proyecto_id': proyecto_id}}
    r = _lambda.invoke(FunctionName='BuscarProyecto',
                       InvocationType='RequestResponse',
                       Payload=json.dumps(payload))
    datos = json.loads(r['Payload'].read())
    return datos.get('proyecto') if datos.get('statusCode') == 200 else None


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
