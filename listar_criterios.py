from comun import (NO_AUTORIZADO, INVERTIDOS, respuesta, autenticar, cargar_pesos)

def lambda_handler(event, context):
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
