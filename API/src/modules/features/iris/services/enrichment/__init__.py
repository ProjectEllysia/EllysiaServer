"""
Enriquecimiento de Iris: lo que se sabe de un indicador preguntando fuera.

Es la primera parte de Iris que hace red hacia fuera —RDAP de un dominio,
seguir los redirects de una URL, reputación en servicios de terceros—, así que
todas comparten un mismo patrón, definido una sola vez aquí:

- ``egress.py``: la única puerta de salida. Solo ``http``/``https`` a puertos
  web, nunca a una dirección privada (tampoco tras un redirect ni si el DNS
  cambia de respuesta entre la comprobación y la conexión), sin credenciales ni
  cookies, con tiempo y tamaño acotados.
- ``policy.py``: el limitador de peticiones por proveedor y la caducidad de la
  caché.

Ninguna consulta se hace sola dentro de un análisis: son siempre bajo demanda,
por un indicador que el usuario ya tiene, y degradan a un estado neutro
(``EnrichmentStatus.UNAVAILABLE``) si el servicio no responde. Nada de lo que
devuelven cambia el veredicto de un análisis.
"""
