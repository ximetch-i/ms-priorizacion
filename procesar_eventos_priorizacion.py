import json
import os
from decimal import Decimal
from comun import (dynamodb, PESOS_DEFAULT, VALOR_NEUTRO, cargar_pesos, guardar_puntaje,
                   publicar)

tabla = dynamodb.Table('t_puntajes')


def lambda_handler(event, context):
    # Entrada: mensajes de SQS; el cuerpo es el sobre de SNS y 'Message' es nuestro JSON
    for registro in event['Records']:
        sobre = json.loads(registro['body'])
        msg = json.loads(sobre['Message'])
        tipo = msg.get('tipo_evento')
        tenant_id = msg['tenant_id']
        proyecto_id = msg.get('proyecto_id')
        print('Evento recibido:', tipo, tenant_id, proyecto_id)
        # Proceso
        if tipo == 'ProyectoCreado':
            # Puntaje inicial con valores neutros (3). Si ya existe, no se toca (idempotente).
            existe = tabla.get_item(Key={'tenant_id': tenant_id, 'proyecto_id': proyecto_id})
            if 'Item' not in existe:
                valores = {c: VALOR_NEUTRO for c in PESOS_DEFAULT}
                guardar_puntaje(tenant_id, proyecto_id, msg.get('portafolio_id'),
                                valores, cargar_pesos(tenant_id))
                # No se publica PuntajeActualizado: el proyecto ya nace con prioridad MEDIA
        elif tipo == 'PresupuestoExcedido':
            # El criterio de costo pasa a 5 (el peor) y se recalcula el puntaje
            actual = tabla.get_item(Key={'tenant_id': tenant_id, 'proyecto_id': proyecto_id}).get('Item', {})
            valores = dict(actual.get('valores', {c: VALOR_NEUTRO for c in PESOS_DEFAULT}))
            valores['costo'] = Decimal('5')
            item = guardar_puntaje(tenant_id, proyecto_id, actual.get('portafolio_id'),
                                   valores, cargar_pesos(tenant_id))
            publicar(os.environ['TOPIC_PRIORIZACION_ARN'], 'PuntajeActualizado', tenant_id,
                     {'proyecto_id': proyecto_id, 'puntaje': item['puntaje'],
                      'prioridad': item['prioridad']})
        else:
            print('Tipo de evento ignorado:', tipo)
    # Salida
    return {'statusCode': 200}
